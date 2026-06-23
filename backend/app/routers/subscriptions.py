from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import require_admin
from app.database import get_db
from app.models import SubscriptionPlan, User, UserSubscription
from app.schemas import PlanCreate, PlanOut, PlanUpdate, SubscriptionAssign, SubscriptionOut

router = APIRouter(prefix="/api", tags=["subscriptions"])


# ── Plans ─────────────────────────────────────────────────────────
@router.get("/plans", response_model=list[PlanOut])
async def list_plans(db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(SubscriptionPlan).order_by(SubscriptionPlan.price_monthly))
    return result.scalars().all()


@router.post("/plans", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
async def create_plan(
    body: PlanCreate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    plan = SubscriptionPlan(**body.model_dump())
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.patch("/plans/{plan_id}", response_model=PlanOut)
async def update_plan(
    plan_id: int,
    body: PlanUpdate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    plan = await db.get(SubscriptionPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    plan_id: int,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    plan = await db.get(SubscriptionPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    await db.delete(plan)
    await db.commit()


# ── Subscriptions ─────────────────────────────────────────────────
@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_subscriptions(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(UserSubscription).options(selectinload(UserSubscription.plan)).order_by(UserSubscription.id)
    )
    return result.scalars().all()


@router.post("/subscriptions", response_model=SubscriptionOut, status_code=status.HTTP_201_CREATED)
async def assign_subscription(
    body: SubscriptionAssign,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await db.get(User, body.user_id)
    plan = await db.get(SubscriptionPlan, body.plan_id)
    if not user or not plan:
        raise HTTPException(status_code=404, detail="User or plan not found")

    existing = await db.scalar(select(UserSubscription).where(UserSubscription.user_id == body.user_id))
    if existing:
        existing.plan_id = body.plan_id
        existing.status = body.status
        existing.expires_at = body.expires_at
        sub_id = existing.id
    else:
        sub = UserSubscription(
            user_id=body.user_id,
            plan_id=body.plan_id,
            status=body.status,
            expires_at=body.expires_at,
        )
        db.add(sub)
        await db.flush()
        sub_id = sub.id

    await db.commit()
    result = await db.execute(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(UserSubscription.id == sub_id)
    )
    return result.scalar_one()
