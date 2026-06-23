from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import SubscriptionPlan, User
from app.schemas import (
    BillingStatusOut,
    CheckoutRequest,
    CheckoutResponse,
    PortalResponse,
    StripeConfigOut,
    VerifySessionRequest,
    VerifySessionResponse,
)
from app.stripe_service import (
    construct_webhook_event,
    create_billing_portal_session,
    create_checkout_session,
    handle_checkout_completed,
    handle_subscription_deleted,
    handle_subscription_updated,
    sync_user_subscription_from_stripe,
    verify_checkout_session,
)
from app.subscription_service import get_plan_usage

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/config", response_model=StripeConfigOut)
async def billing_config():
    return StripeConfigOut(
        stripe_enabled=settings.stripe_enabled,
        publishable_key=settings.stripe_publishable_key or None,
    )


@router.get("/status", response_model=BillingStatusOut)
async def billing_status(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    sync: bool = False,
):
    if sync:
        await sync_user_subscription_from_stripe(db, user)

    usage = await get_plan_usage(db, user)
    sub = usage["subscription"]
    plan = usage["plan"]
    return BillingStatusOut(
        plan_name=plan.name if plan else None,
        plan_id=plan.id if plan else None,
        status=sub.status.value if sub else None,
        is_active=usage["is_active"],
        can_create_task=usage["can_create_task"],
        task_count=usage["task_count"],
        max_tasks=usage["max_tasks"],
        tasks_remaining=usage["tasks_remaining"],
        max_users=usage["max_users"],
        current_period_end=sub.current_period_end if sub else None,
        cancel_at_period_end=sub.cancel_at_period_end if sub else False,
        stripe_subscription_id=sub.stripe_subscription_id if sub else None,
    )


@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(
    body: CheckoutRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.stripe_service import ensure_plan_stripe_price

    plan = await db.get(SubscriptionPlan, body.plan_id)
    if not plan or not plan.is_active:
        raise HTTPException(status_code=404, detail="Plan not found")

    if plan.price_monthly > 0:
        await ensure_plan_stripe_price(db, plan)
        await db.commit()
        await db.refresh(plan)

    try:
        result = await create_checkout_session(db, user, plan)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CheckoutResponse(**result)


@router.post("/portal", response_model=PortalResponse)
async def billing_portal(
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        url = await create_billing_portal_session(user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PortalResponse(portal_url=url)


@router.post("/verify-session", response_model=VerifySessionResponse)
async def verify_session(
    body: VerifySessionRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        sub = await verify_checkout_session(db, user, body.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    plan = sub.plan
    return VerifySessionResponse(
        plan_name=plan.name if plan else "Unknown",
        status=sub.status.value,
    )


@router.post("/sync", response_model=BillingStatusOut)
async def sync_billing(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await sync_user_subscription_from_stripe(db, user)
    usage = await get_plan_usage(db, user)
    sub = usage["subscription"]
    plan = usage["plan"]
    return BillingStatusOut(
        plan_name=plan.name if plan else None,
        plan_id=plan.id if plan else None,
        status=sub.status.value if sub else None,
        is_active=usage["is_active"],
        can_create_task=usage["can_create_task"],
        task_count=usage["task_count"],
        max_tasks=usage["max_tasks"],
        tasks_remaining=usage["tasks_remaining"],
        max_users=usage["max_users"],
        current_period_end=sub.current_period_end if sub else None,
        cancel_at_period_end=sub.cancel_at_period_end if sub else False,
        stripe_subscription_id=sub.stripe_subscription_id if sub else None,
    )


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = construct_webhook_event(payload, sig)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Webhook error: {exc}") from exc

    event_type = event["type"]
    data_object = event["data"]["object"]

    if event_type == "checkout.session.completed":
        await handle_checkout_completed(db, data_object)
    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        await handle_subscription_updated(db, data_object)
    elif event_type == "customer.subscription.deleted":
        await handle_subscription_deleted(db, data_object)
    elif event_type == "invoice.payment_failed":
        from app.models import SubscriptionStatus, UserSubscription

        sub_id = data_object.get("subscription")
        if sub_id:
            sub_row = await db.scalar(
                select(UserSubscription).where(UserSubscription.stripe_subscription_id == sub_id)
            )
            if sub_row:
                sub_row.status = SubscriptionStatus.PAST_DUE
                await db.commit()

    return {"received": True}
