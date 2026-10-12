"""Capacity-aware dispatch: which methods the worker may start a run for.

Each method service reports how many jobs it can run (``GET /capacity``), based
on its own CPU and memory limits. The worker only claims runs for methods with
a free slot, so a run that cannot start stays QUEUED instead of being handed to
a service that would have to oversubscribe its container.

The tracker keeps three small pieces of state:

* a short-lived cache of each method's reported capacity;
* reservations: runs this worker has claimed but not yet submitted, which the
  method service cannot know about yet;
* a back-off per method after a service answered "busy", so the worker does
  not offer the same run again in a tight loop.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, Optional
from uuid import UUID

from apps.api.services.method_jobs_client import (
    MethodCapacity,
    MethodServiceUnavailable,
)

CapacityFetcher = Callable[[str], Awaitable[Optional[MethodCapacity]]]


@dataclass
class MethodState:
    """Latest knowledge about one method service."""

    capacity: Optional[MethodCapacity] = None
    # "known": capacity reported. "legacy": no /capacity endpoint or no URL
    # configured (offer runs; the service or the submit path decides).
    # "unreachable": the service did not answer; do not send it new work.
    kind: str = "legacy"
    detail: str = ""
    fetched_at: float = 0.0


class CapacityTracker:
    def __init__(
        self,
        fetch: CapacityFetcher,
        *,
        ttl_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._fetch = fetch
        self._ttl = ttl_seconds
        self._clock = clock
        self._states: dict[str, MethodState] = {}
        self._reserved: dict[str, set[UUID]] = {}
        self._busy_until: dict[str, float] = {}
        self._busy_reason: dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # Refresh
    # ------------------------------------------------------------------ #
    async def refresh(self, method_ids: Iterable[str]) -> None:
        now = self._clock()
        for method_id in set(method_ids):
            state = self._states.get(method_id)
            if state is not None and now - state.fetched_at < self._ttl:
                continue
            self._states[method_id] = await self._load(method_id, now)

    async def _load(self, method_id: str, now: float) -> MethodState:
        try:
            capacity = await self._fetch(method_id)
        except MethodServiceUnavailable as exc:
            # No URL configured: let the run be claimed so it fails with the
            # existing, explicit configuration error.
            return MethodState(kind="legacy", detail=str(exc), fetched_at=now)
        except Exception as exc:  # noqa: BLE001 - any transport/HTTP failure
            return MethodState(kind="unreachable", detail=f"{type(exc).__name__}: {exc}", fetched_at=now)
        if capacity is None:
            return MethodState(kind="legacy", fetched_at=now)
        return MethodState(capacity=capacity, kind="known", fetched_at=now)

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def state(self, method_id: str) -> MethodState:
        return self._states.get(method_id, MethodState())

    def free_slots(self, method_id: str) -> Optional[int]:
        """Slots this worker may still fill, or None when the service does not
        report capacity (then it is not limited here)."""
        state = self.state(method_id)
        if state.kind != "known" or state.capacity is None:
            return None
        cap = state.capacity
        return max(0, cap.job_slots - cap.running_jobs - len(self._reserved.get(method_id, ())))

    def blocked_reason(self, method_id: str) -> Optional[str]:
        """Why no new run may start for this method right now, or None if one may."""
        now = self._clock()
        if self._busy_until.get(method_id, 0.0) > now:
            return self._busy_reason.get(method_id) or f"The {method_id} service is busy."
        state = self.state(method_id)
        if state.kind == "unreachable":
            return f"The {method_id} service is not reachable right now."
        if state.kind != "known" or state.capacity is None:
            return None
        cap = state.capacity
        if cap.job_slots < 1:
            # A configuration problem, not a wait: let the run be claimed so the
            # service's own explanation becomes the run's error.
            return None
        free = self.free_slots(method_id)
        if free is not None and free < 1:
            return (
                f"Waiting for a free {method_id} slot "
                f"({cap.job_slots} of {cap.job_slots} in use)."
            )
        if not cap.accepting:
            return cap.reason or f"The {method_id} service has no free capacity right now."
        return None

    def eligible(self, method_ids: Iterable[str]) -> set[str]:
        return {m for m in set(method_ids) if self.blocked_reason(m) is None}

    def total_slots(self) -> int:
        """Job slots across every method that reports capacity."""
        return sum(
            s.capacity.job_slots
            for s in self._states.values()
            if s.kind == "known" and s.capacity is not None
        )

    # ------------------------------------------------------------------ #
    # Updates from the dispatch loop
    # ------------------------------------------------------------------ #
    def reserve(self, method_id: str, run_id: UUID) -> None:
        self._reserved.setdefault(method_id, set()).add(run_id)

    def submitted(self, method_id: str, run_id: UUID) -> None:
        """The job is now running in the service: move it from "reserved" to the
        cached running count until the next refresh confirms it."""
        self._reserved.get(method_id, set()).discard(run_id)
        state = self._states.get(method_id)
        if state is not None and state.capacity is not None:
            state.capacity.running_jobs += 1
            state.capacity.free_slots = max(0, state.capacity.free_slots - 1)

    def release(self, method_id: str, run_id: UUID) -> None:
        self._reserved.get(method_id, set()).discard(run_id)

    def mark_busy(self, method_id: str, reason: str, retry_after_seconds: float) -> None:
        self._busy_until[method_id] = self._clock() + max(1.0, float(retry_after_seconds))
        self._busy_reason[method_id] = reason
        # The cached numbers were wrong enough to be refused: fetch them again.
        if method_id in self._states:
            self._states[method_id].fetched_at = 0.0
