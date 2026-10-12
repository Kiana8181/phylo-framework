"""Time limits the worker enforces on runs. All configurable through the
environment; every limit is read when it is used, so tests and a restarted
worker see the current values.

  RUN_TIMEOUT_SECONDS              longest a run may execute, measured from its
                                   persisted start time (default 86400 = 24 h;
                                   0 disables the limit)
  RUN_TIMEOUT_SECONDS_<METHOD>     the same for one method, e.g.
                                   RUN_TIMEOUT_SECONDS_DOWSER
  RUN_QUEUE_WAIT_TIMEOUT_SECONDS   longest a run that is ready to start may
                                   wait for a free slot or for an unreachable
                                   method service (default 172800 = 48 h;
                                   0 disables the limit)
  WORKER_METHOD_UNREACHABLE_SECONDS  how long a method service may stay
                                   unreachable while one of its jobs is being
                                   followed before the run fails (default 300)
  WORKER_CANCEL_CONFIRM_SECONDS    how long to wait for a method service to
                                   confirm that a job it was told to stop has
                                   stopped (default 60)
  WORKER_METHOD_DEADLINE_GRACE_SECONDS  extra time a method service's own
                                   deadline gets on top of the run's limit
                                   (default 120), so that the worker is
                                   normally the one that reports a timeout and
                                   the service only acts when the worker cannot
"""
from __future__ import annotations

import os
import re
from typing import Optional

DEFAULT_RUN_TIMEOUT_SECONDS = 24 * 3600
DEFAULT_QUEUE_WAIT_TIMEOUT_SECONDS = 48 * 3600
DEFAULT_METHOD_UNREACHABLE_SECONDS = 300
DEFAULT_CANCEL_CONFIRM_SECONDS = 60
METHOD_DEADLINE_GRACE_SECONDS = 120


def _seconds(name: str) -> Optional[float]:
    """Value of an environment variable in seconds, or None when unset/invalid."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _method_key(method_id: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (method_id or "").upper()).strip("_")


def run_timeout_seconds(method_id: str) -> Optional[float]:
    """Longest a run of this method may execute; None when there is no limit."""
    value = _seconds(f"RUN_TIMEOUT_SECONDS_{_method_key(method_id)}")
    if value is None:
        value = _seconds("RUN_TIMEOUT_SECONDS")
    if value is None:
        value = float(DEFAULT_RUN_TIMEOUT_SECONDS)
    return value if value > 0 else None


def queue_wait_timeout_seconds() -> Optional[float]:
    value = _seconds("RUN_QUEUE_WAIT_TIMEOUT_SECONDS")
    if value is None:
        value = float(DEFAULT_QUEUE_WAIT_TIMEOUT_SECONDS)
    return value if value > 0 else None


def method_unreachable_seconds() -> float:
    value = _seconds("WORKER_METHOD_UNREACHABLE_SECONDS")
    return float(DEFAULT_METHOD_UNREACHABLE_SECONDS) if value is None or value < 0 else value


def cancel_confirm_seconds() -> float:
    value = _seconds("WORKER_CANCEL_CONFIRM_SECONDS")
    return float(DEFAULT_CANCEL_CONFIRM_SECONDS) if value is None or value < 0 else value


def method_deadline_grace_seconds() -> float:
    value = _seconds("WORKER_METHOD_DEADLINE_GRACE_SECONDS")
    return float(METHOD_DEADLINE_GRACE_SECONDS) if value is None or value < 0 else value


def describe_duration(seconds: float) -> str:
    """A duration for a message shown to users: '24 hours', '90 minutes', '45 seconds'."""
    seconds = max(0, int(round(seconds)))
    if seconds >= 7200:
        hours = seconds / 3600
        return f"{int(hours)} hours" if seconds % 3600 == 0 else f"{hours:.1f} hours"
    if seconds >= 120:
        return f"{round(seconds / 60)} minutes"
    return f"{seconds} second" + ("" if seconds == 1 else "s")
