"""Real PostgreSQL fixtures using the isolated test service and actual Alembic migrations.

Root conftest.py selects TEST_DATABASE_URL (port 55432 by default). Missing
infrastructure is a failure, never a skip. Every test truncates only phylo_test.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import all models for repository tests.
import apps.api.database.models  # noqa: F401

_DEFAULT_URL = "postgresql+asyncpg://phylo_test:phylo_test@127.0.0.1:55432/phylo_test"
_BASE_URL = make_url(os.getenv("DATABASE_URL", _DEFAULT_URL))
if "+asyncpg" not in _BASE_URL.drivername:
    _BASE_URL = _BASE_URL.set(drivername="postgresql+asyncpg")

_TEST_DB = os.getenv("TEST_DB_NAME", f"{_BASE_URL.database or 'phylo'}_test")
if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*_test", _TEST_DB):
    raise RuntimeError("Refusing destructive test setup: database name must end in _test")
TEST_URL = _BASE_URL.set(database=_TEST_DB)
_ADMIN_URL = _BASE_URL.set(database="postgres")

# Tables cleared between tests (children first for FK safety; CASCADE covers the rest).
_TRUNCATE_SQL = "TRUNCATE runs, files, users RESTART IDENTITY CASCADE"


async def _ensure_database() -> None:
    """Create the test database if it does not exist (idempotent)."""
    admin = create_async_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": _TEST_DB},
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{_TEST_DB}"'))
    finally:
        await admin.dispose()


@pytest.fixture(scope="session")
def _setup_test_db():
    """Create the test DB + schema once per session (synchronous wrapper).

    Requested via the ``session`` fixture rather than autouse, so that tests
    which need no database (converters, contracts, the preprocessing log) still
    run when Postgres is unreachable instead of skipping the whole suite.
    """
    asyncio.run(_ensure_database())
    # Exercise the actual migration chain, including enum/index/sequence DDL.
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[3],
        env={**os.environ, "DATABASE_URL": TEST_URL.render_as_string(hide_password=False)},
        check=True,
    )
    yield


@pytest_asyncio.fixture
async def session(_setup_test_db) -> AsyncSession:
    """A clean AsyncSession per test (tables truncated up front)."""
    engine = create_async_engine(TEST_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text(_TRUNCATE_SQL))
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session, tmp_path, monkeypatch):
    """Real routes, auth and repositories; isolated DB and on-disk storage."""
    from httpx import ASGITransport, AsyncClient
    from apps.api.main import app
    from apps.api.database import get_db
    from apps.api.storage.local_storage import LocalStorage
    from apps.api.routers import uploads, datasets, files, artifacts

    local = LocalStorage(str(tmp_path / "storage"))
    for module in (uploads, datasets, files, artifacts):
        monkeypatch.setattr(module, "_storage_inst", local)
    async def db_override():
        yield session
    app.dependency_overrides[get_db] = db_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def account(client):
    response = await client.post("/auth/register", json={
        "email": "owner@example.org", "username": "owner", "password": "test-password-123",
    })
    assert response.status_code == 201, response.text
    data = response.json()
    client.headers["Authorization"] = f"Bearer {data['access_token']}"
    return data
