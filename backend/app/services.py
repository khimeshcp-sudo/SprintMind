from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.stripe_service import sync_stripe_catalog
from app.models import (
    SubscriptionPlan,
    SubscriptionStatus,
    Task,
    TaskStatus,
    User,
    UserRole,
    UserSubscription,
)


async def seed_database(db: AsyncSession) -> None:
    """Create default plans and admin user if DB is empty."""
    plan_count = await db.scalar(select(func.count()).select_from(SubscriptionPlan))
    if plan_count and plan_count > 0:
        await _sync_plan_stripe_ids(db)
        await sync_stripe_catalog(db)
        return

    plans = [
        SubscriptionPlan(
            name="Free",
            description="Get started with basic task management",
            price_monthly=0,
            max_tasks=5,
            max_users=1,
        ),
        SubscriptionPlan(
            name="Pro",
            description="For growing teams with more tasks",
            price_monthly=2900,
            max_tasks=50,
            max_users=5,
            stripe_price_id=settings.stripe_price_pro or None,
        ),
        SubscriptionPlan(
            name="Enterprise",
            description="Unlimited tasks and priority support",
            price_monthly=9900,
            max_tasks=500,
            max_users=50,
            stripe_price_id=settings.stripe_price_enterprise or None,
        ),
    ]
    db.add_all(plans)
    await db.flush()

    from app.auth import hash_password

    admin = User(
        email="admin@sprintmind.io",
        full_name="Platform Admin",
        hashed_password=hash_password("admin123"),
        role=UserRole.ADMIN,
    )
    demo = User(
        email="demo@sprintmind.io",
        full_name="Demo User",
        hashed_password=hash_password("demo123"),
        role=UserRole.USER,
    )
    db.add_all([admin, demo])
    await db.flush()

    enterprise = plans[2]
    db.add(
        UserSubscription(
            user_id=admin.id,
            plan_id=enterprise.id,
            status=SubscriptionStatus.ACTIVE,
            expires_at=datetime.now(UTC) + timedelta(days=365),
        )
    )
    db.add(
        UserSubscription(
            user_id=demo.id,
            plan_id=plans[0].id,
            status=SubscriptionStatus.ACTIVE,
        )
    )
    await db.commit()
    await sync_stripe_catalog(db)


async def _sync_plan_stripe_ids(db: AsyncSession) -> None:
    """Update Stripe price IDs from env on existing plans."""
    mapping = {
        "Pro": settings.stripe_price_pro,
        "Enterprise": settings.stripe_price_enterprise,
    }
    changed = False
    for name, price_id in mapping.items():
        if not price_id:
            continue
        plan = await db.scalar(select(SubscriptionPlan).where(SubscriptionPlan.name == name))
        if plan and plan.stripe_price_id != price_id:
            plan.stripe_price_id = price_id
            changed = True
    if changed:
        await db.commit()


async def dashboard_stats(db: AsyncSession, user: User) -> dict:
    from app.subscription_service import get_plan_usage

    usage = await get_plan_usage(db, user)
    base_filter = [] if user.role == UserRole.ADMIN else [Task.user_id == user.id]

    total = await db.scalar(select(func.count()).select_from(Task).where(*base_filter)) or 0
    pending = await db.scalar(
        select(func.count()).select_from(Task).where(Task.status == TaskStatus.PENDING, *base_filter)
    ) or 0
    in_progress = await db.scalar(
        select(func.count()).select_from(Task).where(Task.status == TaskStatus.IN_PROGRESS, *base_filter)
    ) or 0
    completed = await db.scalar(
        select(func.count()).select_from(Task).where(Task.status == TaskStatus.COMPLETED, *base_filter)
    ) or 0

    plan = usage["plan"]
    return {
        "total_tasks": total,
        "pending_tasks": pending,
        "in_progress_tasks": in_progress,
        "completed_tasks": completed,
        "plan_name": plan.name if plan else None,
        "max_tasks": usage["max_tasks"],
        "tasks_remaining": usage["tasks_remaining"],
        "is_active": usage["is_active"],
        "can_create_task": usage["can_create_task"],
    }
