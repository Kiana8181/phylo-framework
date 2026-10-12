"""Result retention, cleanup and the limits that keep disk use bounded.

Real PostgreSQL and a real (on-disk) artifact store. What is protected here:
results disappear only after their date and only for finished runs; removal can
be repeated and interrupted safely; datasets are never removed by it; failed
runs keep a downloadable log; and an input that takes too long to prepare does
not hold a run for ever.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.api.database.models import (
    File,
    NotificationOutbox,
    Run,
    RunArtifact,
    RunStatus,
    RunTree,
    StorageState,
    UploadSession,
    UploadSessionStatus,
)
from apps.api.repositories.run_repository import RunRepository
from apps.api.services import retention as settings
from apps.api.services import upload_cleanup
from apps.api.services.method_jobs_client import JobStatus
from apps.api.storage.local_storage import LocalStorage
from apps.api.tests.test_run_recovery import RESULT, make_user, mock_jobs, running, store_result_files
from apps.api.workers import retention
from apps.api.workers import run_worker as worker

DAY = timedelta(days=1)


# --------------------------------------------------------------------------- #
# Settings and storage (no database)
# --------------------------------------------------------------------------- #
def test_settings_have_documented_defaults_and_survive_typos(monkeypatch):
    names = ("RESULT_RETENTION_DAYS", "MAX_UPLOAD_MB", "UPLOAD_SESSION_GRACE_HOURS", "RETENTION_SWEEP_SECONDS")
    for name in names:
        monkeypatch.delenv(name, raising=False)
    assert settings.result_retention_days() == 60 and settings.retention_period() == 60 * DAY
    assert settings.max_upload_bytes() == 500 * 1024 * 1024
    assert settings.upload_session_grace() == timedelta(hours=24) and settings.sweep_seconds() == 3600
    for name in names:
        monkeypatch.setenv(name, "not-a-number")                       # a typo keeps the default
    assert settings.result_retention_days() == 60 and settings.max_upload_bytes() == 500 * 1024 * 1024
    monkeypatch.setenv("RESULT_RETENTION_DAYS", "-5")
    assert settings.result_retention_days() == 60
    monkeypatch.setenv("RESULT_RETENTION_DAYS", "0")                   # explicit: keep for ever
    assert settings.retention_period() is None
    monkeypatch.setenv("RESULT_RETENTION_DAYS", "7.5")
    assert settings.retention_period() == timedelta(days=7.5)
    monkeypatch.setenv("MAX_UPLOAD_MB", "0")                           # "no file at all" is not a valid limit
    assert settings.max_upload_bytes() == 500 * 1024 * 1024


def test_expired_message_tells_the_user_what_happened_and_what_to_do(monkeypatch):
    monkeypatch.setenv("RESULT_RETENTION_DAYS", "60")
    message = settings.expired_message(datetime(2026, 12, 11, tzinfo=timezone.utc))
    assert "expired on 2026-12-11" in message and "kept for 60 days" in message
    assert "stays in your history" in message and "run it again" in message


async def test_deleting_by_prefix_removes_exactly_that_runs_files(tmp_path):
    store = LocalStorage(str(tmp_path / "bucket"))
    for key in ("artifacts/run-1/job/a.zip", "artifacts/run-1/job/b.log", "artifacts/run-1/other/c.png",
                "artifacts/run-10/job/keep.zip", "artifacts/run-2/job/keep.zip", "datasets/u/keep.tsv"):
        await store.upload(b"x", key)
    assert await store.delete_prefix("artifacts/run-1/") == 3
    remaining = sorted(p.relative_to(tmp_path / "bucket").as_posix() for p in (tmp_path / "bucket").rglob("*") if p.is_file())
    assert remaining == ["artifacts/run-10/job/keep.zip", "artifacts/run-2/job/keep.zip", "datasets/u/keep.tsv"]
    assert await store.delete_prefix("artifacts/run-1/") == 0          # nothing left: not an error
    assert await store.delete_prefix("artifacts/never-existed/") == 0
    for dangerous in ("", "/"):
        with pytest.raises(ValueError):
            await store.delete_prefix(dangerous)
    with pytest.raises(ValueError):
        await store.delete_prefix("../outside/")
    assert len(remaining) == 3


# --------------------------------------------------------------------------- #
# Fixtures (real PostgreSQL)
# --------------------------------------------------------------------------- #
db_test = pytest.mark.integration
RETENTION_ENV = ("RESULT_RETENTION_DAYS", "MAX_UPLOAD_MB", "UPLOAD_SESSION_GRACE_HOURS", "RUN_STAGING_TIMEOUT_SECONDS",
                 "RUN_TIMEOUT_SECONDS", "RUN_QUEUE_WAIT_TIMEOUT_SECONDS")


@pytest.fixture
def store(tmp_path, monkeypatch):
    bucket = LocalStorage(str(tmp_path / "artifact-bucket"))
    monkeypatch.setattr(worker, "_artifact_storage", bucket)
    monkeypatch.setattr(retention, "_storage", bucket)
    return bucket


@pytest.fixture
def db(session, monkeypatch, store):
    maker = async_sessionmaker(session.bind, expire_on_commit=False)
    for module in (worker, retention, upload_cleanup):
        monkeypatch.setattr(module, "AsyncSessionLocal", maker)
    monkeypatch.setattr(worker, "METHOD_POLL_INTERVAL", 0)
    for name in RETENTION_ENV:
        monkeypatch.delenv(name, raising=False)
    return session


async def run_row(session, run_id) -> Run:
    return (await session.execute(select(Run).where(Run.id == run_id).execution_options(populate_existing=True))).scalar_one()


async def rows(session, model, run_id):
    return (await session.execute(
        select(model).where(model.run_id == run_id).execution_options(populate_existing=True))).scalars().all()


def stored(store) -> list[str]:
    return sorted(p.relative_to(store.base_path).as_posix() for p in store.base_path.rglob("*") if p.is_file())


async def finished_run(session, store, monkeypatch, *, tag="u") -> uuid.UUID:
    """A DONE run with its three files in the store, under the run's own prefix."""
    run_id = await running(session, tag=tag)
    result = json.loads(json.dumps(RESULT).replace("artifacts/r/j/", f"artifacts/{run_id}/job-1/"))
    for entry in result["artifacts"]:
        await store.upload(b"x" * entry["size_bytes"], entry["object_key"])
    jobs_mock(monkeypatch, [JobStatus(True, "job-1", "DONE")], result)
    await worker.process_run(run_id, "w")
    assert (await run_row(session, run_id)).status == RunStatus.DONE
    return run_id


