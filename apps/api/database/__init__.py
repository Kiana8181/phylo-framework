from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.base import AsyncSessionLocal, Base, close_db, init_db

__all__ = [
    "Base",
    "get_db",
    "init_db",
    "close_db",
]


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for getting database session.
    On connection/DB errors, raises HTTPException(500) so the client always gets JSON.
    """
    try:
        async with AsyncSessionLocal() as session:
            try:
                yield session
            finally:
                await session.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {e!s}",
        )
