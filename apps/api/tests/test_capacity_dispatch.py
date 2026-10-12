"""Capacity-aware dispatch: a run only starts when its method service has room.

The tracker tests are pure. The queue and worker tests use the real PostgreSQL
harness (conftest.py): the scheduling guarantees live in SQL, so they are
checked against the real thing.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.api.database.models import RunStatus, User
from apps.api.repositories.run_repository import RunRepository
from apps.api.services import method_jobs_client as jobs
from apps.api.services.method_jobs_client import MethodBusy, MethodCapacity, MethodCapacityError
from apps.api.workers import run_worker as worker
from apps.api.workers.capacity import CapacityTracker


def capacity(method: str, slots: int, running: int = 0, *, accepting: bool | None = None,
             reason: str = "", threads: int = 1) -> MethodCapacity:
    free = max(0, slots - running)
    return MethodCapacity(
        method_id=method, job_slots=slots, running_jobs=running, free_slots=free,
        threads_per_job=threads, accepting=(free > 0) if accepting is None else accepting,
        code="ACCEPT" if free > 0 else "METHOD_BUSY", reason=reason,
    )


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def tracker_for(table: dict, clock: Clock | None = None, ttl: float = 5.0) -> CapacityTracker:
    async def fetch(method_id: str):
        value = table[method_id]
        if isinstance(value, Exception):
            raise value
        return value

    return CapacityTracker(fetch, ttl_seconds=ttl, clock=clock or Clock())


# --------------------------------------------------------------------------- #
# Tracker
# --------------------------------------------------------------------------- #
async def test_only_methods_with_a_free_slot_are_eligible():
    tracker = tracker_for({
        "dowser": capacity("dowser", 1, running=1),
        "gctree": capacity("gctree", 2, running=1),
        "clonaltree": capacity("clonaltree", 1),
    })
    await tracker.refresh(["dowser", "gctree", "clonaltree"])
    assert tracker.eligible(["dowser", "gctree", "clonaltree"]) == {"gctree", "clonaltree"}
    assert tracker.free_slots("dowser") == 0 and tracker.free_slots("gctree") == 1
    assert "Waiting for a free dowser slot" in tracker.blocked_reason("dowser")
    assert tracker.total_slots() == 4


async def test_reservations_count_before_the_service_knows_about_the_job():
    tracker = tracker_for({"gctree": capacity("gctree", 2)})
    await tracker.refresh(["gctree"])
    first, second = uuid.uuid4(), uuid.uuid4()
    tracker.reserve("gctree", first)
    assert tracker.free_slots("gctree") == 1 and tracker.blocked_reason("gctree") is None
    tracker.reserve("gctree", second)
    assert tracker.free_slots("gctree") == 0 and tracker.blocked_reason("gctree") is not None
    # Submitted: the reservation becomes a running job, still occupying the slot.
    tracker.submitted("gctree", first)
    assert tracker.free_slots("gctree") == 0
    # A reservation that never got submitted gives the slot back.
    tracker.release("gctree", second)
    assert tracker.free_slots("gctree") == 1


async def test_a_service_short_of_memory_is_not_offered_work_despite_free_slots():
    tracker = tracker_for({
        "dowser": capacity("dowser", 2, running=1, accepting=False, reason="Not enough free memory for another dowser job"),
    })
    await tracker.refresh(["dowser"])
    assert tracker.free_slots("dowser") == 1
    assert tracker.eligible(["dowser"]) == set()
    assert "Not enough free memory" in tracker.blocked_reason("dowser")


async def test_unreachable_service_gets_no_new_work_but_legacy_and_unconfigured_do():
    tracker = tracker_for({
        "dowser": httpx.ConnectError("refused"),
        "gctree": None,                                        # no /capacity endpoint
        "brepphylo": jobs.MethodServiceUnavailable("no url"),  # fails later with a clear error
    })
    await tracker.refresh(["dowser", "gctree", "brepphylo"])
    assert tracker.eligible(["dowser", "gctree", "brepphylo"]) == {"gctree", "brepphylo"}
    assert "not reachable" in tracker.blocked_reason("dowser")
    assert tracker.free_slots("gctree") is None


async def test_zero_slot_configuration_error_is_surfaced_not_waited_on():
    """A service that can never run a job must fail the run with its explanation."""
    tracker = tracker_for({"dowser": capacity("dowser", 0, accepting=False, reason="memory limit too small")})
    await tracker.refresh(["dowser"])
    assert tracker.eligible(["dowser"]) == {"dowser"}


async def test_capacity_is_cached_then_refreshed_and_busy_backs_off():
    clock = Clock()
    table = {"gctree": capacity("gctree", 1, running=1)}
    tracker = tracker_for(table, clock)
    await tracker.refresh(["gctree"])
    table["gctree"] = capacity("gctree", 1, running=0)
    clock.now += 2
    await tracker.refresh(["gctree"])
    assert tracker.eligible(["gctree"]) == set()           # still the cached answer
    clock.now += 4
    await tracker.refresh(["gctree"])
    assert tracker.eligible(["gctree"]) == {"gctree"}      # refreshed after the TTL

    tracker.mark_busy("gctree", "All 1 gctree job slot(s) are in use.", 10)
    assert tracker.blocked_reason("gctree") == "All 1 gctree job slot(s) are in use."
    clock.now += 11
    await tracker.refresh(["gctree"])                       # mark_busy invalidated the cache
    assert tracker.eligible(["gctree"]) == {"gctree"}


def test_worker_concurrency_is_derived_from_the_services_unless_configured(monkeypatch):
    tracker = tracker_for({})
    monkeypatch.delenv("WORKER_MAX_CONCURRENT_RUNS", raising=False)
    assert worker.max_concurrent_runs(tracker) == 1          # nothing reported yet
    tracker._states["a"] = type("S", (), {"kind": "known", "capacity": capacity("a", 2)})()
    tracker._states["b"] = type("S", (), {"kind": "known", "capacity": capacity("b", 3)})()
    assert worker.max_concurrent_runs(tracker) == 5
    monkeypatch.setenv("WORKER_MAX_CONCURRENT_RUNS", "2")
    assert worker.max_concurrent_runs(tracker) == 2
    for junk in ("", "0", "-1", "four"):
        monkeypatch.setenv("WORKER_MAX_CONCURRENT_RUNS", junk)
        assert worker.max_concurrent_runs(tracker) == 5


# --------------------------------------------------------------------------- #
# Method client
# --------------------------------------------------------------------------- #
@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []

    def handle(request):
        requests.append(request)
        status, body, headers = responses.pop(0)
        return httpx.Response(status, json=body, headers=headers)

    original = httpx.AsyncClient
    monkeypatch.setattr(jobs.httpx, "AsyncClient",
                        lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    return requests, responses


async def test_busy_and_insufficient_answers_are_distinct_exceptions(transport):
    _, responses = transport
    responses.append((429, {"ok": False, "code": "METHOD_BUSY", "error": "All 1 dowser job slot(s) are in use.",
                            "retry_after_seconds": 7}, {"Retry-After": "7"}))
    with pytest.raises(MethodBusy) as busy:
        await jobs.submit_job("dowser", file_path="/in.tsv", params={})
    assert busy.value.reason == "All 1 dowser job slot(s) are in use." and busy.value.retry_after_seconds == 7

    responses.append((429, {}, {"Retry-After": "3"}))            # header only
    with pytest.raises(MethodBusy) as busy:
        await jobs.submit_job("dowser", file_path=None, params={})
    assert busy.value.retry_after_seconds == 3 and "no free capacity" in busy.value.reason

    responses.append((507, {"ok": False, "code": "INSUFFICIENT_CAPACITY", "error": "memory limit too small"}, {}))
    with pytest.raises(MethodCapacityError, match="memory limit too small"):
        await jobs.submit_job("dowser", file_path=None, params={})


async def test_capacity_endpoint_is_parsed_and_absent_endpoint_is_legacy(transport):
    requests, responses = transport
    responses.append((200, {"ok": True, "job_slots": 2, "running_jobs": 1, "free_slots": 1, "threads_per_job": 2,
                            "accepting": True, "code": "ACCEPT", "cpus": 4.0, "memory_limit_mb": 8192}, {}))
    cap = await jobs.get_capacity("gctree")
    assert (cap.job_slots, cap.running_jobs, cap.free_slots, cap.threads_per_job, cap.accepting) == (2, 1, 1, 2, True)
    assert (cap.cpus, cap.memory_limit_mb) == (4.0, 8192)
    assert str(requests[0].url).endswith("/capacity")

    responses.append((404, {"error": "not found"}, {}))
    assert await jobs.get_capacity("gctree") is None
    responses.append((200, {"unexpected": True}, {}))
    assert await jobs.get_capacity("gctree") is None
    responses.append((500, {}, {}))
    with pytest.raises(httpx.HTTPStatusError):                  # unreachable is never "free"
        await jobs.get_capacity("gctree")


# --------------------------------------------------------------------------- #
# Queue (real PostgreSQL)
# --------------------------------------------------------------------------- #
async def make_user(session, tag: str) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(id=uuid.uuid4(), email=f"{tag}-{suffix}@test.io", username=f"{tag}-{suffix}", password_hash="x")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def enqueue(session, method: str, tag: str):
    """One user, one dispatch-ready run (as the router does)."""
    user = await make_user(session, tag)
    repo = RunRepository(session)
    run = await repo.create_run(method_id=method, params={}, user_id=user.id)
    await repo.promote_next_for_user(user.id)
    return run.id


async def fresh(session, run_id):
    session.expire_all()
    return await RunRepository(session).get_by_id(run_id)


@pytest.mark.integration
async def test_a_full_method_does_not_block_runs_for_other_methods(session):
    """No head-of-line blocking: the oldest run waits, a newer one for a free method starts."""
    dowser_run = await enqueue(session, "dowser", "a")
    gctree_run = await enqueue(session, "gctree", "b")
    repo = RunRepository(session)

    claimed = await repo.claim_next_run("w", 60, eligible_methods={"gctree"})
    assert claimed.id == gctree_run
    assert await repo.claim_next_run("w", 60, eligible_methods={"gctree"}) is None
    assert (await fresh(session, dowser_run)).status == RunStatus.QUEUED

    # Capacity frees up: the waiting run is next, in its original order.
    assert (await repo.claim_next_run("w", 60, eligible_methods={"dowser", "gctree"})).id == dowser_run


@pytest.mark.integration
async def test_no_eligible_method_means_nothing_is_claimed_and_none_means_no_restriction(session):
    run_id = await enqueue(session, "dowser", "a")
    repo = RunRepository(session)
    assert await repo.claim_next_run("w", 60, eligible_methods=set()) is None
    assert (await repo.claim_next_run("w", 60, eligible_methods=None)).id == run_id


@pytest.mark.integration
async def test_waiting_runs_say_why_and_keep_their_place(session):
    first = await enqueue(session, "dowser", "a")
    second = await enqueue(session, "dowser", "b")
    other = await enqueue(session, "gctree", "c")
    repo = RunRepository(session)
    assert sorted(await repo.dispatch_ready_methods()) == ["dowser", "gctree"]

    reason = "Waiting for a free dowser slot (1 of 1 in use)."
    assert await repo.mark_waiting_for_capacity({"dowser": reason}) == 2
    assert await repo.mark_waiting_for_capacity({"dowser": reason}) == 0   # idempotent
    for run_id in (first, second):
        run = await fresh(session, run_id)
        assert (run.status, run.stage, run.stage_message, run.message) == (
            RunStatus.QUEUED, "WAITING_FOR_CAPACITY", reason, reason)
    assert (await fresh(session, other)).stage == "QUEUED"

    # FIFO among the waiting runs is unchanged once a slot is free.
    assert (await repo.claim_next_run("w", 60, eligible_methods={"dowser"})).id == first
    assert (await repo.claim_next_run("w", 60, eligible_methods={"dowser"})).id == second


@pytest.mark.integration
async def test_released_run_returns_to_the_queue_unstarted_at_its_old_position(session):
    first = await enqueue(session, "dowser", "a")
    second = await enqueue(session, "dowser", "b")
    repo = RunRepository(session)
    claimed = await repo.claim_next_run("w1", 60)
    assert claimed.id == first and claimed.started_at is not None
    seq = claimed.dispatch_seq

    assert await repo.release_for_capacity(first, "w1", "All 1 dowser job slot(s) are in use.") is True
    run = await fresh(session, first)
    assert (run.status, run.worker_id, run.worker_lease_until, run.started_at) == (RunStatus.QUEUED, None, None, None)
    assert (run.stage, run.dispatch_seq, run.progress) == ("WAITING_FOR_CAPACITY", seq, 0)
    # Only the owning worker may release, and only before a job was submitted.
    assert await repo.release_for_capacity(first, "w1", "again") is False
    third = await repo.claim_next_run("w2", 60)
    assert third.id == first, "the released run is still ahead of the later one"
    await repo.set_method_job_id(first, "job-1")
    assert await repo.release_for_capacity(first, "w2", "too late") is False
    assert (await fresh(session, second)).status == RunStatus.QUEUED


@pytest.mark.integration
async def test_orphaned_run_with_a_submitted_job_is_resumed_even_when_the_method_is_full(session):
    """It already occupies its slot; refusing to resume it would strand it."""
    from datetime import timedelta
    from sqlalchemy import update
    from apps.api.database.models import Run
    from apps.api.utils.datetime_util import utc_now

    submitted = await enqueue(session, "dowser", "a")
    unsubmitted = await enqueue(session, "dowser", "b")
    repo = RunRepository(session)
    for run_id in (submitted, unsubmitted):
        assert (await repo.claim_next_run("dead", 60)).id == run_id
    await repo.set_method_job_id(submitted, "job-1")
    await session.execute(update(Run).values(worker_lease_until=utc_now() - timedelta(seconds=5)))
    await session.commit()

    resumed = await repo.claim_next_run("new", 60, eligible_methods=set())
    assert resumed.id == submitted
    assert await repo.claim_next_run("new", 60, eligible_methods=set()) is None
    assert (await repo.claim_next_run("new", 60, eligible_methods={"dowser"})).id == unsubmitted


# --------------------------------------------------------------------------- #
# Worker (real PostgreSQL, method service controlled)
# --------------------------------------------------------------------------- #
@pytest.fixture
def worker_db(session, monkeypatch):
    monkeypatch.setattr(worker, "AsyncSessionLocal", async_sessionmaker(session.bind, expire_on_commit=False))
    monkeypatch.setattr(worker, "METHOD_POLL_INTERVAL", 0)
    monkeypatch.delenv("WORKER_MAX_CONCURRENT_RUNS", raising=False)
    return session


@pytest.mark.integration
async def test_dispatch_starts_only_what_fits_and_explains_the_rest(worker_db):
    session = worker_db
    d1 = await enqueue(session, "dowser", "a")
    d2 = await enqueue(session, "dowser", "b")
    g1 = await enqueue(session, "gctree", "c")
    c1 = await enqueue(session, "clonaltree", "d")
    tracker = tracker_for({
        "dowser": capacity("dowser", 1),
        "gctree": capacity("gctree", 1, running=1),          # full
        "clonaltree": capacity("clonaltree", 2),
    })

    claimed = await worker.dispatch_once("w", set(), tracker)
    assert set(claimed) == {d1, c1}, "one dowser slot, one free clonaltree run; gctree is full"

    assert (await fresh(session, d2)).status == RunStatus.QUEUED
    waiting_gctree = await fresh(session, g1)
    assert waiting_gctree.status == RunStatus.QUEUED
    assert waiting_gctree.stage == "WAITING_FOR_CAPACITY"
    assert "Waiting for a free gctree slot" in waiting_gctree.stage_message
    # The second dowser run found the slot taken by the first within the same cycle.
    assert tracker.free_slots("dowser") == 0

    # Nothing else can start until capacity changes.
    assert await worker.dispatch_once("w", set(claimed), tracker) == []
    assert (await fresh(session, d2)).stage == "WAITING_FOR_CAPACITY"


@pytest.mark.integration
async def test_configured_worker_limit_still_applies(worker_db, monkeypatch):
    session = worker_db
    runs = [await enqueue(session, "clonaltree", f"u{i}") for i in range(4)]
    tracker = tracker_for({"clonaltree": capacity("clonaltree", 4)})
    monkeypatch.setenv("WORKER_MAX_CONCURRENT_RUNS", "2")
    assert await worker.dispatch_once("w", set(), tracker) == runs[:2]


@pytest.mark.integration
async def test_busy_answer_at_submit_requeues_the_run_instead_of_failing_it(worker_db, monkeypatch):
    """The capacity snapshot was stale (or memory ran short): not an error."""
    session = worker_db
    run_id = await enqueue(session, "gctree", "a")
    tracker = tracker_for({"gctree": capacity("gctree", 1)})
    assert await worker.dispatch_once("w", set(), tracker) == [run_id]
    monkeypatch.setattr(worker.jobs, "submit_job", AsyncMock(
        side_effect=MethodBusy("Not enough free memory for another gctree job", 15)))

    await worker.process_run(run_id, "w", tracker)

    run = await fresh(session, run_id)
    assert run.status == RunStatus.QUEUED and run.error is None and run.finished_at is None
    assert run.stage == "WAITING_FOR_CAPACITY" and "Not enough free memory" in run.stage_message
    assert run.method_job_id is None and run.started_at is None and run.worker_id is None
    # The slot reservation is gone and the method is paused, so no hot retry loop.
    assert tracker.blocked_reason("gctree") == "Not enough free memory for another gctree job"
    assert await worker.dispatch_once("w", set(), tracker) == []


@pytest.mark.integration
async def test_run_starts_after_capacity_returns(worker_db, monkeypatch):
    session = worker_db
    run_id = await enqueue(session, "gctree", "a")
    clock = Clock()
    table = {"gctree": capacity("gctree", 1, running=1)}
    tracker = tracker_for(table, clock)
    assert await worker.dispatch_once("w", set(), tracker) == []
    assert (await fresh(session, run_id)).stage == "WAITING_FOR_CAPACITY"

    table["gctree"] = capacity("gctree", 1, running=0)        # the other job finished
    clock.now += 6
    assert await worker.dispatch_once("w", set(), tracker) == [run_id]
    assert (await fresh(session, run_id)).status == RunStatus.RUNNING


@pytest.mark.integration
async def test_job_that_can_never_fit_fails_with_the_services_explanation(worker_db, monkeypatch):
    session = worker_db
    run_id = await enqueue(session, "dowser", "a")
    tracker = tracker_for({"dowser": capacity("dowser", 0, accepting=False)})
    assert await worker.dispatch_once("w", set(), tracker) == [run_id]
    monkeypatch.setattr(worker.jobs, "submit_job", AsyncMock(side_effect=MethodCapacityError(
        "The dowser service has a memory limit of 1024 MiB, which cannot hold the service (850 MiB) plus one job")))

    await worker.process_run(run_id, "w", tracker)

    run = await fresh(session, run_id)
    assert run.status == RunStatus.ERROR
    assert "current resource limits" in run.message and "1024 MiB" in run.message