def jobs_mock(monkeypatch, statuses, result=None, *, log="job output\n"):
    """mock_jobs plus the two housekeeping calls the worker makes afterwards."""
    submit, cancel = mock_jobs(monkeypatch, statuses, result)
    delete = AsyncMock(return_value=True)
    get_log = AsyncMock(return_value=log)
    monkeypatch.setattr(worker.jobs, "delete_job", delete)
    monkeypatch.setattr(worker.jobs, "get_job_log", get_log)
    return submit, cancel, delete, get_log


async def age(session, run_id, days_past_expiry=1.0):
    """Move a run's dates so that its results expired ``days_past_expiry`` ago."""
    past = datetime.now(timezone.utc) - timedelta(days=days_past_expiry)
    await session.execute(update(Run).where(Run.id == run_id).values(expires_at=past, finished_at=past - 60 * DAY))
    await session.commit()


# --------------------------------------------------------------------------- #
# The expiry date is fixed when a run ends
# --------------------------------------------------------------------------- #
@db_test
async def test_every_way_a_run_ends_gives_it_an_expiry_date_sixty_days_out(db, store, monkeypatch):
    repo = RunRepository(db)
    done = await finished_run(db, store, monkeypatch, tag="d")

    failed = await running(db, tag="e")
    jobs_mock(monkeypatch, [JobStatus(False, "job-1", "ERROR", message="boom")])
    await worker.process_run(failed, "w")

    owner = await make_user(db, "c")
    queued = await repo.create_run(method_id="gctree", params={}, user_id=owner.id)
    await repo.promote_next_for_user(owner.id)
    assert await repo.cancel_if_queued(queued.id, "Cancelled by user")
    behind = await repo.create_run(method_id="gctree", params={}, user_id=owner.id)
    second = await repo.create_run(method_id="gctree", params={}, user_id=owner.id)
    assert await repo.cancel_queued_run(second.id, owner.id) is not None

    stopped = await running(db, tag="s")
    await repo.request_cancel(stopped)
    jobs_mock(monkeypatch, [JobStatus(False, "job-1", "CANCELLED")])
    await worker.process_run(stopped, "w")

    waiter = await make_user(db, "q")
    waiting = await repo.create_run(method_id="dowser", params={}, user_id=waiter.id)
    await repo.promote_next_for_user(waiter.id)
    await repo.update(waiting.id, dispatch_ready_at=datetime.now(timezone.utc) - timedelta(hours=50))
    assert await worker.expire_waiting_runs() == [waiting.id]

    for run_id in (done, failed, queued.id, second.id, stopped, waiting.id):
        run = await run_row(db, run_id)
        kept_for = run.expires_at - run.finished_at
        assert timedelta(days=59, hours=23) < kept_for < timedelta(days=60, hours=1), (run.status, kept_for)
        assert run.results_expired_at is None
    assert (await run_row(db, behind.id)).expires_at is None           # still waiting: no date yet


@db_test
async def test_the_promised_date_does_not_move_when_the_setting_changes(db, store, monkeypatch):
    first = await finished_run(db, store, monkeypatch, tag="a")
    promised = (await run_row(db, first)).expires_at
    monkeypatch.setenv("RESULT_RETENTION_DAYS", "7")
    second = await finished_run(db, store, monkeypatch, tag="b")
    later = await run_row(db, second)
    assert timedelta(days=6, hours=23) < later.expires_at - later.finished_at < timedelta(days=7, hours=1)
    assert (await run_row(db, first)).expires_at == promised           # unchanged
    assert await retention.sweep() == {}                               # and nothing is due


