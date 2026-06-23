import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.auth import hash_password
from app.database import Base, async_session, engine, get_db
from app.main import app
from app.models import SubscriptionPlan, SubscriptionStatus, User, UserRole, UserSubscription


@pytest_asyncio.fixture
async def db_session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    async with async_session() as session:
        free_plan = SubscriptionPlan(
            name="Free",
            description="Test free plan",
            price_monthly=0,
            max_tasks=2,
            max_users=1,
        )
        session.add(free_plan)
        await session.flush()

        admin = User(
            email="admin@test.com",
            full_name="Admin",
            hashed_password=hash_password("admin123"),
            role=UserRole.ADMIN,
        )
        user = User(
            email="user@test.com",
            full_name="User",
            hashed_password=hash_password("user123"),
            role=UserRole.USER,
        )
        session.add_all([admin, user])
        await session.flush()

        session.add(
            UserSubscription(
                user_id=user.id,
                plan_id=free_plan.id,
                status=SubscriptionStatus.ACTIVE,
            )
        )
        await session.commit()

    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def auth_token(client, email, password):
    res = await client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
    )
    return res.json()["access_token"]
