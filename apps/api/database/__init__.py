from __future__ import annotations

from typing import AsyncGenerator

import logging

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.base import AsyncSessionLocal, Base, close_db, init_db
from apps.api.database.errors import database_unavailable

logger = logging.getLogger("phylo.api.errors")

__all__ = [
    "Base",
    "get_db",
    "init_db",
    "close_db",
]


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for getting database session.

    Everything a route raises passes through here. Two cases, and nothing else:

    * the database is away (restarting, unreachable): the client is told so
      with 503 and when to try again, which is the truth and lets it retry;
    * anything else is NOT turned into a response here. It goes on to the
      application's error handler, which logs it with a reference id and, in
      production, answers with a fixed message. (This function used to answer
      "Database error: <exception text>" for every exception of every route,
      which hid the traceback and showed internal text to the client.)
    """
    try:
        async with AsyncSessionLocal() as session:
            try:
                yield session
            finally:
                await session.close()
    except HTTPException:
        raise
    except Exception as exc:
        if database_unavailable(exc):
            logger.warning("database unavailable during a request (%s)", type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail="The service is temporarily unavailable. Please try again in a moment.",
                headers={"Retry-After": "5"},
            ) from None
        raise