@db_test
async def test_with_retention_off_runs_get_no_date_and_nothing_is_removed(db, store, monkeypatch):
    monkeypatch.setenv("RESULT_RETENTION_DAYS", "0")
    run_id = await finished_run(db, store, monkeypatch)
    assert (await run_row(db, run_id)).expires_at is None
    await db.execute(update(Run).where(Run.id == run_id).values(expires_at=datetime.now(timezone.utc) - DAY))
    await db.commit()                                                  # even a stale date is not acted on
    assert await retention.sweep() == {}
    assert len(stored(store)) == 3


@db_test
async def test_runs_that_ended_before_retention_existed_are_counted_from_the_upgrade(db, store, monkeypatch):
    """What migration 016 does: no old run loses its results on deployment day."""
    import importlib.util
    from pathlib import Path

    path = Path(worker.__file__).resolve().parents[1] / "database/migrations/versions/016_result_retention.py"
    spec = importlib.util.spec_from_file_location("migration_016", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setenv("RESULT_RETENTION_DAYS", "junk")
    assert migration._retention_days() == 60
    monkeypatch.delenv("RESULT_RETENTION_DAYS")

    old = await finished_run(db, store, monkeypatch, tag="o")
    stale = await finished_run(db, store, monkeypatch, tag="s")        # carries a date from before, already past
    far = await finished_run(db, store, monkeypatch, tag="f")          # carries a later date than the policy gives
    long_ago = datetime.now(timezone.utc) - timedelta(days=400)
    await db.execute(update(Run).where(Run.id == old).values(finished_at=long_ago, expires_at=None))
    await db.execute(update(Run).where(Run.id == stale).values(finished_at=long_ago, expires_at=long_ago + DAY))
    far_date = datetime.now(timezone.utc) + timedelta(days=365)
    await db.execute(update(Run).where(Run.id == far).values(expires_at=far_date))
    waiting = await RunRepository(db).create_run(method_id="gctree", params={}, user_id=(await make_user(db, "w")).id)
    await db.commit()

    # The migration's own statements, run against this database.
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)
    migration.upgrade()
    assert len(statements) == 3 and "UPDATE runs" in statements[1]
    for statement in statements:
        await db.execute(text(statement))
    await db.commit()

    for run_id in (old, stale):
        run = await run_row(db, run_id)
        assert timedelta(days=59) < run.expires_at - datetime.now(timezone.utc) < timedelta(days=61)
    assert abs((await run_row(db, far)).expires_at - far_date) < timedelta(seconds=1)   # never moved earlier
    assert (await run_row(db, waiting.id)).expires_at is None
    assert await retention.sweep() == {} and len(stored(store)) == 9   # nothing is removed on upgrade day

    # With retention switched off the migration puts no date on anything.
    monkeypatch.setenv("RESULT_RETENTION_DAYS", "0")
    statements.clear()
    migration.upgrade()
    assert len(statements) == 2 and not any("UPDATE runs" in s for s in statements)


# --------------------------------------------------------------------------- #
# Expiry removes the results and keeps the run
# --------------------------------------------------------------------------- #
@db_test
async def test_expired_results_are_removed_and_the_run_stays_as_history(db, store, monkeypatch):
    run_id = await finished_run(db, store, monkeypatch)
    await store.upload(b"orphan", f"artifacts/{run_id}/job-1/never-registered.tmp")     # uploaded, never listed
    await store.upload(b"other", "artifacts/another-run/job/keep.zip")
    before = await run_row(db, run_id)
    assert len(await rows(db, RunArtifact, run_id)) == 3 and len(await rows(db, RunTree, run_id)) == 1
    assert before.result and len(await rows(db, NotificationOutbox, run_id)) == 1
    await db.execute(update(NotificationOutbox).where(NotificationOutbox.run_id == run_id).values(status="SENT"))
    await age(db, run_id)

    assert await retention.sweep() == {"expired": 1}

    assert stored(store) == ["artifacts/another-run/job/keep.zip"]     # this run's files, registered or not
    artifacts = await rows(db, RunArtifact, run_id)
    assert len(artifacts) == 3 and all(a.storage_state == StorageState.DELETED and a.object_deleted_at for a in artifacts)
    assert await rows(db, RunTree, run_id) == [] and await rows(db, NotificationOutbox, run_id) == []
    run = await run_row(db, run_id)
    assert run.result is None and run.results_expired_at is not None
    # The run itself is still there, with what makes it meaningful as history.
    assert (run.status, run.method_id, run.params, run.message) == (RunStatus.DONE, before.method_id, before.params, before.message)
    assert run.finished_at is not None and run.user_id == before.user_id


