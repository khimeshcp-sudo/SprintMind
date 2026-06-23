"""Backend API tests."""

import pytest

from tests.conftest import auth_token


@pytest.mark.asyncio
async def test_health(client):
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_login_and_me(client):
    token = await auth_token(client, "user@test.com", "user123")
    res = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["email"] == "user@test.com"


@pytest.mark.asyncio
async def test_create_task_user_scoped(client):
    token = await auth_token(client, "user@test.com", "user123")
    headers = {"Authorization": f"Bearer {token}"}
    res = await client.post("/api/tasks", json={"title": "Test task", "description": "desc"}, headers=headers)
    assert res.status_code == 201
    task = res.json()
    assert task["title"] == "Test task"

    res = await client.get("/api/tasks", headers=headers)
    assert len(res.json()) == 1


@pytest.mark.asyncio
async def test_admin_users_forbidden_for_user(client):
    token = await auth_token(client, "user@test.com", "user123")
    res = await client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_admin_list_users(client):
    token = await auth_token(client, "admin@test.com", "admin123")
    res = await client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert len(res.json()) >= 2
