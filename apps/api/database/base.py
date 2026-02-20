from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

from apps.api.config import DATABASE_URL

# Create async engine.
# server_settings timezone=UTC forces PostgreSQL to use UTC so that timestamptz
# values are returned with a safe timezone name. On Windows, other timezone names
# (e.g. numeric like <+00>-00) can cause OSError [Errno 22] Invalid argument
# when Python's zoneinfo/datetime code tries to resolve the timezone.
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    poolclass=NullPool,
    connect_args={"server_settings": {"timezone": "UTC"}},
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Base class for all models
Base = declarative_base()


# get_session is now in __init__.py as FastAPI dependency


async def init_db() -> None:
    """Initialize database - create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()
