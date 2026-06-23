"""Subscription validation and plan quota enforcement."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import SubscriptionPlan, SubscriptionStatus, Task, User, UserRole, UserSubscription

ACTIVE_STATUSES = {
    SubscriptionStatus.ACTIVE,
    SubscriptionStatus.TRIAL,
}


def _now() -> datetime:
    return datetime.now(UTC)


def is_subscription_usable(sub: UserSubscription | None) -> bool:
    if not sub or not sub.plan or not sub.plan.is_active:
        return False
    if sub.status not in ACTIVE_STATUSES:
        return False
    # Stripe-managed subs use current_period_end; manual/free subs may use expires_at
    period_end = sub.current_period_end or sub.expires_at
    if period_end and period_end < _now():
        return False
    return True


async def get_user_subscription(db: AsyncSession, user: User) -> UserSubscription | None:
    result = await db.execute(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(UserSubscription.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def get_user_plan(db: AsyncSession, user: User) -> SubscriptionPlan | None:
    sub = await get_user_subscription(db, user)
    return sub.plan if sub else None


async def get_user_task_count(db: AsyncSession, user_id: int) -> int:
    return await db.scalar(select(func.count()).select_from(Task).where(Task.user_id == user_id)) or 0


async def get_plan_usage(db: AsyncSession, user: User) -> dict:
    sub = await get_user_subscription(db, user)
    plan = sub.plan if sub else None
    task_count = await get_user_task_count(db, user.id)

    if user.role == UserRole.ADMIN:
        return {
            "subscription": sub,
            "plan": plan,
            "task_count": task_count,
            "tasks_remaining": None,
            "max_tasks": None,
            "max_users": None,
            "is_active": True,
            "can_create_task": True,
        }

    usable = is_subscription_usable(sub)
    max_tasks = plan.max_tasks if plan else 0
    tasks_remaining = max(0, max_tasks - task_count) if plan else 0

    return {
        "subscription": sub,
        "plan": plan,
        "task_count": task_count,
        "tasks_remaining": tasks_remaining,
        "max_tasks": max_tasks,
        "max_users": plan.max_users if plan else 0,
        "is_active": usable,
        "can_create_task": usable and task_count < max_tasks,
    }


async def enforce_task_creation(db: AsyncSession, user: User) -> None:
    """Block task creation unless subscription is active and under plan max_tasks."""
    if user.role == UserRole.ADMIN:
        return

    usage = await get_plan_usage(db, user)
    sub = usage["subscription"]
    plan = usage["plan"]

    if not sub or not plan:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="No subscription found. Choose a plan to start creating tasks.",
        )

    if not usage["is_active"]:
        reason = "Subscription expired or inactive."
        if sub.status == SubscriptionStatus.PAST_DUE:
            reason = "Payment failed. Update your billing to continue."
        elif sub.status == SubscriptionStatus.CANCELLED:
            reason = "Subscription cancelled. Resubscribe to create tasks."
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=reason)

    if not usage["can_create_task"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Task limit reached ({plan.max_tasks} on {plan.name} plan). "
                f"Upgrade your subscription to add more tasks."
            ),
        )


async def assign_free_plan(db: AsyncSession, user: User) -> UserSubscription:
    """Assign the Free plan to a new user."""
    result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.name == "Free", SubscriptionPlan.is_active.is_(True))
    )
    free_plan = result.scalar_one_or_none()
    if not free_plan:
        raise HTTPException(status_code=500, detail="Free plan not configured")

    existing = await get_user_subscription(db, user)
    if existing:
        return existing

    sub = UserSubscription(
        user_id=user.id,
        plan_id=free_plan.id,
        status=SubscriptionStatus.ACTIVE,
        expires_at=None,
    )
    db.add(sub)
    await db.flush()
    await db.refresh(sub, attribute_names=["plan"])
    return sub
