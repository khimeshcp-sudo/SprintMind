"""Stripe billing integration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import SubscriptionPlan, SubscriptionStatus, User, UserSubscription
from app.subscription_service import assign_free_plan, get_user_subscription

logger = logging.getLogger(__name__)

stripe.api_key = settings.effective_stripe_secret_key


def _stripe_configured() -> bool:
    key = settings.effective_stripe_secret_key
    return bool(key and key.startswith("sk_"))


def _is_valid_price_id(price_id: str | None) -> bool:
    return bool(price_id and price_id.startswith("price_"))


async def ensure_plan_stripe_price(db: AsyncSession, plan: SubscriptionPlan) -> str | None:
    """Return a Stripe price id for a paid plan, creating catalog entries if needed."""
    if plan.price_monthly == 0:
        return None

    env_map = {
        "Pro": settings.stripe_price_pro,
        "Enterprise": settings.stripe_price_enterprise,
    }
    env_price = env_map.get(plan.name, "")
    if _is_valid_price_id(env_price):
        if plan.stripe_price_id != env_price:
            plan.stripe_price_id = env_price
            await db.flush()
        return env_price

    if _is_valid_price_id(plan.stripe_price_id):
        return plan.stripe_price_id

    if not _stripe_configured():
        return None

    stripe.api_key = settings.effective_stripe_secret_key

    if plan.stripe_product_id:
        try:
            stripe.Product.retrieve(plan.stripe_product_id)
        except stripe.error.InvalidRequestError:
            plan.stripe_product_id = None

    if not plan.stripe_product_id:
        product = stripe.Product.create(
            name=f"SprintMind {plan.name}",
            description=plan.description or f"SprintMind {plan.name} subscription",
            metadata={"plan_name": plan.name, "plan_id": str(plan.id)},
        )
        plan.stripe_product_id = product.id

    price = stripe.Price.create(
        product=plan.stripe_product_id,
        unit_amount=plan.price_monthly,
        currency="usd",
        recurring={"interval": "month"},
        metadata={"plan_name": plan.name, "plan_id": str(plan.id)},
    )
    plan.stripe_price_id = price.id
    await db.flush()
    return price.id


async def sync_stripe_catalog(db: AsyncSession) -> None:
    """Ensure all paid plans have Stripe product/price ids when Stripe is configured."""
    if not _stripe_configured():
        return

    result = await db.execute(
        select(SubscriptionPlan).where(
            SubscriptionPlan.is_active.is_(True),
            SubscriptionPlan.price_monthly > 0,
        )
    )
    plans = result.scalars().all()
    changed = False
    try:
        for plan in plans:
            before = plan.stripe_price_id
            await ensure_plan_stripe_price(db, plan)
            if plan.stripe_price_id != before:
                changed = True
        if changed:
            await db.commit()
    except stripe.error.AuthenticationError:
        logger.warning("Stripe catalog sync skipped: invalid API key")
    except stripe.error.StripeError as exc:
        logger.warning("Stripe catalog sync skipped: %s", exc)


def _ts_to_dt(ts: int | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=UTC)


async def get_or_create_stripe_customer(db: AsyncSession, user: User) -> str:
    if user.stripe_customer_id:
        return user.stripe_customer_id

    if not _stripe_configured():
        raise ValueError("Stripe is not configured")

    customer = stripe.Customer.create(
        email=user.email,
        name=user.full_name,
        metadata={"user_id": str(user.id)},
    )
    user.stripe_customer_id = customer.id
    await db.flush()
    return customer.id


async def create_checkout_session(db: AsyncSession, user: User, plan: SubscriptionPlan) -> dict:
    if plan.price_monthly == 0:
        sub = await get_user_subscription(db, user)
        if sub:
            sub.plan_id = plan.id
            sub.status = SubscriptionStatus.ACTIVE
            sub.stripe_subscription_id = None
            sub.stripe_price_id = None
            sub.current_period_end = None
            sub.cancel_at_period_end = False
        else:
            sub = UserSubscription(
                user_id=user.id,
                plan_id=plan.id,
                status=SubscriptionStatus.ACTIVE,
            )
            db.add(sub)
        await db.commit()
        return {"checkout_url": None, "activated": True, "plan_id": plan.id}

    if not plan.stripe_price_id:
        price_id = await ensure_plan_stripe_price(db, plan)
        if not price_id:
            if not _stripe_configured():
                raise ValueError(
                    "Stripe is not configured. Set STRIPE_SECRET_KEY in .env "
                    "(use your sk_test_... key from Stripe Dashboard)."
                )
            raise ValueError(f"Plan '{plan.name}' has no Stripe price configured")

    if not _stripe_configured():
        raise ValueError("Stripe is not configured. Set STRIPE_SECRET_KEY in .env")

    customer_id = await get_or_create_stripe_customer(db, user)
    await db.commit()

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
        success_url=f"{settings.frontend_url}/billing?success=1&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.frontend_url}/billing?cancelled=1",
        metadata={"user_id": str(user.id), "plan_id": str(plan.id)},
        subscription_data={"metadata": {"user_id": str(user.id), "plan_id": str(plan.id)}},
    )
    return {"checkout_url": session.url, "activated": False, "session_id": session.id}


async def create_billing_portal_session(user: User) -> str:
    if not user.stripe_customer_id:
        raise ValueError("No Stripe customer on file. Subscribe to a paid plan first.")
    if not _stripe_configured():
        raise ValueError("Stripe is not configured")

    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{settings.frontend_url}/billing",
    )
    return session.url


def map_stripe_status(stripe_status: str) -> SubscriptionStatus:
    mapping = {
        "active": SubscriptionStatus.ACTIVE,
        "trialing": SubscriptionStatus.TRIAL,
        "past_due": SubscriptionStatus.PAST_DUE,
        "canceled": SubscriptionStatus.CANCELLED,
        "unpaid": SubscriptionStatus.PAST_DUE,
        "incomplete": SubscriptionStatus.INCOMPLETE,
        "incomplete_expired": SubscriptionStatus.EXPIRED,
        "paused": SubscriptionStatus.CANCELLED,
    }
    return mapping.get(stripe_status, SubscriptionStatus.INCOMPLETE)


async def sync_subscription_from_stripe(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
    stripe_subscription: dict | stripe.Subscription,
) -> UserSubscription:
    if hasattr(stripe_subscription, "to_dict"):
        stripe_subscription = stripe_subscription.to_dict()

    sub_id = stripe_subscription["id"]
    customer_id = stripe_subscription.get("customer")
    status = map_stripe_status(stripe_subscription.get("status", "incomplete"))
    period_end = _ts_to_dt(stripe_subscription.get("current_period_end"))
    if not period_end:
        items = stripe_subscription.get("items", {}).get("data", [])
        if items:
            period_end = _ts_to_dt(items[0].get("current_period_end"))
    cancel_at_period_end = bool(stripe_subscription.get("cancel_at_period_end"))
    price_id = None
    items = stripe_subscription.get("items", {}).get("data", [])
    if items:
        price_id = items[0].get("price", {}).get("id")

    result = await db.execute(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(UserSubscription.user_id == user_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        sub = UserSubscription(user_id=user_id, plan_id=plan_id)
        db.add(sub)

    sub.plan_id = plan_id
    sub.status = status
    sub.stripe_subscription_id = sub_id
    sub.stripe_customer_id = customer_id
    sub.stripe_price_id = price_id
    sub.current_period_end = period_end
    sub.expires_at = period_end
    sub.cancel_at_period_end = cancel_at_period_end

    user = await db.get(User, user_id)
    if user and customer_id:
        user.stripe_customer_id = customer_id

    await db.commit()
    await db.refresh(sub)
    return sub


async def handle_checkout_completed(db: AsyncSession, session: dict) -> None:
    metadata = session.get("metadata") or {}
    user_id = int(metadata.get("user_id", 0))
    plan_id = int(metadata.get("plan_id", 0))
    subscription_id = session.get("subscription")
    if isinstance(subscription_id, dict):
        subscription_id = subscription_id.get("id")
    customer_id = session.get("customer")
    if isinstance(customer_id, dict):
        customer_id = customer_id.get("id")

    if not user_id or not plan_id or not subscription_id:
        return

    stripe_sub = stripe.Subscription.retrieve(subscription_id)
    await sync_subscription_from_stripe(
        db,
        user_id=user_id,
        plan_id=plan_id,
        stripe_subscription=stripe_sub,
    )

    user = await db.get(User, user_id)
    if user and customer_id:
        user.stripe_customer_id = customer_id
        await db.commit()


async def verify_checkout_session(db: AsyncSession, user: User, session_id: str) -> UserSubscription:
    """Activate subscription after Stripe redirect (no webhook required)."""
    if not _stripe_configured():
        raise ValueError("Stripe is not configured")

    stripe.api_key = settings.effective_stripe_secret_key
    session = stripe.checkout.Session.retrieve(session_id, expand=["subscription"])

    if session.payment_status not in ("paid", "no_payment_required"):
        raise ValueError("Checkout payment not completed yet")

    metadata = dict(session.metadata or {})
    session_user_id = int(metadata.get("user_id", 0))
    if session_user_id != user.id:
        raise ValueError("This checkout session belongs to another account")

    session_dict = session.to_dict() if hasattr(session, "to_dict") else dict(session)
    await handle_checkout_completed(db, session_dict)

    result = await db.execute(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(UserSubscription.user_id == user.id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise ValueError("Failed to activate subscription")
    return sub


async def sync_user_subscription_from_stripe(db: AsyncSession, user: User) -> UserSubscription | None:
    """Reconcile DB subscription from Stripe (e.g. after missed webhook)."""
    if not _stripe_configured():
        return None

    stripe.api_key = settings.effective_stripe_secret_key

    customer_id = user.stripe_customer_id
    if not customer_id:
        customers = stripe.Customer.list(email=user.email, limit=1)
        if customers.data:
            customer_id = customers.data[0].id
            user.stripe_customer_id = customer_id
            await db.flush()

    if not customer_id:
        return None

    stripe_subs = stripe.Subscription.list(customer=customer_id, status="all", limit=5)
    active_sub = None
    for s in stripe_subs.data:
        if s.status in ("active", "trialing", "past_due"):
            active_sub = s
            break

    if not active_sub:
        return await get_user_subscription(db, user)

    sub_dict = active_sub.to_dict() if hasattr(active_sub, "to_dict") else dict(active_sub)
    metadata = sub_dict.get("metadata") or {}
    plan_id = int(metadata.get("plan_id", 0))

    if not plan_id:
        items = sub_dict.get("items", {}).get("data", [])
        price_id = items[0].get("price", {}).get("id") if items else None
        if price_id:
            plan = await db.scalar(
                select(SubscriptionPlan).where(SubscriptionPlan.stripe_price_id == price_id)
            )
            if plan:
                plan_id = plan.id

    if not plan_id:
        return await get_user_subscription(db, user)

    return await sync_subscription_from_stripe(
        db,
        user_id=user.id,
        plan_id=plan_id,
        stripe_subscription=active_sub,
    )


async def handle_subscription_updated(db: AsyncSession, stripe_sub: dict) -> None:
    metadata = stripe_sub.get("metadata") or {}
    user_id = int(metadata.get("user_id", 0))
    plan_id = int(metadata.get("plan_id", 0))

    if not user_id:
        result = await db.execute(
            select(UserSubscription).where(UserSubscription.stripe_subscription_id == stripe_sub.get("id"))
        )
        existing = result.scalar_one_or_none()
        if not existing:
            return
        user_id = existing.user_id
        plan_id = existing.plan_id

    await sync_subscription_from_stripe(
        db,
        user_id=user_id,
        plan_id=plan_id,
        stripe_subscription=stripe_sub,
    )


async def handle_subscription_deleted(db: AsyncSession, stripe_sub: dict) -> None:
    sub_id = stripe_sub.get("id")
    result = await db.execute(select(UserSubscription).where(UserSubscription.stripe_subscription_id == sub_id))
    sub = result.scalar_one_or_none()
    if not sub:
        return

    user = await db.get(User, sub.user_id)
    sub.status = SubscriptionStatus.CANCELLED
    sub.stripe_subscription_id = None
    sub.stripe_price_id = None
    sub.current_period_end = None
    sub.cancel_at_period_end = False
    await db.commit()

    if user:
        await assign_free_plan(db, user)
        await db.commit()


def construct_webhook_event(payload: bytes, sig_header: str):
    if not settings.stripe_webhook_secret:
        raise ValueError("STRIPE_WEBHOOK_SECRET not configured")
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
