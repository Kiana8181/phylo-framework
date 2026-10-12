"""How long things are kept, and what "expired" means for a run.

RESULT_RETENTION_DAYS (default 60; 0 = keep for ever)
    A run's results are kept this many days after the run ended. The date is
    fixed when the run ends (``runs.expires_at``) and shown to its owner from
    then on; changing the setting later affects runs that end afterwards, never
    a date already promised. Runs that had ended before retention was
    introduced got their date counted from the day of that upgrade.

What expires with a run
    its result files in the object store (including its log), its trees, its
    stored result and logs, and the record of its notification.
What stays
    the run itself as history: method, parameters, dataset name, status,
    message and times, marked as expired (``runs.results_expired_at``).
What never expires by itself
    uploaded datasets. They count against the owner's storage quota until the
    owner deletes them.

Uploads
    MAX_UPLOAD_MB (default 500): largest single file accepted.
    UPLOAD_SESSION_GRACE_HOURS (default 24): an upload that was started and
    never finished is cleaned up after this long.
RETENTION_SWEEP_SECONDS (default 3600): how often the worker looks for expired
    results, and the API for abandoned uploads.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

DEFAULT_RESULT_RETENTION_DAYS = 60
DEFAULT_MAX_UPLOAD_MB = 500
DEFAULT_UPLOAD_SESSION_GRACE_HOURS = 24
DEFAULT_SWEEP_SECONDS = 3600

CODE_RESULT_EXPIRED = "RESULT_EXPIRED"
CODE_UPLOAD_TOO_LARGE = "UPLOAD_TOO_LARGE"


def _number(name: str, default: float, *, minimum: float) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        value = float(raw) if raw else float(default)
    except ValueError:
        return float(default)          # a typo must not switch a limit or the cleanup off
    return value if value >= minimum else float(default)


def result_retention_days() -> float:
    """Days results are kept after a run ends; 0 means they are never removed."""
    return _number("RESULT_RETENTION_DAYS", DEFAULT_RESULT_RETENTION_DAYS, minimum=0)


def retention_period() -> Optional[timedelta]:
    days = result_retention_days()
    return timedelta(days=days) if days > 0 else None


def max_upload_bytes() -> int:
    return int(_number("MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB, minimum=0.000001) * 1024 * 1024)


def upload_session_grace() -> timedelta:
    return timedelta(hours=_number("UPLOAD_SESSION_GRACE_HOURS", DEFAULT_UPLOAD_SESSION_GRACE_HOURS, minimum=0.01))


def sweep_seconds() -> float:
    return _number("RETENTION_SWEEP_SECONDS", DEFAULT_SWEEP_SECONDS, minimum=0.05)


def expired_message(expired_at: Optional[datetime]) -> str:
    when = f" on {expired_at:%Y-%m-%d}" if expired_at else ""
    days = result_retention_days()
    kept = f"Results are kept for {days:g} days after a run ends. " if days > 0 else ""
    return (
        f"The results of this run expired{when} and have been removed. {kept}"
        "The run itself stays in your history; run it again to get new results."
    )
