"""Internal exception text must reach the server log, never the HTTP client."""
from __future__ import annotations

import logging

import pytest
from httpx import ASGITransport, AsyncClient

import apps.api.main as api_main
from apps.api.main import app

INTERNAL_DETAIL = "connection to 10.0.0.7:5432 failed for user phylo_app /srv/apps/api/secret.py"
BOOM_PATH = "/__test_boom"


@pytest.fixture
async def raw_client():
    async def boom():
        raise RuntimeError(INTERNAL_DETAIL)

    app.add_api_route(BOOM_PATH, boom, methods=["GET"])
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != BOOM_PATH]


async def test_production_hides_unhandled_exception_text(raw_client, monkeypatch, caplog):
    monkeypatch.setattr(api_main, "IS_PRODUCTION", True)
    with caplog.at_level(logging.ERROR, logger="phylo.api.errors"):
        response = await raw_client.get(BOOM_PATH)
    assert response.status_code == 500
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == "Internal server error"
    assert INTERNAL_DETAIL not in response.text
    # The client gets a reference; the log holds the same reference and the cause.
    error_id = body["data"]["error_id"]
    assert len(error_id) == 12
    record = next(r for r in caplog.records if error_id in r.getMessage())
    assert BOOM_PATH in record.getMessage()
    assert INTERNAL_DETAIL in str(record.exc_info[1])


async def test_non_production_keeps_the_message_for_developers(raw_client, monkeypatch):
    monkeypatch.setattr(api_main, "IS_PRODUCTION", False)
    response = await raw_client.get(BOOM_PATH)
    assert response.status_code == 500
    assert response.json()["message"] == INTERNAL_DETAIL
    assert response.json()["data"]["error_id"]


@pytest.mark.integration
async def test_login_failure_returns_fixed_message(client, account, monkeypatch):
    from apps.api.auth import routers

    def explode(*_args, **_kwargs):
        raise RuntimeError(INTERNAL_DETAIL)

    monkeypatch.setattr(routers, "verify_password", explode)
    response = await client.post(
        "/auth/login", json={"email": "owner@example.org", "password": "test-password-123"}
    )
    assert response.status_code == 500
    assert response.json()["message"] == "Login failed."
    assert response.json()["data"]["error_id"]
    assert INTERNAL_DETAIL not in response.text


@pytest.mark.integration
async def test_upload_storage_failure_returns_fixed_message(client, account, monkeypatch):
    from apps.api.routers import uploads

    async def explode(*_args, **_kwargs):
        raise RuntimeError(INTERNAL_DETAIL)

    init = await client.post("/uploads/init", json={"original_filename": "x.fasta"})
    assert init.status_code == 200, init.text
    monkeypatch.setattr(uploads.storage(), "move", explode)
    response = await client.put(init.json()["content_url"], content=b">a\nACGT\n")
    assert response.status_code == 500
    assert response.json()["message"] == "Failed to store upload."
    assert response.json()["data"]["error_id"]
    assert INTERNAL_DETAIL not in response.text


@pytest.mark.integration
async def test_google_url_error_does_not_reveal_configuration(client, monkeypatch):
    from apps.api.auth import google_oauth

    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_ID", "")
    response = await client.get("/auth/google")
    assert response.status_code == 503
    assert response.json()["message"] == "Google sign-in is not available."
