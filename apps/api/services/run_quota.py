"""Per-user limits on creating runs.

Three limits, all per user, all configurable through the environment (read when
used, so a restart is enough to change them):

  MAX_RUNS_PER_USER_PER_HOUR            runs a user may have in any rolling
                                        60-minute window (default 5; 0 = no limit)
  MAX_QUEUED_RUNS_PER_USER              runs that may wait behind the user's
                                        active run (default 5)
  MAX_RUN_SUBMISSIONS_PER_USER_PER_HOUR every run a user creates in the window,
                                        whatever became of it (default 30;
                                        0 = no limit)

What counts against the hourly quota: every run the user created in the last 60
minutes, EXCEPT runs that ended without their analysis ever starting — cancelled
before anything was submitted to the method service, or expired in the queue
(QUEUE_TIMEOUT). The persisted fact is ``started_at``: a worker sets it when it
takes the run, and it is cleared again when the run returns to the queue or is
cancelled before submission. A run that is still waiting counts: it is going to
execute. A run that failed while its input was being prepared counts too: work
was done for it.

Why a third limit. Runs that never started are free, by decision. Without a
ceiling, submit-and-cancel in a loop would be free as well and could be used to
flood the queue table and the API. The submission limit counts every created
run and cannot be earned back by cancelling.

The queue limit is independent of both: it counts runs that have not finished,
so neither cancelling nor a queue timeout can be used to hold more than
1 + MAX_QUEUED_RUNS_PER_USER unfinished runs.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from apps.api.repositories.run_repository import RunRepository
from apps.api.utils.datetime_util import utc_now

WINDOW_SECONDS = 3600
DEFAULT_RUNS_PER_HOUR = 5
DEFAULT_MAX_QUEUED = 5
DEFAULT_SUBMISSIONS_PER_HOUR = 30

CODE_QUOTA = "RUN_QUOTA_EXCEEDED"
CODE_SUBMISSIONS = "RUN_SUBMISSION_LIMIT_EXCEEDED"
CODE_QUEUE_FULL = "QUEUE_FULL"


def _int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default          # a typo must not remove the limit
    return value if value >= 0 else default


def max_runs_per_hour() -> int:
    return _int_env("MAX_RUNS_PER_USER_PER_HOUR", DEFAULT_RUNS_PER_HOUR)


def max_queued_runs() -> int:
    return _int_env("MAX_QUEUED_RUNS_PER_USER", DEFAULT_MAX_QUEUED)


def max_submissions_per_hour() -> int:
    """Never lower than the hourly quota, which it exists to protect."""
    limit = _int_env("MAX_RUN_SUBMISSIONS_PER_USER_PER_HOUR", DEFAULT_SUBMISSIONS_PER_HOUR)
    return 0 if limit == 0 else max(limit, max_runs_per_hour())


@dataclass(frozen=True)
class Window:
    """Use of one rolling-window limit."""

    limit: int                      # 0 = unlimited
    used: int
    reset_at: Optional[datetime]    # when the next unit becomes available again

    @property
    def unlimited(self) -> bool:
        return self.limit == 0

    @property
    def remaining(self) -> Optional[int]:
        return None if self.unlimited else max(0, self.limit - self.used)

    @property
    def exceeded(self) -> bool:
        return not self.unlimited and self.used >= self.limit

    def as_dict(self, now: datetime) -> dict[str, Any]:
        blocked_until = self.reset_at if self.exceeded else None
        return {
            "limit": None if self.unlimited else self.limit,
            "used": self.used,
            "remaining": self.remaining,
            "window_seconds": WINDOW_SECONDS,
            # Set only while the limit is reached: when one more run becomes possible.
            "reset_at": blocked_until.isoformat() if blocked_until else None,
            "retry_after_seconds": _seconds_until(blocked_until, now) if blocked_until else None,
        }


def _seconds_until(moment: datetime, now: datetime) -> int:
    return max(1, math.ceil((moment - now).total_seconds()))


def _window(limit: int, created: list[datetime]) -> Window:
    """``created``: creation times of the runs that count, oldest first."""
    used = len(created)
    reset_at = None
    if limit and used >= limit:
        # One unit frees when the oldest run that keeps us at the limit leaves the window.
        reset_at = created[used - limit] + timedelta(seconds=WINDOW_SECONDS)
    return Window(limit=limit, used=used, reset_at=reset_at)


@dataclass(frozen=True)
class QuotaState:
    hourly: Window
    submissions: Window
    max_queued: int
    unfinished: int                 # the user's runs that have not finished (active + queued)
    now: datetime

    @property
    def queue_full(self) -> bool:
        return self.unfinished >= self.max_queued + 1

    @property
    def blocked_by(self) -> Optional[str]:
        if self.submissions.exceeded:
            return CODE_SUBMISSIONS
        if self.hourly.exceeded:
            return CODE_QUOTA
        if self.queue_full:
            return CODE_QUEUE_FULL
        return None

    @property
    def retry_after_seconds(self) -> Optional[int]:
        """Seconds until submitting can work again; None when that depends on
        a run finishing (full queue) rather than on time."""
        waits = [
            _seconds_until(w.reset_at, self.now)
            for w in (self.submissions, self.hourly) if w.exceeded and w.reset_at
        ]
        return max(waits) if waits else None

    @property
    def message(self) -> Optional[str]:
        blocked = self.blocked_by
        if blocked == CODE_QUOTA:
            return (
                f"You have reached the limit of {self.hourly.limit} runs per hour. "
                "You can start another run when the oldest of them is an hour old."
            )
        if blocked == CODE_SUBMISSIONS:
            return (
                f"You have submitted {self.submissions.used} runs in the last hour, which is the "
                f"most allowed ({self.submissions.limit}), including cancelled ones. Please try again later."
            )
        if blocked == CODE_QUEUE_FULL:
            return (
                f"Your run queue is full ({self.max_queued} queued behind your active "
                "run). Wait for a run to finish or cancel a queued one."
            )
        return None

    def as_dict(self) -> dict[str, Any]:
        queued = max(0, self.unfinished - 1)
        return {
            "can_submit": self.blocked_by is None,
            "blocked_by": self.blocked_by,
            "message": self.message,
            "retry_after_seconds": self.retry_after_seconds,
            "hourly": self.hourly.as_dict(self.now),
            "submissions": self.submissions.as_dict(self.now),
            "queue": {
                "max_queued": self.max_queued,
                "queued_count": min(queued, self.max_queued),
                "unfinished": self.unfinished,
                "can_add": not self.queue_full,
            },
            "server_time": self.now.isoformat(),
        }


async def quota_state(run_repo: RunRepository, user_id: UUID, *, now: Optional[datetime] = None) -> QuotaState:
    """The user's position against all three limits, as of ``now``."""
    now = now or utc_now()
    since = now - timedelta(seconds=WINDOW_SECONDS)
    recent = await run_repo.recent_run_creations(user_id, since)
    counted = [created for created, never_started in recent if not never_started]
    everything = [created for created, _ in recent]
    return QuotaState(
        hourly=_window(max_runs_per_hour(), counted),
        submissions=_window(max_submissions_per_hour(), everything),
        max_queued=max_queued_runs(),
        unfinished=await run_repo.count_nonterminal_for_user(user_id),
        now=now,
    )
