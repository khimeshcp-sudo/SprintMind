"""Apply schema updates for existing databases."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def migrate_schema(conn: AsyncConnection) -> None:
    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255)",
        "ALTER TABLE subscription_plans ADD COLUMN IF NOT EXISTS stripe_product_id VARCHAR(255)",
        "ALTER TABLE subscription_plans ADD COLUMN IF NOT EXISTS stripe_price_id VARCHAR(255)",
        "ALTER TABLE user_subscriptions ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255)",
        "ALTER TABLE user_subscriptions ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(255)",
        "ALTER TABLE user_subscriptions ADD COLUMN IF NOT EXISTS stripe_price_id VARCHAR(255)",
        "ALTER TABLE user_subscriptions ADD COLUMN IF NOT EXISTS current_period_end TIMESTAMPTZ",
        "ALTER TABLE user_subscriptions ADD COLUMN IF NOT EXISTS cancel_at_period_end BOOLEAN DEFAULT FALSE",
    ]
    for stmt in statements:
        await conn.execute(text(stmt))

    # Extend enum values for PostgreSQL (ignore errors on sqlite / if already exists)
    enum_values = ["past_due", "incomplete"]
    for value in enum_values:
        try:
            await conn.execute(
                text(f"ALTER TYPE subscriptionstatus ADD VALUE IF NOT EXISTS '{value}'")
            )
        except Exception:
            pass

    # Unique indexes for stripe ids (postgres)
    index_statements = [
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_stripe_customer_id ON users (stripe_customer_id) WHERE stripe_customer_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_user_subscriptions_stripe_subscription_id ON user_subscriptions (stripe_subscription_id) WHERE stripe_subscription_id IS NOT NULL",
    ]
    for stmt in index_statements:
        try:
            await conn.execute(text(stmt))
        except Exception:
            pass
