"""Limits on creating runs: rolling hourly quota, queue size, submission ceiling.

Real routes and repositories against the test PostgreSQL. What each test
protects is one way the limits could be wrong: too strict (a run that never
started is charged), too loose (two concurrent requests both pass), or
bypassable (cancelling as a way to submit without end).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.api.auth.dependencies import get_current_user
from apps.api.database import get_db
from apps.api.database.models import Run, RunStatus, User
from apps.api.main import app
from apps.api.repositories.run_repository import RunRepository
from apps.api.routers import runs as runs_router
from apps.api.services import run_quota
from apps.api.workers import run_worker as worker

LIMIT_ENV = ("MAX_RUNS_PER_USER_PER_HOUR", "MAX_QUEUED_RUNS_PER_USER", "MAX_RUN_SUBMISSIONS_PER_USER_PER_HOUR")


# --------------------------------------------------------------------------- #
# Window arithmetic and settings (no database)
# --------------------------------------------------------------------------- #
def at(minutes_ago: float) -> datetime:
    return datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc) - timedelta(minutes=minutes_ago)


NOW = at(0)


def test_defaults_and_overrides(monkeypatch):
    for name in LIMIT_ENV:
        monkeypatch.delenv(name, raising=False)
    assert (run_quota.max_runs_per_hour(), run_quota.max_queued_runs(), run_quota.max_submissions_per_hour()) == (5, 5, 30)
    monkeypatch.setenv("MAX_RUNS_PER_USER_PER_HOUR", "12")
    monkeypatch.setenv("MAX_QUEUED_RUNS_PER_USER", "2")
    monkeypatch.setenv("MAX_RUN_SUBMISSIONS_PER_USER_PER_HOUR", "100")
    assert (run_quota.max_runs_per_hour(), run_quota.max_queued_runs(), run_quota.max_submissions_per_hour()) == (12, 2, 100)


@pytest.mark.parametrize("junk", ["", "many", "-3", "2.5"])
def test_a_typo_never_removes_a_limit(monkeypatch, junk):
    for name in LIMIT_ENV:
        monkeypatch.setenv(name, junk)
    assert (run_quota.max_runs_per_hour(), run_quota.max_queued_runs(), run_quota.max_submissions_per_hour()) == (5, 5, 30)


def test_zero_switches_a_rolling_limit_off_explicitly(monkeypatch):
    monkeypatch.setenv("MAX_RUNS_PER_USER_PER_HOUR", "0")
    monkeypatch.setenv("MAX_RUN_SUBMISSIONS_PER_USER_PER_HOUR", "0")
    assert run_quota.max_runs_per_hour() == 0 and run_quota.max_submissions_per_hour() == 0
    window = run_quota._window(0, [at(1)] * 50)
    assert window.unlimited and not window.exceeded and window.remaining is None
    assert window.as_dict(NOW)["limit"] is None


def test_the_submission_ceiling_cannot_be_set_below_the_quota_it_protects(monkeypatch):
    monkeypatch.setenv("MAX_RUNS_PER_USER_PER_HOUR", "8")
    monkeypatch.setenv("MAX_RUN_SUBMISSIONS_PER_USER_PER_HOUR", "3")
    assert run_quota.max_submissions_per_hour() == 8


def test_window_reports_when_the_next_run_becomes_possible():
    # 5 allowed, 5 used: the oldest leaves the window 60 minutes after it was created.
    full = run_quota._window(5, [at(50), at(40), at(30), at(20), at(10)])
    assert full.exceeded and full.remaining == 0
    assert full.reset_at == at(50) + timedelta(hours=1)
    body = full.as_dict(NOW)
    assert body["retry_after_seconds"] == 600 and body["reset_at"] == (at(50) + timedelta(hours=1)).isoformat()

    # Over the limit (the limit was lowered): one more run needs TWO to leave the window.
    over = run_quota._window(3, [at(50), at(40), at(30), at(20)])
    assert over.reset_at == at(40) + timedelta(hours=1)

    partial = run_quota._window(5, [at(50), at(10)])
    assert not partial.exceeded and partial.remaining == 3 and partial.reset_at is None
    assert partial.as_dict(NOW)["reset_at"] is None and partial.as_dict(NOW)["retry_after_seconds"] is None


def state(*, counted=0, submitted=None, unfinished=0, quota=5, ceiling=30, max_queued=5):
    created = [at(59 - i) for i in range(submitted if submitted is not None else counted)]
    return run_quota.QuotaState(
        hourly=run_quota._window(quota, created[:counted]),
        submissions=run_quota._window(ceiling, created),
        max_queued=max_queued, unfinished=unfinished, now=NOW,
    )


def test_what_blocks_a_submission_and_what_the_user_is_told():
    assert state(counted=4, unfinished=1).blocked_by is None
    quota = state(counted=5)
    assert quota.blocked_by == "RUN_QUOTA_EXCEEDED" and "5 runs per hour" in quota.message
    assert quota.retry_after_seconds == 60                     # the oldest was created 59 minutes ago
    queue = state(counted=2, unfinished=6, quota=50)
    assert queue.blocked_by == "QUEUE_FULL" and queue.retry_after_seconds is None   # depends on a run finishing
    ceiling = state(counted=0, submitted=30)
    assert ceiling.blocked_by == "RUN_SUBMISSION_LIMIT_EXCEEDED" and "including cancelled ones" in ceiling.message
    body = state(counted=5, unfinished=3).as_dict()
    assert body["can_submit"] is False and body["blocked_by"] == "RUN_QUOTA_EXCEEDED"
    assert body["hourly"] == {"limit": 5, "used": 5, "remaining": 0, "window_seconds": 3600,
                              "reset_at": (at(59) + timedelta(hours=1)).isoformat(), "retry_after_seconds": 60}
    assert body["queue"] == {"max_queued": 5, "queued_count": 2, "unfinished": 3, "can_add": True}


# --------------------------------------------------------------------------- #
# Routes (real PostgreSQL)
# --------------------------------------------------------------------------- #
pytestmark_db = pytest.mark.integration


async def make_user(session, tag="quota") -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(id=uuid.uuid4(), email=f"{tag}-{suffix}@test.io", username=f"{tag}-{suffix}", password_hash="x")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.fixture
async def test_user(session) -> User:
    return await make_user(session)


@pytest.fixture
async def client(session, test_user, monkeypatch):
    """Every request gets its own database session, as in production, so that
    concurrent requests really are concurrent transactions."""
    for name in LIMIT_ENV:
        monkeypatch.delenv(name, raising=False)
    # A file-less method so create_run needs no upload; a configured service URL so
    # the "no service URL" guard passes.
    monkeypatch.setattr(runs_router, "method_service_url", lambda method: "http://method.test")
    monkeypatch.setattr(runs_router, "get_ui_hints", lambda method: {"requiresFile": False})
    maker = async_sessionmaker(session.bind, expire_on_commit=False)
    identity = {"user": test_user}

    async def _db():
        async with maker() as request_session:
            yield request_session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.identity = identity
        yield ac
    app.dependency_overrides.clear()


def data(response):
    body = response.json()
    return body.get("data", body) if isinstance(body, dict) else body


async def create(client, method="dowser"):
    return await client.post("/runs", params={"method": method}, json={"params": {}})


async def create_ok(client, count=1):
    ids = []
    for i in range(count):
        response = await create(client)
        assert response.status_code == 200, f"create #{i + 1}: {response.status_code} {response.text}"
        ids.append(data(response)["run_id"])
    return ids


async def quota(client):
    response = await client.get("/runs/quota")
    assert response.status_code == 200, response.text
    return data(response)


async def run_rows(session, user):
    # populate_existing: re-read rows this session has already seen, without
    # expiring the user object the application is using as the signed-in user.
    stmt = select(Run).where(Run.user_id == user.id).order_by(Run.created_at).execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalars().all()


@pytestmark_db
async def test_the_sixth_run_within_an_hour_is_refused_with_the_time_to_retry(client, session, test_user):
    await create_ok(client, 5)
    refused = await create(client)
    assert refused.status_code == 429
    detail = data(refused)
    assert detail["code"] == "RUN_QUOTA_EXCEEDED" and detail["limit"] == 5 and detail["used"] == 5
    assert "5 runs per hour" in refused.json()["message"]
    oldest = (await run_rows(session, test_user))[0].created_at
    assert datetime.fromisoformat(detail["reset_at"]) == oldest + timedelta(hours=1)
    assert 3590 <= detail["retry_after_seconds"] <= 3600
    assert refused.headers["Retry-After"] == str(detail["retry_after_seconds"])
    assert len(await run_rows(session, test_user)) == 5                      # the refused request created nothing


@pytestmark_db
async def test_quota_endpoint_tells_the_client_beforehand(client):
    fresh = await quota(client)
    assert fresh["can_submit"] is True and fresh["blocked_by"] is None and fresh["message"] is None
    assert fresh["hourly"]["limit"] == 5 and fresh["hourly"]["used"] == 0 and fresh["hourly"]["remaining"] == 5
    assert fresh["queue"] == {"max_queued": 5, "queued_count": 0, "unfinished": 0, "can_add": True}

    await create_ok(client, 3)
    partly = await quota(client)
    assert partly["can_submit"] is True and partly["hourly"]["remaining"] == 2
    assert partly["queue"]["queued_count"] == 2 and partly["hourly"]["reset_at"] is None

    await create_ok(client, 2)
    blocked = await quota(client)
    assert blocked["can_submit"] is False and blocked["blocked_by"] == "RUN_QUOTA_EXCEEDED"
    assert blocked["hourly"]["remaining"] == 0 and 3590 <= blocked["retry_after_seconds"] <= 3600
    assert blocked["hourly"]["reset_at"] and "5 runs per hour" in blocked["message"]
    # The endpoint and POST /runs apply the same rule.
    assert (await create(client)).status_code == 429


@pytestmark_db
async def test_quota_endpoint_requires_a_signed_in_user(client):
    client.identity["user"] = None
    assert (await client.get("/runs/quota")).status_code == 401


@pytestmark_db
async def test_one_users_runs_do_not_use_another_users_quota(client, session):
    await create_ok(client, 5)
    assert (await create(client)).status_code == 429
    client.identity["user"] = await make_user(session, "other")
    assert (await quota(client))["hourly"]["used"] == 0
    await create_ok(client, 1)


@pytestmark_db
async def test_runs_older_than_an_hour_no_longer_count(client, session, test_user):
    ids = await create_ok(client, 5)
    assert (await create(client)).status_code == 429
    old = datetime.now(timezone.utc) - timedelta(minutes=61)
    await session.execute(update(Run).where(Run.id == uuid.UUID(ids[0])).values(created_at=old, status=RunStatus.DONE))
    await session.commit()
    assert (await quota(client))["hourly"]["used"] == 4
    await create_ok(client, 1)
    assert (await create(client)).status_code == 429


@pytestmark_db
async def test_finished_and_failed_runs_count(client, session, test_user):
    """The quota is about work done, whatever its outcome."""
    ids = await create_ok(client, 5)
    started = datetime.now(timezone.utc)
    for run_id, status in zip(ids, [RunStatus.DONE, RunStatus.ERROR, RunStatus.CANCELLED, RunStatus.DONE, RunStatus.ERROR]):
        await session.execute(update(Run).where(Run.id == uuid.UUID(run_id)).values(
            status=status, started_at=started, finished_at=started, dispatch_seq=None))
    await session.commit()
    state_now = await quota(client)
    assert state_now["hourly"]["used"] == 5 and state_now["queue"]["unfinished"] == 0
    assert (await create(client)).status_code == 429


@pytestmark_db
async def test_cancelling_a_queued_run_gives_its_allowance_back(client, session, test_user):
    ids = await create_ok(client, 5)
    assert (await create(client)).status_code == 429
    # A run waiting in the personal queue, and the promoted one that no worker has taken yet.
    assert (await client.post(f"/runs/{ids[4]}/cancel-queued")).status_code == 200
    assert (await client.post(f"/runs/{ids[0]}/cancel")).status_code == 200
    rows = {str(r.id): r for r in await run_rows(session, test_user)}
    assert rows[ids[4]].status == rows[ids[0]].status == RunStatus.CANCELLED
    assert rows[ids[4]].started_at is None and rows[ids[0]].started_at is None
    assert (await quota(client))["hourly"]["used"] == 3
    await create_ok(client, 2)
    assert (await create(client)).status_code == 429


@pytestmark_db
async def test_cancelling_a_run_that_started_does_not_give_its_allowance_back(client, session, test_user):
    ids = await create_ok(client, 5)
    repo = RunRepository(session)
    claimed = await repo.claim_next_run("w", 60)                              # a worker takes the active run
    assert str(claimed.id) == ids[0]
    await repo.set_method_job_id(claimed.id, "job-1")
    assert (await client.post(f"/runs/{ids[0]}/cancel")).status_code == 200  # user asks to stop it
    await repo.mark_cancelled(claimed.id, "Run cancelled")                    # worker confirms
    row = (await run_rows(session, test_user))[0]
    assert row.status == RunStatus.CANCELLED and row.started_at is not None
    assert (await quota(client))["hourly"]["used"] == 5
    assert (await create(client)).status_code == 429


@pytestmark_db
async def test_a_run_cancelled_after_pickup_but_before_submission_is_free(client, session, test_user, monkeypatch):
    """The worker had taken the run, but nothing reached the method service."""
    ids = await create_ok(client, 5)
    await RunRepository(session).claim_next_run("w", 60)
    assert (await client.post(f"/runs/{ids[0]}/cancel")).status_code == 200
    monkeypatch.setattr(worker, "AsyncSessionLocal", async_sessionmaker(session.bind, expire_on_commit=False))
    from unittest.mock import AsyncMock
    submit = AsyncMock()
    monkeypatch.setattr(worker.jobs, "submit_job", submit)
    await worker.process_run(uuid.UUID(ids[0]), "w")
    submit.assert_not_awaited()
    row = (await run_rows(session, test_user))[0]
    assert row.status == RunStatus.CANCELLED and row.started_at is None and row.method_job_id is None
    assert (await quota(client))["hourly"]["used"] == 4
    await create_ok(client, 1)


@pytestmark_db
async def test_a_run_that_expired_in_the_queue_is_free(client, session, test_user, monkeypatch):
    """QUEUE_TIMEOUT: the run never executed, so it is not charged."""
    ids = await create_ok(client, 5)
    assert (await create(client)).status_code == 429
    await session.execute(update(Run).where(Run.id == uuid.UUID(ids[0])).values(
        dispatch_ready_at=datetime.now(timezone.utc) - timedelta(hours=49)))
    await session.commit()
    monkeypatch.setattr(worker, "AsyncSessionLocal", async_sessionmaker(session.bind, expire_on_commit=False))
    monkeypatch.delenv("RUN_QUEUE_WAIT_TIMEOUT_SECONDS", raising=False)
    assert [str(i) for i in await worker.expire_waiting_runs()] == [ids[0]]
    row = (await run_rows(session, test_user))[0]
    assert row.status == RunStatus.ERROR and "QUEUE_TIMEOUT" in row.error and row.started_at is None
    now = await quota(client)
    assert now["hourly"]["used"] == 4 and now["submissions"]["used"] == 5    # still a submission
    await create_ok(client, 1)
    assert (await create(client)).status_code == 429


@pytestmark_db
async def test_a_run_that_failed_while_preparing_its_input_counts(client, session, test_user):
    """Unlike a queue timeout, work was done for it (started_at is set)."""
    ids = await create_ok(client, 5)
    repo = RunRepository(session)
    claimed = await repo.claim_next_run("w", 60)
    await repo.update(claimed.id, status=RunStatus.ERROR, stage="ERROR", finished_at=datetime.now(timezone.utc))
    assert (await quota(client))["hourly"]["used"] == 5
    assert ids and (await create(client)).status_code == 429


@pytestmark_db
async def test_the_queue_limit_is_configurable_and_independent_of_the_hourly_quota(client, monkeypatch):
    monkeypatch.setenv("MAX_RUNS_PER_USER_PER_HOUR", "50")
    monkeypatch.setenv("MAX_QUEUED_RUNS_PER_USER", "2")
    ids = await create_ok(client, 3)                                          # 1 active + 2 queued
    full = await create(client)
    assert full.status_code == 409
    assert data(full)["code"] == "QUEUE_FULL" and data(full)["limit"] == 2
    assert "Retry-After" not in full.headers                                 # no time will fix it; a run must finish
    state_now = await quota(client)
    assert state_now["blocked_by"] == "QUEUE_FULL" and state_now["queue"]["can_add"] is False
    assert state_now["retry_after_seconds"] is None and state_now["hourly"]["remaining"] == 47
    dashboard = data(await client.get("/runs/dashboard"))
    assert dashboard["limits"] == {"max_queued": 2, "queued_count": 2, "can_add": False}
    await client.post(f"/runs/{ids[2]}/cancel-queued")
    await create_ok(client, 1)


@pytestmark_db
async def test_cancelling_cannot_be_used_to_submit_without_end(client, session, test_user, monkeypatch):
    """Runs that never start are free for the quota, but not for the submission ceiling."""
    monkeypatch.setenv("MAX_RUN_SUBMISSIONS_PER_USER_PER_HOUR", "8")
    for _ in range(8):
        (run_id,) = await create_ok(client, 1)
        assert (await client.post(f"/runs/{run_id}/cancel")).status_code == 200
    state_now = await quota(client)
    assert state_now["hourly"]["used"] == 0 and state_now["submissions"]["used"] == 8
    assert state_now["can_submit"] is False and state_now["blocked_by"] == "RUN_SUBMISSION_LIMIT_EXCEEDED"
    refused = await create(client)
    assert refused.status_code == 429 and data(refused)["code"] == "RUN_SUBMISSION_LIMIT_EXCEEDED"
    assert data(refused)["limit"] == 8 and int(refused.headers["Retry-After"]) > 3500
    assert len(await run_rows(session, test_user)) == 8


@pytestmark_db
async def test_neither_cancelling_nor_a_queue_timeout_lets_a_user_hold_more_unfinished_runs(client, session, monkeypatch):
    monkeypatch.setenv("MAX_RUNS_PER_USER_PER_HOUR", "0")                     # hourly quota off: only the queue limit
    monkeypatch.setenv("MAX_QUEUED_RUNS_PER_USER", "1")
    ids = await create_ok(client, 2)
    for _ in range(3):                                                        # churn the queued one
        assert (await create(client)).status_code == 409
        await client.post(f"/runs/{ids[-1]}/cancel-queued")
        ids += await create_ok(client, 1)
    unfinished = [r for r in await run_rows(session, client.identity["user"])
                  if r.status in (RunStatus.QUEUED, RunStatus.RUNNING)]
    assert len(unfinished) == 2


@pytest.fixture
def slow_limit_check(monkeypatch):
    """Make a race between two requests certain if nothing prevents it, without
    depending on timing.

    The first request pauses right after its limit check and resumes only when
    one of two things has happened:
      - a second request has finished its own limit check too. Both now hold
        the same count and both will create a run: the race the lock prevents;
      - a second request has arrived at the per-user lock, where it has to wait
        for the first. That is the lock doing its job.

    Returns a function that switches this on; requests made before it is called
    (test set-up) are not paused.
    """
    original_state = run_quota.quota_state
    original_lock = RunRepository.lock_run_creation
    seen = {"armed": False, "checked": 0, "at_lock": 0}
    resume = asyncio.Event()

    async def lock(self, user_id):
        if seen["armed"]:
            seen["at_lock"] += 1
            if seen["at_lock"] >= 2:
                resume.set()
        await original_lock(self, user_id)

    async def state_then_pause(*args, **kwargs):
        result = await original_state(*args, **kwargs)
        if seen["armed"]:
            seen["checked"] += 1
            if seen["checked"] >= 2:
                resume.set()
            await asyncio.wait_for(resume.wait(), timeout=20)
        return result

    monkeypatch.setattr(RunRepository, "lock_run_creation", lock)
    monkeypatch.setattr(runs_router.run_quota, "quota_state", state_then_pause)

    def arm():
        seen["armed"] = True

    return arm


@pytestmark_db
async def test_ten_simultaneous_requests_for_the_last_allowance_admit_exactly_one(
    client, session, test_user, slow_limit_check
):
    await create_ok(client, 4)
    slow_limit_check()
    responses = await asyncio.gather(*(create(client) for _ in range(10)))
    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [429] * 9, codes
    assert len(await run_rows(session, test_user)) == 5


@pytestmark_db
async def test_simultaneous_requests_cannot_overfill_the_queue_either(
    client, session, test_user, monkeypatch, slow_limit_check
):
    monkeypatch.setenv("MAX_RUNS_PER_USER_PER_HOUR", "0")
    monkeypatch.setenv("MAX_RUN_SUBMISSIONS_PER_USER_PER_HOUR", "0")
    monkeypatch.setenv("MAX_QUEUED_RUNS_PER_USER", "2")
    slow_limit_check()
    responses = await asyncio.gather(*(create(client) for _ in range(12)))
    codes = sorted(r.status_code for r in responses)
    assert codes == [200] * 3 + [409] * 9, codes
    rows = await run_rows(session, test_user)
    assert len(rows) == 3 and sum(1 for r in rows if r.dispatch_seq is not None) == 1   # one active turn


@pytestmark_db
async def test_simultaneous_requests_of_different_users_do_not_wait_for_each_other(client, session):
    users = [await make_user(session, f"u{i}") for i in range(4)]
    maker = async_sessionmaker(session.bind, expire_on_commit=False)

    async def one(user):
        async with maker() as s:
            repo = RunRepository(s)
            await repo.lock_run_creation(user.id)
            await asyncio.sleep(0.5)                                          # all four hold "their" lock at once
            await s.commit()

    started = asyncio.get_running_loop().time()
    await asyncio.gather(*(one(u) for u in users))
    # In parallel (~0.6 s), not 4 x 0.5 in a row (2 s): wide enough apart that
    # four connections on a busy 2-CPU runner cannot blur the two.
    assert asyncio.get_running_loop().time() - started < 1.5


@pytestmark_db
async def test_with_the_hourly_quota_off_only_the_other_limits_apply(client, monkeypatch):
    monkeypatch.setenv("MAX_RUNS_PER_USER_PER_HOUR", "0")
    monkeypatch.setenv("MAX_QUEUED_RUNS_PER_USER", "9")
    await create_ok(client, 10)
    state_now = await quota(client)
    assert state_now["hourly"]["limit"] is None and state_now["hourly"]["remaining"] is None
    assert state_now["blocked_by"] == "QUEUE_FULL"


@pytestmark_db
async def test_create_reports_queue_position(client):
    first = data(await create(client))
    assert first["queued"] is False and first["queue_position"] is None
    second = data(await create(client))
    assert second["queued"] is True and second["queue_position"] == 1


# --------------------------------------------------------------------------- #
# Creating a run survives losing the promotion race
# --------------------------------------------------------------------------- #
@pytest.mark.integration
async def test_a_run_is_reported_to_its_owner_even_when_its_promotion_loses_a_race(client, session, monkeypatch):
    """Found on the real stack: two submissions of one user at the same moment
    (or one submission and the worker's sweep) can both try to promote. The
    loser rolls its session back; the route then read the new run from that
    session and answered 500, although the run had been created."""
    from sqlalchemy.exc import IntegrityError

    original = RunRepository._promote_next_locked
    lost = {"n": 0}

    async def lose_the_race_once(self, user_id):
        if lost["n"] == 0:
            lost["n"] += 1
            raise IntegrityError("UPDATE runs SET dispatch_seq", {}, Exception("duplicate key value violates unique constraint"))
        return await original(self, user_id)

    monkeypatch.setattr(RunRepository, "_promote_next_locked", lose_the_race_once)
    response = await create(client)
    assert response.status_code == 200, response.text
    created = data(response)
    assert lost["n"] == 1 and created["run_id"]
    # The run exists exactly once and is the one the client was told about.
    listed = data(await client.get("/runs"))
    assert [r["id"] for r in listed] == [created["run_id"]]
    # Nothing is stuck: the next sweep (here: the next submission) promotes as usual.
    second = await create(client)
    assert second.status_code == 200 and data(second)["run_id"] != created["run_id"]
