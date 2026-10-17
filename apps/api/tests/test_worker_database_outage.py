"""A database that is briefly away must not cost anyone a run.

Found on the real stack: restarting PostgreSQL while a job was running made the
worker fail the run, delete the input the job was still reading, and report a
meaningless error minutes later. The job itself needs no database; the worker
now waits for it, and if it stays away, leaves the run for recovery.

Real PostgreSQL; the outage is simulated at the one place the worker opens
sessions.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import asyncpg
import httpx
import pytest
from sqlalchemy import exc as sa_exc
from sqlalchemy.ext.asyncio import create_async_engine

from apps.api.database.errors import database_unavailable
from apps.api.database.models import RunStatus
from apps.api.services import run_staging
from apps.api.services.method_jobs_client import JobStatus
from apps.api.tests.test_run_recovery import RESULT, fresh, mock_jobs, running, store, store_result_files, worker_db  # noqa: F401
from apps.api.workers import limits
from apps.api.workers import run_worker as worker

pytestmark = pytest.mark.integration


class Outage:
    """Stands where the worker gets its database sessions; can be switched off."""

    def __init__(self, real):
        self.real, self.down, self.refused = real, False, 0

    def __call__(self):
        if self.down:
            self.refused += 1
            raise asyncpg.exceptions.CannotConnectNowError("the database system is shutting down")
        return self.real()


@pytest.fixture
def outage(worker_db, monkeypatch, tmp_path):
    switch = Outage(worker.AsyncSessionLocal)
    monkeypatch.setattr(worker, "AsyncSessionLocal", switch)
    monkeypatch.setattr(worker, "DATABASE_RETRY_SECONDS", 0.01)
    monkeypatch.setattr(run_staging, "runtime_shared_root_host", lambda: tmp_path)
    monkeypatch.delenv("WORKER_DATABASE_UNAVAILABLE_SECONDS", raising=False)
    return switch


def work_directory(run_id):
    """What a job reads its input from while it runs."""
    directory = run_staging._run_work_dir_sync(run_id)
    (directory / "01_input.tsv").write_text("sequence_id\tsequence\n")
    return directory


# --------------------------------------------------------------------------- #
# Recognising the situation
# --------------------------------------------------------------------------- #
async def test_only_a_database_that_is_away_counts_as_unavailable():
    assert database_unavailable(asyncpg.exceptions.CannotConnectNowError("the database system is starting up"))
    assert database_unavailable(asyncpg.exceptions.ConnectionDoesNotExistError("connection was closed"))
    assert database_unavailable(asyncpg.exceptions.AdminShutdownError("terminating connection"))
    assert database_unavailable(sa_exc.OperationalError("SELECT 1", {}, Exception("server closed the connection")))
    assert database_unavailable(sa_exc.InterfaceError("SELECT 1", {}, Exception("connection is closed")))
    try:
        raise RuntimeError("could not store the result") from asyncpg.exceptions.CannotConnectNowError("shutting down")
    except RuntimeError as wrapped:
        assert database_unavailable(wrapped)                                # found through the chain

    # A real refused connection, raised inside the driver.
    engine = create_async_engine("postgresql+asyncpg://nobody:nothing@127.0.0.1:1/nowhere")
    with pytest.raises(Exception) as refused:
        async with engine.connect():
            pass
    await engine.dispose()
    assert database_unavailable(refused.value)

    # Things that are not the database being away.
    assert not database_unavailable(None)
    assert not database_unavailable(ValueError("bad parameter"))
    assert not database_unavailable(ConnectionRefusedError("some other service"))     # not raised by the driver
    assert not database_unavailable(httpx.ConnectError("method service down"))
    assert not database_unavailable(sa_exc.IntegrityError("INSERT", {}, Exception("duplicate key")))
    assert not database_unavailable(sa_exc.ProgrammingError("SELEC 1", {}, Exception("syntax error")))
    assert not database_unavailable(asyncpg.exceptions.UniqueViolationError("duplicate"))
    assert not database_unavailable(asyncpg.exceptions.QueryCanceledError("statement timeout"))


def test_the_patience_is_configurable_and_has_a_sane_default(monkeypatch):
    monkeypatch.delenv("WORKER_DATABASE_UNAVAILABLE_SECONDS", raising=False)
    assert limits.database_unavailable_seconds() == 90
    monkeypatch.setenv("WORKER_DATABASE_UNAVAILABLE_SECONDS", "20")
    assert limits.database_unavailable_seconds() == 20
    monkeypatch.setenv("WORKER_DATABASE_UNAVAILABLE_SECONDS", "junk")
    assert limits.database_unavailable_seconds() == 90
    # Never longer than half the lease: the run must not look abandoned while it is being waited for.
    assert worker.LEASE_SECONDS / 2 >= 60


# --------------------------------------------------------------------------- #
# A short outage: the run is simply followed to its end
# --------------------------------------------------------------------------- #
async def test_a_short_outage_while_a_job_runs_changes_nothing_about_the_run(outage, worker_db, store, monkeypatch):
    run_id = await running(worker_db)
    directory = work_directory(run_id)
    await store_result_files(store)
    submit, cancel = mock_jobs(monkeypatch, [], RESULT)
    polls = {"n": 0}

    async def status(method_id, job_id):
        polls["n"] += 1
        if polls["n"] == 2:
            outage.down = True                                              # the database goes away mid-run...
        return JobStatus(True, job_id, "RUNNING" if polls["n"] < 4 else "DONE")

    async def back_after_a_moment():
        while outage.refused < 5:
            await asyncio.sleep(0.005)
        assert directory.exists()                                           # the job's input is not touched meanwhile
        outage.down = False                                                 # ...and comes back

    monkeypatch.setattr(worker.jobs, "get_job_status", status)
    await asyncio.gather(worker.process_run(run_id, "w"), back_after_a_moment())

    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.DONE and run.error is None
    assert outage.refused >= 5                                              # it really was away, several attempts long
    cancel.assert_not_awaited()                                             # the job was left alone
    submit.assert_not_awaited()                                             # and not submitted a second time
    assert not directory.exists()                                           # cleaned up only at the real end


async def test_an_outage_at_the_moment_the_result_is_stored_does_not_lose_or_duplicate_it(outage, worker_db, store, monkeypatch):
    run_id = await running(worker_db)
    await store_result_files(store)
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")] * 6, RESULT)
    original, attempts = worker._persist_done, {"n": 0}

    async def flaky_persist(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise asyncpg.exceptions.ConnectionDoesNotExistError("connection was closed in the middle of operation")
        return await original(*args, **kwargs)

    monkeypatch.setattr(worker, "_persist_done", flaky_persist)
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.DONE and attempts["n"] == 2
    from apps.api.database.models import RunArtifact, RunTree
    from sqlalchemy import func, select
    assert (await worker_db.execute(select(func.count()).select_from(RunTree).where(RunTree.run_id == run_id))).scalar() == 1
    assert (await worker_db.execute(select(func.count()).select_from(RunArtifact).where(RunArtifact.run_id == run_id))).scalar() == 3


async def test_a_run_that_was_settled_just_before_the_connection_dropped_is_not_processed_again(outage, worker_db, store, monkeypatch):
    run_id = await running(worker_db)
    mock_jobs(monkeypatch, [], RESULT)
    asked = AsyncMock(return_value=JobStatus(False, "job-1", "ERROR", message="boom"))
    monkeypatch.setattr(worker.jobs, "get_job_status", asked)
    await worker.process_run(run_id, "w")
    assert (await fresh(worker_db, run_id)).status == RunStatus.ERROR and asked.await_count == 1
    # Followed again (as after a lost acknowledgement): the stored outcome stands, the service is not asked.
    await worker._poll_method_job(run_id, "gctree", "job-1", "w")
    assert asked.await_count == 1 and (await fresh(worker_db, run_id)).error == "boom"


# --------------------------------------------------------------------------- #
# A long outage: the run is left exactly as it is, and recovered later
# --------------------------------------------------------------------------- #
async def test_a_long_outage_leaves_the_run_and_its_job_alone_and_it_is_finished_later(outage, worker_db, store, monkeypatch):
    monkeypatch.setenv("WORKER_DATABASE_UNAVAILABLE_SECONDS", "0.1")
    run_id = await running(worker_db)
    directory = work_directory(run_id)
    await store_result_files(store)
    submit, cancel = mock_jobs(monkeypatch, [], RESULT)

    async def status(method_id, job_id):
        outage.down = True                                                  # away from the first look on
        return JobStatus(True, job_id, "RUNNING")

    monkeypatch.setattr(worker.jobs, "get_job_status", status)
    await worker.process_run(run_id, "w")                                   # gives up waiting, without raising

    outage.down = False
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.RUNNING and run.method_job_id == "job-1"  # not failed, not forgotten
    assert run.error is None and run.finished_at is None
    cancel.assert_not_awaited()                                             # the job goes on computing
    assert (directory / "01_input.tsv").exists()                            # with its input still there

    # The database is back; the run is picked up again (as after a worker restart) and completed.
    monkeypatch.setattr(worker.jobs, "get_job_status", AsyncMock(return_value=JobStatus(True, "job-1", "DONE")))
    await worker.process_run(run_id, "w2")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.DONE
    submit.assert_not_awaited()                                             # never submitted a second time
    assert not directory.exists()                                           # and now the work directory is removed


async def test_an_outage_before_any_job_exists_does_not_fail_the_run_either(outage, worker_db, monkeypatch):
    from apps.api.repositories.run_repository import RunRepository
    from apps.api.tests.test_run_recovery import make_user

    user = await make_user(worker_db, "early")
    repo = RunRepository(worker_db)
    run = await repo.create_run(method_id="gctree", params={}, user_id=user.id)
    await repo.promote_next_for_user(user.id)
    await repo.claim_next_run("w", 60)
    submit, _ = mock_jobs(monkeypatch, [], RESULT)

    async def submit_then_lose_the_database(*args, **kwargs):
        outage.down = True
        return "job-1"

    monkeypatch.setattr(worker.jobs, "submit_job", submit_then_lose_the_database)
    await worker.process_run(run.id, "w")
    outage.down = False
    row = await fresh(worker_db, run.id)
    assert row.status == RunStatus.RUNNING and row.error is None            # waits for recovery, is not failed


# --------------------------------------------------------------------------- #
# A real internal error still ends the run, and now also stops its job
# --------------------------------------------------------------------------- #
async def test_an_internal_error_ends_the_run_with_a_reference_and_stops_the_job(outage, worker_db, store, monkeypatch):
    run_id = await running(worker_db)
    directory = work_directory(run_id)
    _, cancel = mock_jobs(monkeypatch, [JobStatus(True, "job-1", "RUNNING")], RESULT)
    monkeypatch.setattr(worker.jobs, "get_job_status", AsyncMock(return_value=JobStatus(True, "job-1", "RUNNING")))
    monkeypatch.setattr(worker, "_normalize_method_poll_stage", lambda *a: (_ for _ in ()).throw(KeyError("a programming error")))
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.ERROR and "internal error (reference " in run.error
    assert "programming error" not in run.error                             # the exception text stays in the log
    cancel.assert_awaited_once_with("gctree", "job-1")                      # the orphaned job does not keep its slot
    assert not directory.exists()


async def test_an_internal_error_that_cannot_be_recorded_leaves_the_run_for_recovery(outage, worker_db, store, monkeypatch):
    run_id = await running(worker_db)
    _, cancel = mock_jobs(monkeypatch, [], RESULT)
    monkeypatch.setattr(worker.jobs, "get_job_status", AsyncMock(return_value=JobStatus(True, "job-1", "RUNNING")))

    def explode(*_args):
        outage.down = True                                                  # the error cannot be written down either
        raise KeyError("a programming error")

    monkeypatch.setattr(worker, "_normalize_method_poll_stage", explode)
    await worker.process_run(run_id, "w")                                   # must not raise
    outage.down = False
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.RUNNING and run.error is None
    cancel.assert_not_awaited()


# --------------------------------------------------------------------------- #
# One run, one task
# --------------------------------------------------------------------------- #
async def test_a_run_claimed_again_by_the_worker_that_already_has_it_is_not_started_twice(monkeypatch):
    import uuid

    started = []

    async def fake_process(run_id, worker_id, tracker):
        started.append(run_id)
        await asyncio.sleep(0.05)

    monkeypatch.setattr(worker, "process_run", fake_process)
    active: set = set()
    run_id, other = uuid.uuid4(), uuid.uuid4()
    first = worker.start_processing(run_id, "w", None, active)
    assert first is not None and active == {run_id}
    assert worker.start_processing(run_id, "w", None, active) is None       # still in hand: refused
    second = worker.start_processing(other, "w", None, active)
    await asyncio.gather(first, second)
    await asyncio.sleep(0)
    assert started == [run_id, other] and active == set()
    again = worker.start_processing(run_id, "w", None, active)               # free again once the first task is over
    assert again is not None
    await again