@db_test
async def test_results_that_are_not_due_and_runs_that_are_not_finished_are_never_touched(db, store, monkeypatch):
    fresh = await finished_run(db, store, monkeypatch, tag="f")                      # expires in 60 days
    tomorrow = await finished_run(db, store, monkeypatch, tag="t")
    await db.execute(update(Run).where(Run.id == tomorrow).values(expires_at=datetime.now(timezone.utc) + DAY))
    active = await running(db, tag="a")
    await store.upload(b"partial", f"artifacts/{active}/job-1/partial.zip")
    # A date in the past on a run that is still going must not matter.
    await db.execute(update(Run).where(Run.id == active).values(expires_at=datetime.now(timezone.utc) - DAY))
    queued = await RunRepository(db).create_run(method_id="gctree", params={}, user_id=(await make_user(db, "q")).id)
    await db.execute(update(Run).where(Run.id == queued.id).values(expires_at=datetime.now(timezone.utc) - DAY))
    await db.commit()

    assert await retention.sweep() == {}
    assert len(stored(store)) == 7
    for run_id in (fresh, tomorrow, active, queued.id):
        assert (await run_row(db, run_id)).results_expired_at is None
    for run_id in (fresh, tomorrow, active, queued.id):                # even when asked directly
        assert await retention.expire_run(run_id) is False
    assert len(stored(store)) == 7 and f"artifacts/{active}/job-1/partial.zip" in stored(store)
    assert all(a.storage_state == StorageState.ACTIVE for a in await rows(db, RunArtifact, fresh))


@db_test
async def test_a_running_runs_files_survive_a_direct_expiry_attempt(db, store, monkeypatch):
    """Belt and braces: the database refuses to mark an unfinished run expired."""
    active = await running(db)
    assert await RunRepository(db).mark_results_expired(active) is False
    run = await run_row(db, active)
    assert run.status == RunStatus.RUNNING and run.results_expired_at is None


@db_test
async def test_removal_is_repeatable(db, store, monkeypatch):
    run_id = await finished_run(db, store, monkeypatch)
    await age(db, run_id)
    assert await retention.sweep() == {"expired": 1}
    first = (await run_row(db, run_id)).results_expired_at
    assert await retention.sweep() == {}                               # nothing left to do
    assert await retention.expire_run(run_id) is False                 # asked again: no change
    assert (await run_row(db, run_id)).results_expired_at == first


@db_test
async def test_if_the_store_is_down_nothing_changes_and_the_next_sweep_finishes_the_job(db, store, monkeypatch):
    run_id = await finished_run(db, store, monkeypatch)
    await age(db, run_id)
    before = await run_row(db, run_id)

    class Down:
        async def delete_prefix(self, prefix):
            raise ConnectionError("store unreachable")

    monkeypatch.setattr(retention, "_storage", Down())
    assert await retention.sweep() == {"retry": 1}
    run = await run_row(db, run_id)
    assert run.results_expired_at is None and run.result == before.result       # never marked while files may exist
    assert len(await rows(db, RunTree, run_id)) == 1
    assert all(a.storage_state == StorageState.ACTIVE for a in await rows(db, RunArtifact, run_id))
    assert len(stored(store)) == 3

    monkeypatch.setattr(retention, "_storage", store)                  # the store is back
    assert await retention.sweep() == {"expired": 1}
    assert stored(store) == [] and (await run_row(db, run_id)).results_expired_at is not None


@db_test
async def test_an_interruption_between_the_two_steps_is_completed_later(db, store, monkeypatch):
    """Files already deleted, database not yet updated (the process died in between)."""
    run_id = await finished_run(db, store, monkeypatch)
    await age(db, run_id)
    assert await store.delete_prefix(retention.run_prefix(run_id)) == 3
    assert (await run_row(db, run_id)).results_expired_at is None
    assert await retention.sweep() == {"expired": 1}
    assert (await run_row(db, run_id)).results_expired_at is not None and await rows(db, RunTree, run_id) == []


@db_test
async def test_one_run_that_cannot_be_cleaned_does_not_hold_up_the_others(db, store, monkeypatch):
    good = await finished_run(db, store, monkeypatch, tag="g")
    bad = await finished_run(db, store, monkeypatch, tag="b")
    for run_id in (good, bad):
        await age(db, run_id)

    class Flaky:
        async def delete_prefix(self, prefix):
            if str(bad) in prefix:
                raise PermissionError("denied")
            return await store.delete_prefix(prefix)

    monkeypatch.setattr(retention, "_storage", Flaky())
    assert await retention.sweep() == {"expired": 1, "retry": 1}
    assert (await run_row(db, good)).results_expired_at is not None
    assert (await run_row(db, bad)).results_expired_at is None


@db_test
async def test_a_notification_still_waiting_to_be_sent_survives_expiry(db, store, monkeypatch):
    run_id = await finished_run(db, store, monkeypatch)
    await age(db, run_id)
    assert await retention.sweep() == {"expired": 1}
    (pending,) = await rows(db, NotificationOutbox, run_id)
    assert pending.status == "PENDING"


