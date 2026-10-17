"""Client-safe error responses.

Internal exception text (SQL fragments, file paths, hostnames, stack details)
belongs in the server log, not in an HTTP response. These helpers log the real
cause under a short error id and hand the client a fixed message plus that id,
so a user can quote it and an operator can find the matching log entry.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException

logger = logging.getLogger("phylo.api.errors")


def new_error_id() -> str:
    return uuid.uuid4().hex[:12]


def log_internal_error(public_message: str, exc: BaseException, *, context: str = "") -> str:
    """Log ``exc`` with a fresh error id and return the id."""
    error_id = new_error_id()
    logger.error(
        "%s error_id=%s%s",
        public_message,
        error_id,
        f" {context}" if context else "",
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return error_id


def internal_error(public_message: str, exc: BaseException, *, context: str = "") -> HTTPException:
    """Build a 500 whose body carries ``public_message`` and an error id only."""
    error_id = log_internal_error(public_message, exc, context=context)
    return HTTPException(
        status_code=500,
        detail={"message": public_message, "error_id": error_id},
    )
