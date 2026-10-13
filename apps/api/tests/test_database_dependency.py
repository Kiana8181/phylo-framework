"""What a client is told when a request fails underneath its database session.

`get_db` wraps every route that uses the database. It used to answer
"Database error: <exception text>" (HTTP 500) for any exception of any such
route: internal text went to the client and the traceback went nowhere. Now a
database that is away is answered as such (503, retry), and everything else
reaches the application's error handler.
"""
from __future__ import annotations

import logging

import asyncpg
import pytest
from fastapi import Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.api import database
from apps.api import main as api_main
from apps.api.database import get_db


class NoDatabaseNeeded:
    """A session stand-in for routes that fail before they would use one."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def close(self):
        return None


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(database, "AsyncSessionLocal", NoDatabaseNeeded)
    test_app = FastAPI()
    test_app.add_exception_handler(StarletteHTTPException, api_main.http_exception_handler)
    test_app.add_exception_handler(Exception, api_main.unhandled_exception_handler)

    @test_app.get("/bug")
    async def bug(db: AsyncSession = Depends(get_db)):
        raise KeyError("users_internal_table.password_hash")

    @test_app.get("/refused")
    async def refused(db: AsyncSession = Depends(get_db)):
        raise HTTPException(409, detail={"code": "DATASET_DELETED", "message": "This dataset has been deleted."})

    @test_app.get("/away")
    async def away(db: AsyncSession = Depends(get_db)):
        raise asyncpg.exceptions.CannotConnectNowError("the database system is starting up at 10.0.0.7:5432")

    @test_app.get("/fine")
    async def fine(db: AsyncSession = Depends(get_db)):
        return {"ok": True}

    return test_app


async def get(app, path):
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        return await client.get(path)


async def test_a_programming_error_reaches_the_error_handler_with_a_reference_and_a_traceback(app, monkeypatch, caplog):
    monkeypatch.setattr(api_main, "IS_PRODUCTION", True)
    with caplog.at_level(logging.ERROR, logger="phylo.api.errors"):
        response = await get(app, "/bug")
    assert response.status_code == 500
    body = response.json()
    assert body["message"] == "Internal server error"                        # nothing internal in production
    assert "password_hash" not in response.text and "Database error" not in response.text
    error_id = body["data"]["error_id"]
    logged = [r for r in caplog.records if error_id in r.getMessage()]
    assert len(logged) == 1 and logged[0].exc_info is not None               # the traceback is in the log, under that id
    assert "KeyError" in logging.Formatter().formatException(logged[0].exc_info)


async def test_a_database_that_is_away_is_answered_as_temporarily_unavailable(app, monkeypatch, caplog):
    monkeypatch.setattr(api_main, "IS_PRODUCTION", False)                     # even outside production
    with caplog.at_level(logging.WARNING, logger="phylo.api.errors"):
        response = await get(app, "/away")
    assert response.status_code == 503 and response.headers["retry-after"] == "5"
    assert response.json()["message"] == "The service is temporarily unavailable. Please try again in a moment."
    assert "10.0.0.7" not in response.text and "starting up" not in response.text
    assert any("database unavailable during a request (CannotConnectNowError)" in r.getMessage() for r in caplog.records)


async def test_a_session_that_cannot_be_opened_is_answered_the_same_way(app, monkeypatch):
    def no_connection():
        raise asyncpg.exceptions.TooManyConnectionsError("sorry, too many clients already")

    monkeypatch.setattr(database, "AsyncSessionLocal", no_connection)
    response = await get(app, "/fine")
    assert response.status_code == 503 and "too many clients" not in response.text


async def test_deliberate_answers_and_successes_pass_through_untouched(app):
    refused = await get(app, "/refused")
    assert refused.status_code == 409 and refused.json()["data"]["code"] == "DATASET_DELETED"
    assert (await get(app, "/fine")).json() == {"ok": True}