@db_test
async def test_datasets_are_never_removed_by_retention(db, store, monkeypatch, tmp_path):
    run_id = await finished_run(db, store, monkeypatch)
    run = await run_row(db, run_id)
    dataset = tmp_path / "dataset.tsv"
    dataset.write_text("sequence_id\tsequence\n")
    file_id = uuid.uuid4()
    await db.execute(text(
        "INSERT INTO files (id, user_id, original_filename, storage_type, storage_path, file_size, storage_state) "
        "VALUES (:id, :user, 'dataset.tsv', 'LOCAL', :path, 21, 'ACTIVE')"),
        {"id": file_id, "user": run.user_id, "path": str(dataset)})
    await db.execute(update(Run).where(Run.id == run_id).values(input_file_id=file_id))
    await age(db, run_id, days_past_expiry=400)
    assert await retention.sweep() == {"expired": 1}
    kept = (await db.execute(select(File).where(File.id == file_id))).scalar_one()
    assert kept.storage_state == StorageState.ACTIVE and dataset.exists()
    assert (await run_row(db, run_id)).input_file_id == file_id        # the run still says what it ran on


@db_test
async def test_an_expired_run_is_no_longer_offered_for_comparison(db, store, monkeypatch):
    first = await finished_run(db, store, monkeypatch, tag="a")
    second = await finished_run(db, store, monkeypatch, tag="b")
    file_id, owner = uuid.uuid4(), (await run_row(db, first)).user_id
    await db.execute(text(
        "INSERT INTO files (id, user_id, original_filename, storage_type, storage_path, file_size, storage_state) "
        "VALUES (:id, :user, 'shared.tsv', 'LOCAL', '/nowhere/shared.tsv', 1, 'ACTIVE')"), {"id": file_id, "user": owner})
    await db.execute(update(Run).where(Run.id.in_([first, second])).values(input_file_id=file_id, user_id=owner))
    await db.commit()
    repo = RunRepository(db)
    assert [r.id for r in await repo.get_by_same_input_file(file_id, first, owner)] == [second]
    await age(db, second)
    assert await retention.sweep() == {"expired": 1}
    assert await repo.get_by_same_input_file(file_id, first, owner) == []


@db_test
async def test_the_sweep_loop_survives_its_own_failures(db, monkeypatch):
    monkeypatch.setenv("RETENTION_SWEEP_SECONDS", "0.05")
    calls = {"n": 0}
    stop = asyncio.Event()

    async def flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] >= 3:
            stop.set()
        raise RuntimeError("database is away")

    monkeypatch.setattr(retention, "sweep", flaky)
    await asyncio.wait_for(retention.retention_loop(stop), timeout=5)
    assert calls["n"] == 3


# --------------------------------------------------------------------------- #
# What the API says before and after
# --------------------------------------------------------------------------- #
@db_test
async def test_the_expiry_date_is_visible_before_and_expired_results_answer_410(db, store, monkeypatch, client):
    from apps.api.auth.dependencies import get_current_user
    from apps.api.database.models import User
    from apps.api.main import app
    from apps.api.routers import artifacts as artifacts_router

    monkeypatch.setattr(artifacts_router, "_storage_inst", store)
    run_id = await finished_run(db, store, monkeypatch)
    owner = (await db.execute(select(User).where(User.id == (await run_row(db, run_id)).user_id))).scalar_one()
    app.dependency_overrides[get_current_user] = lambda: owner

    def data(response):
        body = response.json()
        return body.get("data", body) if isinstance(body, dict) else body

    status = data(await client.get(f"/runs/{run_id}/status"))
    assert status["results_expired"] is False and status["results_expired_at"] is None
    expires = datetime.fromisoformat(status["expires_at"])
    assert timedelta(days=59) < expires - datetime.now(timezone.utc) < timedelta(days=61)
    listed = data(await client.get("/runs"))[0]
    assert listed["expires_at"] == status["expires_at"] and listed["results_expired"] is False
    assert data(await client.get(f"/runs/{run_id}/result"))["expires_at"] == status["expires_at"]
    artifact = data(await client.get(f"/runs/{run_id}/artifacts"))["artifacts"][0]
    tree_id = data(await client.get(f"/runs/{run_id}/trees"))["trees"][0]["treeId"]
    assert (await client.get(artifact["download_url"])).status_code == 200

    await age(db, run_id)
    assert await retention.sweep() == {"expired": 1}

    for path in (f"/runs/{run_id}/result", f"/runs/{run_id}/trees", f"/runs/{run_id}/trees/{tree_id}",
                 f"/runs/{run_id}/artifacts", artifact["download_url"], artifact["download_url"].replace("download", "preview")):
        gone = await client.get(path)
        assert gone.status_code == 410, path
        assert gone.json()["data"]["code"] == "RESULT_EXPIRED" and "expired on" in gone.json()["message"]
    # The run is still in the history, and says that its results are gone.
    status = data(await client.get(f"/runs/{run_id}/status"))
    assert status["status"] == "DONE" and status["results_expired"] is True and status["results_expired_at"]
    listed = data(await client.get("/runs"))[0]
    assert listed["id"] == str(run_id) and listed["results_expired"] is True and listed["method_id"] == "gctree"


