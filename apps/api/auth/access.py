"""Run ownership check shared by every route that exposes a run or its outputs."""
from __future__ import annotations

from fastapi import HTTPException

from apps.api.database.models import Run, User


def ensure_run_access(run: Run, user: User) -> None:
    """Allow the run's owner or an administrator; raise 403 for anyone else.

    A run with no owner (created before authentication became mandatory) is
    visible to administrators only: its UUID alone must not grant access.
    """
    if user.is_admin:
        return
    if run.user_id is None or run.user_id != user.id:
        raise HTTPException(403, "Access denied")
