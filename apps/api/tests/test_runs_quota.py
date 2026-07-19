"""Router-level quota: the per-user queue caps non-terminal runs at MAX_QUEUED + 1
(1 active turn + 5 queued). The next creation returns 409 QUEUE_FULL.

Requires a live Postgres (shares the conftest async DB harness).
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.auth.dependencies import get_current_user
from apps.api.database import get_db
from apps.api.database.models import User
from apps.api.main import app
from apps.api.routers import runs as runs_router


@pytest.fixture
async def test_user(session) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        email=f"quota-{suffix}@test.io",
        username=f"quota-{suffix}",
        password_hash="x",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.fixture
async def client(session, test_user, monkeypatch):
    # A file-less method so create_run needs no upload; a configured service URL so
    # the "no service URL" guard passes.
    monkeypatch.setattr(runs_router, "method_service_url", lambda method: "http://method.test")
    monkeypatch.setattr(runs_router, "get_ui_hints", lambda method: {"requiresFile": False})

    async def _override_db():
        yield session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_quota_full_returns_409(client):
    # 6 non-terminal runs allowed (1 active + 5 queued).
    for i in range(6):
        resp = await client.post("/runs", params={"method": "dowser"}, json={"params": {}})
        assert resp.status_code < 400, f"create #{i + 1} failed: {resp.status_code} {resp.text}"

    # The 7th exceeds the quota.
    resp = await client.post("/runs", params={"method": "dowser"}, json={"params": {}})
    assert resp.status_code == 409
    assert "QUEUE_FULL" in resp.text


async def test_create_reports_queue_position(client):
    # First run becomes the active turn.
    first = await client.post("/runs", params={"method": "dowser"}, json={"params": {}})
    assert first.status_code < 400
    body1 = first.json()
    payload1 = body1.get("data", body1)
    assert payload1["queued"] is False
    assert payload1["queue_position"] is None

    # Second run waits in the personal queue at position 1.
    second = await client.post("/runs", params={"method": "dowser"}, json={"params": {}})
    assert second.status_code < 400
    body2 = second.json()
    payload2 = body2.get("data", body2)
    assert payload2["queued"] is True
    assert payload2["queue_position"] == 1