# --------------------------------------------------------------------------- #
# Failed runs keep a log; the service forgets finished jobs
# --------------------------------------------------------------------------- #
@db_test
async def test_a_run_stopped_at_its_time_limit_gets_a_downloadable_log(db, store, monkeypatch):
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "60")
    run_id = await running(db, started_seconds_ago=120)
    log = "clone 12 of 40\nbuilding tree\n"
    _, _, delete, get_log = jobs_mock(monkeypatch, [JobStatus(False, "job-1", "CANCELLED")], log=log)
    await worker.process_run(run_id, "w")
    assert (await run_row(db, run_id)).status == RunStatus.ERROR
    get_log.assert_awaited_once_with("gctree", "job-1")
    (row,) = await rows(db, RunArtifact, run_id)
    assert (row.filename, row.artifact_role, row.size_bytes, row.is_previewable) == ("job.log", "log", len(log), True)
    assert row.object_key == f"artifacts/{run_id}/job-1/job.log" and row.checksum_sha256 == hashlib.sha256(log.encode()).hexdigest()
    assert (store.base_path / row.object_key).read_text() == log       # under the run's prefix: it expires with the run
    delete.assert_awaited_once_with("gctree", "job-1")                 # and the service may forget the job


@db_test
async def test_a_job_that_uploaded_its_own_log_is_not_fetched_again(db, store, monkeypatch):
    run_id = await running(db)
    manifest = {"manifest_version": 1, "artifacts": [
        {"object_key": f"artifacts/{run_id}/job-1/job.log", "filename": "job.log", "size_bytes": 4, "kind": "log", "role": "log"}]}
    status = JobStatus(False, "job-1", "ERROR", message="method failed", error=manifest)
    _, _, delete, get_log = jobs_mock(monkeypatch, [status])
    await worker.process_run(run_id, "w")
    assert len(await rows(db, RunArtifact, run_id)) == 1
    get_log.assert_not_awaited()
    delete.assert_awaited_once()


@db_test
async def test_finished_and_cancelled_runs_let_the_service_forget_the_job_without_fetching_a_log(db, store, monkeypatch):
    done = await running(db, tag="d")
    await store_result_files(store)
    _, _, delete, get_log = jobs_mock(monkeypatch, [JobStatus(True, "job-1", "DONE")], RESULT)
    await worker.process_run(done, "w")
    delete.assert_awaited_once_with("gctree", "job-1")
    get_log.assert_not_awaited()

    cancelled = await running(db, tag="c")
    await RunRepository(db).request_cancel(cancelled)
    _, _, delete, get_log = jobs_mock(monkeypatch, [JobStatus(False, "job-1", "CANCELLED")])
    await worker.process_run(cancelled, "w")
    assert (await run_row(db, cancelled)).status == RunStatus.CANCELLED
    delete.assert_awaited_once()
    get_log.assert_not_awaited()
    assert await rows(db, RunArtifact, cancelled) == []


@db_test
@pytest.mark.parametrize("failing", ["log", "delete", "both"])
async def test_housekeeping_failures_never_change_a_runs_outcome(db, store, monkeypatch, failing):
    run_id = await running(db)
    _, _, delete, get_log = jobs_mock(monkeypatch, [JobStatus(False, "job-1", "ERROR", message="method failed")])
    if failing in ("log", "both"):
        get_log.side_effect = ConnectionError("service gone")
    if failing in ("delete", "both"):
        delete.side_effect = ConnectionError("service gone")
    await worker.process_run(run_id, "w")
    run = await run_row(db, run_id)
    assert run.status == RunStatus.ERROR and run.error == "method failed"
    delete.assert_awaited_once()                                       # still asked, even when the log failed


@db_test
async def test_a_run_handed_back_to_the_queue_keeps_its_job_untouched(db, monkeypatch):
    from apps.api.services.method_jobs_client import MethodBusy

    user = await make_user(db, "b")
    repo = RunRepository(db)
    run = await repo.create_run(method_id="gctree", params={}, user_id=user.id)
    await repo.promote_next_for_user(user.id)
    await repo.claim_next_run("w", 60)
    delete = AsyncMock()
    monkeypatch.setattr(worker.jobs, "submit_job", AsyncMock(side_effect=MethodBusy("full", 5)))
    monkeypatch.setattr(worker.jobs, "delete_job", delete)
    await worker.process_run(run.id, "w")
    assert (await run_row(db, run.id)).status == RunStatus.QUEUED
    delete.assert_not_awaited()


