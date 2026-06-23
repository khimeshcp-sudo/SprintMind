"""Subscription limit enforcement tests."""

import pytest

from tests.conftest import auth_token


@pytest.mark.asyncio
async def test_task_limit_enforced(client):
    token = await auth_token(client, "user@test.com", "user123")
    headers = {"Authorization": f"Bearer {token}"}

    for i in range(2):
        res = await client.post("/api/tasks", json={"title": f"Task {i}"}, headers=headers)
        assert res.status_code == 201

    res = await client.post("/api/tasks", json={"title": "Over limit"}, headers=headers)
    assert res.status_code == 403
    assert "limit" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_billing_status(client):
    token = await auth_token(client, "user@test.com", "user123")
    headers = {"Authorization": f"Bearer {token}"}
    res = await client.get("/api/billing/status", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["plan_name"] == "Free"
    assert data["max_tasks"] == 2
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_free_plan_checkout_activates(client):
    token = await auth_token(client, "user@test.com", "user123")
    headers = {"Authorization": f"Bearer {token}"}

    plans = await client.get("/api/plans")
    free = next(p for p in plans.json() if p["name"] == "Free")

    res = await client.post("/api/billing/checkout", json={"plan_id": free["id"]}, headers=headers)
    assert res.status_code == 200
    assert res.json()["activated"] is True
