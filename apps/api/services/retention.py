"""How long things are kept, and what "expired" means for a run or a dataset.

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

DATASET_RETENTION_DAYS (default 60; 0 = keep for ever)
    An uploaded dataset is kept this many days after it was uploaded, or after
    the owner last renewed it. The date is stored on ``files.expires_at``.
    Changing the setting later affects datasets uploaded or renewed afterwards,
    and the one-time backfill of datasets that had no date (migration
    ``018_dataset_retention``), which is counted from the day of that upgrade.
    ``0`` stops dataset removal, including datasets already past their date.
DATASET_EXPIRATION_WARNING_HOURS (default 24)
    How long before ``files.expires_at`` the dataset is treated as approaching
    expiration: the dashboard warning and the renewal action. The warning
    duration is this setting, not a fixed 24 hours. A value that is not a
    positive number falls back to 24. When the warning window is at least as
    long as the retention period, the effective window is shortened to the
    retention period minus one hour (or half the period, when that period is
    under an hour) so a dataset is not already "expiring" the moment it is
    uploaded. With retention off, the warning is off too.

What expires with a dataset
    the stored source file. The metadata row stays (soft-deleted) so historical
    runs keep the dataset name, size and checksum. Run results are not removed
    by dataset retention.
What stays until its own date
    run results, which follow RESULT_RETENTION_DAYS and are not removed by
    dataset retention.

Uploads
    MAX_UPLOAD_MB (default 500): largest single file accepted.
    UPLOAD_SESSION_GRACE_HOURS (default 24): an upload that was started and
    never finished is cleaned up after this long.
RETENTION_SWEEP_SECONDS (default 3600): how often the worker looks for expired
    results and expired datasets, and the API for abandoned uploads.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("phylo.api.retention")

DEFAULT_RESULT_RETENTION_DAYS = 60
DEFAULT_DATASET_RETENTION_DAYS = 60
DEFAULT_DATASET_WARNING_HOURS = 24
DEFAULT_MAX_UPLOAD_MB = 500
DEFAULT_UPLOAD_SESSION_GRACE_HOURS = 24
DEFAULT_SWEEP_SECONDS = 3600

# One log line per (retention days, configured warning hours) seen in this process.
_logged_warning_clamps: set[tuple[float, float]] = set()

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


def dataset_retention_days() -> float:
    """Days an uploaded dataset is kept; 0 means datasets are never removed."""
    return _number("DATASET_RETENTION_DAYS", DEFAULT_DATASET_RETENTION_DAYS, minimum=0)


def dataset_retention_period() -> Optional[timedelta]:
    days = dataset_retention_days()
    return timedelta(days=days) if days > 0 else None


def dataset_warning_hours() -> float:
    """Configured warning window in hours. Invalid or non-positive values use the default."""
    return _number("DATASET_EXPIRATION_WARNING_HOURS", DEFAULT_DATASET_WARNING_HOURS, minimum=0.01)


def effective_dataset_warning() -> Optional[timedelta]:
    """Warning window actually used for eligibility.

    ``None`` when dataset retention is off. When the configured window is at
    least as long as the retention period, the window is shortened so a dataset
    is not inside it from the moment it is uploaded.
    """
    period = dataset_retention_period()
    if period is None:
        return None
    hours = dataset_warning_hours()
    window = timedelta(hours=hours)
    if window < period:
        return window
    clamped = period - timedelta(hours=1)
    if clamped <= timedelta(0):
        clamped = period / 2
    key = (dataset_retention_days(), hours)
    if key not in _logged_warning_clamps:
        _logged_warning_clamps.add(key)
        logger.warning(
            "DATASET_EXPIRATION_WARNING_HOURS (%g h) is at least DATASET_RETENTION_DAYS (%g d); "
            "using a warning window of %s so a new upload is not already approaching expiration",
            hours,
            dataset_retention_days(),
            clamped,
        )
    return clamped


def dataset_expires_at(when: datetime) -> Optional[datetime]:
    """Expiration timestamp for a dataset uploaded or renewed at ``when``.

    ``None`` when retention is off (the dataset is kept until the owner deletes it).
    """
    period = dataset_retention_period()
    if period is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when + period


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def renewal_eligible(expires_at: Optional[datetime], now: datetime) -> bool:
    """True while the dataset is still kept and inside the effective warning window.

    The window comes from configuration (``effective_dataset_warning``), not from
    a fixed number of hours in the caller.
    """
    window = effective_dataset_warning()
    if window is None or expires_at is None:
        return False
    remaining = _aware(expires_at) - _aware(now)
    return timedelta(0) < remaining <= window


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