# --------------------------------------------------------------------------- #
# Input preparation is bounded
# --------------------------------------------------------------------------- #
@db_test
async def test_an_input_that_takes_too_long_to_prepare_fails_the_run_and_frees_its_place(db, monkeypatch, tmp_path):
    from apps.api.services import run_staging

    monkeypatch.setenv("RUN_STAGING_TIMEOUT_SECONDS", "0.3")
    monkeypatch.setattr(run_staging, "runtime_shared_root_host", lambda: tmp_path)
    user = await make_user(db, "s")
    repo = RunRepository(db)
    run = await repo.create_run(method_id="gctree", params={}, user_id=user.id)
    behind = await repo.create_run(method_id="gctree", params={}, user_id=user.id)
    await repo.promote_next_for_user(user.id)
    await repo.claim_next_run("w", 60)
    work = run_staging.run_work_root(run.id) / "abc"
    started = asyncio.Event()

    async def slow_prepare(**_kwargs):
        work.mkdir(parents=True)
        (work / "half-converted.tsv").write_text("partial")
        started.set()
        await asyncio.sleep(30)

    submit = AsyncMock()
    monkeypatch.setattr(worker, "prepare_method_input", slow_prepare)
    monkeypatch.setattr(worker, "_resolve_input_storage_path", AsyncMock(return_value="datasets/u/in.tsv"))
    monkeypatch.setattr(worker.jobs, "submit_job", submit)
    began = time.monotonic()
    await worker.process_run(run.id, "w")
    assert time.monotonic() - began < 5 and started.is_set()

    failed = await run_row(db, run.id)
    assert failed.status == RunStatus.ERROR and json.loads(failed.error)["error"]["code"] == "STAGING_TIMEOUT"
    assert "Preparing the input file took longer than" in failed.message and "was not started" in failed.message
    submit.assert_not_awaited()                                        # the method was never started
    assert not (tmp_path / "runs" / str(run.id)).exists()              # nothing of it left on disk
    assert (await run_row(db, behind.id)).dispatch_seq is not None     # the owner's next run moves up


def test_staging_timeout_setting(monkeypatch):
    from apps.api.workers import limits

    monkeypatch.delenv("RUN_STAGING_TIMEOUT_SECONDS", raising=False)
    assert limits.staging_timeout_seconds() == 1800
    monkeypatch.setenv("RUN_STAGING_TIMEOUT_SECONDS", "0")
    assert limits.staging_timeout_seconds() is None
    monkeypatch.setenv("RUN_STAGING_TIMEOUT_SECONDS", "junk")
    assert limits.staging_timeout_seconds() == 1800


def test_cleaning_a_work_directory_leaves_no_empty_directories(tmp_path, monkeypatch):
    from apps.api.services import run_staging

    monkeypatch.setattr(run_staging, "runtime_shared_root_host", lambda: tmp_path)
    run_id = uuid.uuid4()
    first = run_staging._run_work_dir_sync(run_id)
    second = run_staging._run_work_dir_sync(run_id)
    (first / "input.tsv").write_text("x")
    run_staging.cleanup_workspace(first, run_id)
    assert not first.exists() and second.exists()                      # another work directory of the run is kept
    run_staging.cleanup_workspace(second, run_id)
    assert not (tmp_path / "runs" / str(run_id)).exists()
    # A path outside the run's own work area is never removed.
    outside = tmp_path / "precious"
    outside.mkdir()
    run_staging.cleanup_workspace(outside, run_id)
    assert outside.exists()


# --------------------------------------------------------------------------- #
# Uploads: size limit and abandoned sessions
# --------------------------------------------------------------------------- #
@db_test
async def test_a_file_over_the_upload_limit_is_refused_before_and_during_the_upload(client, account, session, monkeypatch, tmp_path):
    monkeypatch.setenv("MAX_UPLOAD_MB", "0.001")                       # 1048 bytes
    headers = {"Authorization": f"Bearer {account['access_token']}"}

    limits_ = (await client.get("/uploads/limits", headers=headers)).json()
    assert limits_["max_upload_bytes"] == 1048 and limits_["used_bytes"] == 0 and limits_["remaining_bytes"] == limits_["quota_bytes"]

    # The client says how large the file is: refused at once, nothing is sent.
    declared = await client.post("/uploads/init", json={"original_filename": "big.fa", "expected_size": 5000}, headers=headers)
    assert declared.status_code == 413 and declared.json()["data"]["code"] == "UPLOAD_TOO_LARGE"
    assert "MB allowed for one upload" in declared.json()["message"] and declared.json()["data"]["max_upload_bytes"] == 1048

    # The client does not say (or lies): stopped while the bytes arrive.
    init = (await client.post("/uploads/init", json={"original_filename": "big.fa", "expected_size": 10}, headers=headers)).json()
    sent = await client.put(init["content_url"], content=b"A" * 5000, headers=headers)
    assert sent.status_code == 413 and sent.json()["data"]["code"] == "UPLOAD_TOO_LARGE"
    upload = (await session.execute(select(UploadSession).where(UploadSession.id == uuid.UUID(init["upload_id"]))
                                    .execution_options(populate_existing=True))).scalar_one()
    assert upload.status == UploadSessionStatus.ERROR and not os.path.exists(upload.temp_storage_path)
    assert (await session.execute(select(File))).scalars().all() == []  # nothing was stored

    # A file within the limit is accepted.
    ok = (await client.post("/uploads/init", json={"original_filename": "ok.fa", "expected_size": 1000}, headers=headers)).json()
    assert (await client.put(ok["content_url"], content=b"A" * 1000, headers=headers)).status_code == 200
    assert (await client.get("/uploads/limits", headers=headers)).json()["used_bytes"] == 1000
    del client.headers["Authorization"]
    assert (await client.get("/uploads/limits")).status_code == 401


