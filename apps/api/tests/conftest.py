"""Async DB test harness for the run queue.

These tests require a live PostgreSQL (the scheduling logic relies on a real
SEQUENCE, a partial UNIQUE index, and ``SELECT ... FOR UPDATE SKIP LOCKED`` — none
of which SQLite can emulate). They run against a dedicated ``*_test`` database that
is created (and its schema built) once per session, then truncated between tests.

Connection: derived from ``DATABASE_URL`` (same host/creds as dev), with the
database name replaced by ``TEST_DB_NAME`` (default: ``<dbname>_test``). Point
``DATABASE_URL`` at your dev Postgres and these run as-is; without a reachable
Postgres they are skipped/error and the harness gap is expected.
"""
from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import models so Base.metadata is fully populated before create_all.
import apps.api.database.models  # noqa: F401
from apps.api.database.base import Base

_DEFAULT_URL = "postgresql+asyncpg://phylo_user:phylo_pass@127.0.0.1:5432/phylo_db"
_BASE_URL = make_url(os.getenv("DATABASE_URL", _DEFAULT_URL))
if "+asyncpg" not in _BASE_URL.drivername:
    _BASE_URL = _BASE_URL.set(drivername="postgresql+asyncpg")

_TEST_DB = os.getenv("TEST_DB_NAME", f"{_BASE_URL.database or 'phylo'}_test")
TEST_URL = _BASE_URL.set(database=_TEST_DB)
_ADMIN_URL = _BASE_URL.set(database="postgres")

# Raw DDL that migration 009 adds on top of the ORM metadata (create_all makes the
# column + composite index, but not the sequence or the partial-unique backstop).
_SEQUENCE_DDL = "CREATE SEQUENCE IF NOT EXISTS runs_dispatch_seq"
_PARTIAL_UNIQUE_DDL = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_user_active_turn ON runs (user_id)
WHERE user_id IS NOT NULL AND (
    status = 'RUNNING' OR (status = 'QUEUED' AND dispatch_seq IS NOT NULL)
)
"""

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


async def _build_schema() -> None:
    engine = create_async_engine(TEST_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text(_SEQUENCE_DDL))
            await conn.execute(text(_PARTIAL_UNIQUE_DDL))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def _setup_test_db():
    """Create the test DB + schema once per session (synchronous wrapper).

    Requested via the ``session`` fixture rather than autouse, so that tests
    which need no database (converters, contracts, the preprocessing log) still
    run when Postgres is unreachable instead of skipping the whole suite.
    """
    try:
        asyncio.run(_ensure_database())
        asyncio.run(_build_schema())
    except Exception as exc:  # pragma: no cover - environment/harness gap
        pytest.skip(f"Postgres test DB unavailable: {exc}")
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