@db_test
async def test_uploads_nobody_finished_are_cleaned_up_and_finished_ones_are_not(db, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOAD_SESSION_GRACE_HOURS", "24")
    root = tmp_path / "phylo-uploads"
    monkeypatch.setattr(upload_cleanup, "temp_roots", lambda: [root])
    user = await make_user(db, "up")
    old, recent = datetime.now(timezone.utc) - timedelta(hours=30), datetime.now(timezone.utc) - timedelta(hours=2)

    async def session_row(status, created, *, temp=True, name="x.fa"):
        upload_id = uuid.uuid4()
        temp_path = root / str(user.id) / f"{upload_id}.part"
        if temp:
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_bytes(b"partial")
            stamp = created.timestamp()
            os.utime(temp_path, (stamp, stamp))
        db.add(UploadSession(id=upload_id, user_id=user.id, status=status, original_filename=name,
                             bytes_received=7, temp_storage_path=str(temp_path) if temp else None, created_at=created))
        await db.commit()
        return upload_id, temp_path

    abandoned, abandoned_file = await session_row(UploadSessionStatus.UPLOADING, old)
    never_sent, _ = await session_row(UploadSessionStatus.INITIATED, old, temp=False)
    failed, failed_file = await session_row(UploadSessionStatus.ERROR, old)
    in_progress, in_progress_file = await session_row(UploadSessionStatus.UPLOADING, recent)
    finished, _ = await session_row(UploadSessionStatus.COMPLETED, old, temp=False)
    # A partial file whose session is gone (e.g. the API restarted mid-upload).
    stray_dir = root / "someone-else"
    stray_dir.mkdir(parents=True)
    stray = stray_dir / "orphan.part"
    stray.write_bytes(b"x")
    os.utime(stray, (old.timestamp(), old.timestamp()))

    assert await upload_cleanup.sweep() == {"sessions": 3, "files": 1}

    statuses = {s.id: s.status for s in (await db.execute(
        select(UploadSession).execution_options(populate_existing=True))).scalars().all()}
    assert statuses[abandoned] == statuses[never_sent] == statuses[failed] == UploadSessionStatus.CANCELLED
    assert statuses[in_progress] == UploadSessionStatus.UPLOADING      # still within its time
    assert statuses[finished] == UploadSessionStatus.COMPLETED         # a dataset: never touched here
    assert not abandoned_file.exists() and not failed_file.exists() and not stray.exists()
    assert in_progress_file.exists()
    assert await upload_cleanup.sweep() == {}                          # repeatable


@db_test
async def test_cleanup_never_pulls_the_directory_from_under_an_upload_that_is_starting(client, account, monkeypatch, tmp_path):
    """An upload creates its directory, then opens its file a moment later. The
    clean-up once removed empty directories and made such an upload fail (500)."""
    from apps.api.routers import uploads

    headers = {"Authorization": f"Bearer {account['access_token']}"}

    # Deterministic version of the race: the clean-up runs exactly between the
    # two steps, at the first database call the route makes after mkdir.
    original = uploads.UploadSessionRepository.mark_uploading
    seen = {}

    async def sweep_then_mark(self, upload_id, temp_path):
        user_dir = Path(temp_path).parent
        assert user_dir.is_dir() and not Path(temp_path).exists()
        monkeypatch.setattr(upload_cleanup, "temp_roots", lambda: [user_dir.parent])
        seen["removed"] = upload_cleanup.remove_stray_temp_files(0)    # as aggressive as it can be
        seen["dir_still_there"] = user_dir.is_dir()
        return await original(self, upload_id, temp_path)

    monkeypatch.setattr(uploads.UploadSessionRepository, "mark_uploading", sweep_then_mark)
    init = (await client.post("/uploads/init", json={"original_filename": "racing.fa"}, headers=headers)).json()
    sent = await client.put(init["content_url"], content=b">a\nACGT\n", headers=headers)
    assert seen == {"removed": 0, "dir_still_there": True}
    assert sent.status_code == 200, sent.text


# --------------------------------------------------------------------------- #
# The finished-run email says until when
# --------------------------------------------------------------------------- #
def test_the_finished_email_says_until_when_the_results_are_kept():
    from apps.api.services import email_templates as templates

    facts = templates.RunFacts(run_id="r", method_name="GCtree", expires_at=datetime(2026, 12, 11, tzinfo=timezone.utc))
    done = templates.run_finished("DONE", facts, run_url="https://x/r")
    assert "The results are kept until 2026-12-11." in done.text and "after that date they are removed" in done.text
    no_date = templates.run_finished("DONE", templates.RunFacts(run_id="r", method_name="GCtree"), run_url="https://x/r")
    assert "kept until" not in no_date.text
    assert "kept until" not in templates.run_finished("QUEUE_TIMEOUT", facts, run_url="https://x/r").text
