"""Timeouts, lost jobs, queue-wait limit and artifact persistence.

Every test here guards one way a run could otherwise end wrongly: reported DONE
without its files, or never ending at all. The database is the real test
PostgreSQL; only the remote method service is controlled.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.api.database.models import RunArtifact, RunStatus, RunTree, User
from apps.api.repositories.artifact_repository import ArtifactRepository
from apps.api.repositories.run_repository import RunRepository
from apps.api.repositories.run_tree_repository import RunTreeRepository
from apps.api.services import artifact_verification as verification
from apps.api.services import method_jobs_client as jobs
from apps.api.services.method_jobs_client import JobStatus, MethodJobNotFound
from apps.api.storage.base import ObjectStat
from apps.api.storage.local_storage import LocalStorage
from apps.api.workers import limits
from apps.api.workers import run_worker as worker

NEWICK = b"(a:1,b:2)root:0;\n"
RESULT = {
    "ok": True,
    "trees": ["(a:1,b:2)root:0;"],
    "manifest_version": 1,
    "artifacts": [
        {"object_key": "artifacts/r/j/tree.nwk", "filename": "tree.nwk",
         "size_bytes": len(NEWICK), "kind": "newick"},
        {"object_key": "artifacts/r/j/job.log", "filename": "job.log",
         "size_bytes": 4, "kind": "log", "role": "log"},
    ],
}


# --------------------------------------------------------------------------- #
# Limits (no database)
# --------------------------------------------------------------------------- #
def test_limits_have_generous_defaults_and_can_be_changed_or_disabled(monkeypatch):
    for name in ("RUN_TIMEOUT_SECONDS", "RUN_TIMEOUT_SECONDS_DOWSER", "RUN_QUEUE_WAIT_TIMEOUT_SECONDS",
                 "WORKER_METHOD_UNREACHABLE_SECONDS", "WORKER_CANCEL_CONFIRM_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    assert limits.run_timeout_seconds("gctree") == 24 * 3600
    assert limits.queue_wait_timeout_seconds() == 48 * 3600
    assert limits.method_unreachable_seconds() == 300
    assert limits.cancel_confirm_seconds() == 60

    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS_DOWSER", "7200")
    assert limits.run_timeout_seconds("gctree") == 600
    assert limits.run_timeout_seconds("dowser") == 7200        # per-method value wins

    monkeypatch.setenv("RUN_TIMEOUT_SECONDS_DOWSER", "0")       # 0 = no limit, for that method only
    assert limits.run_timeout_seconds("dowser") is None
    assert limits.run_timeout_seconds("gctree") == 600

    monkeypatch.setenv("RUN_QUEUE_WAIT_TIMEOUT_SECONDS", "0")
    assert limits.queue_wait_timeout_seconds() is None

    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "not-a-number")   # a typo must not remove the limit
    assert limits.run_timeout_seconds("gctree") == 24 * 3600


@pytest.mark.parametrize("seconds,text_", [(86400, "24 hours"), (5400, "90 minutes"), (45, "45 seconds"),
                                           (1, "1 second"), (9000, "2.5 hours")])
def test_durations_read_naturally_in_user_messages(seconds, text_):
    assert limits.describe_duration(seconds) == text_


def test_method_deadline_is_what_is_left_of_the_run_limit_plus_a_margin(monkeypatch):
    monkeypatch.delenv("WORKER_METHOD_DEADLINE_GRACE_SECONDS", raising=False)
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "1000")
    started = datetime.now(timezone.utc) - timedelta(seconds=400)
    deadline = worker._method_job_deadline("gctree", started)
    assert 595 + limits.METHOD_DEADLINE_GRACE_SECONDS <= deadline <= 600 + limits.METHOD_DEADLINE_GRACE_SECONDS
    monkeypatch.setenv("WORKER_METHOD_DEADLINE_GRACE_SECONDS", "10")
    assert 605 <= worker._method_job_deadline("gctree", started) <= 610
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "0")
    assert worker._method_job_deadline("gctree", started) is None


# --------------------------------------------------------------------------- #
# Artifact verification (no database)
# --------------------------------------------------------------------------- #
def rows_for(*specs):
    return [{"object_key": key, "filename": key.rsplit("/", 1)[-1], "size_bytes": size, "checksum_sha256": sha}
            for key, size, sha in specs]


class FakeStore:
    """An object store that answers from a table and can be made to fail."""

    def __init__(self, objects: dict[str, ObjectStat], failures: int = 0):
        self.objects, self.failures, self.calls = objects, failures, 0

    async def stat(self, key):
        self.calls += 1
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionError("store down")
        return self.objects.get(key)


async def test_local_storage_stat_reports_size_and_absence(tmp_path):
    store = LocalStorage(str(tmp_path / "bucket"))
    await store.upload(b"12345", "a/b.txt")
    assert await store.stat("a/b.txt") == ObjectStat(size_bytes=5)
    assert await store.stat("a/missing.txt") is None


async def test_verification_passes_only_when_every_object_is_stored_as_declared():
    store = FakeStore({"k/ok": ObjectStat(10, "aa"), "k/short": ObjectStat(3), "k/sum": ObjectStat(5, "bb")})
    report = await verification.verify_artifacts(
        rows_for(("k/ok", 10, "aa"), ("k/short", 10, None), ("k/sum", 5, "cc"), ("k/gone", 1, None)),
        store, attempts=1, retry_seconds=0,
    )
    assert not report.ok
    assert report.checked == 4
    assert report.verified_keys == {"k/ok"}
    problems = {p["filename"]: p["problem"] for p in report.problems}
    assert problems["gone"] == "not in the object store"
    assert "stored size 3 bytes, expected 10" in problems["short"]
    assert problems["sum"] == "checksum differs"

    clean = await verification.verify_artifacts(rows_for(("k/ok", 10, "aa")), store, attempts=1, retry_seconds=0)
    assert clean.ok and clean.checked == 1


async def test_a_checksum_is_compared_only_when_both_sides_declare_one():
    store = FakeStore({"k/a": ObjectStat(4, None), "k/b": ObjectStat(4, "aa")})
    report = await verification.verify_artifacts(
        rows_for(("k/a", 4, "ff"), ("k/b", 4, None)), store, attempts=1, retry_seconds=0)
    assert report.ok


async def test_an_unreachable_store_is_retried_then_reported_as_unavailable_not_as_missing_files():
    recovering = FakeStore({"k/a": ObjectStat(4)}, failures=2)
    report = await verification.verify_artifacts(rows_for(("k/a", 4, None)), recovering, attempts=3, retry_seconds=0)
    assert report.ok and recovering.calls == 3

    down = FakeStore({}, failures=99)
    with pytest.raises(verification.ArtifactStoreUnavailable):
        await verification.verify_artifacts(rows_for(("k/a", 4, None)), down, attempts=3, retry_seconds=0)
    assert down.calls == 3


async def test_a_run_without_artifacts_has_nothing_to_verify():
    report = await verification.verify_artifacts([], FakeStore({}, failures=5), attempts=1, retry_seconds=0)
    assert report.ok and report.checked == 0


# --------------------------------------------------------------------------- #
# Method client
# --------------------------------------------------------------------------- #
@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []

    def handle(request):
        requests.append(request)
        status, body = responses.pop(0)
        return httpx.Response(status, json=body)

    original = httpx.AsyncClient
    monkeypatch.setattr(jobs.httpx, "AsyncClient",
                        lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setenv("METHOD_GCTREE_URL", "http://gctree.test")
    return requests, responses


async def test_an_unknown_job_is_a_distinct_answer_not_a_transient_failure(transport):
    _, responses = transport
    responses.extend([(404, {"ok": False, "error": "Job not found"})] * 2)
    with pytest.raises(MethodJobNotFound):
        await jobs.get_job_status("gctree", "gone")
    with pytest.raises(MethodJobNotFound):
        await jobs.get_job_result("gctree", "gone")


async def test_submit_tells_the_service_how_long_the_job_may_run(transport):
    requests, responses = transport
    responses.extend([(200, {"job_id": "j1"}), (200, {"job_id": "j2"})])
    await jobs.submit_job("gctree", file_path="/x", params={}, run_id="r1", timeout_seconds=612.7)
    await jobs.submit_job("gctree", file_path="/x", params={}, run_id="r1")
    assert json.loads(requests[0].content)["timeout_seconds"] == 612
    assert "timeout_seconds" not in json.loads(requests[1].content)


# --------------------------------------------------------------------------- #
# Worker (real PostgreSQL)
# --------------------------------------------------------------------------- #
pytest_integration = pytest.mark.integration


@pytest.fixture
def store(tmp_path, monkeypatch):
    bucket = LocalStorage(str(tmp_path / "artifact-bucket"))
    monkeypatch.setattr(worker, "_artifact_storage", bucket)
    return bucket


@pytest.fixture
def worker_db(session, monkeypatch, store):
    monkeypatch.setattr(worker, "AsyncSessionLocal", async_sessionmaker(session.bind, expire_on_commit=False))
    monkeypatch.setattr(worker, "METHOD_POLL_INTERVAL", 0)
    monkeypatch.setenv("ARTIFACT_VERIFY_RETRY_SECONDS", "0")
    for name in ("RUN_TIMEOUT_SECONDS", "RUN_TIMEOUT_SECONDS_GCTREE", "RUN_QUEUE_WAIT_TIMEOUT_SECONDS",
                 "WORKER_METHOD_UNREACHABLE_SECONDS", "WORKER_CANCEL_CONFIRM_SECONDS",
                 "WORKER_METHOD_DEADLINE_GRACE_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    return session


async def make_user(session, tag: str) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(id=uuid.uuid4(), email=f"{tag}-{suffix}@test.io", username=f"{tag}-{suffix}", password_hash="x")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def running(session, *, method="gctree", job_id="job-1", started_seconds_ago=0, tag="u"):
    """A claimed run whose method job has been submitted."""
    user = await make_user(session, tag)
    repo = RunRepository(session)
    run = await repo.create_run(method_id=method, params={}, user_id=user.id)
    await repo.promote_next_for_user(user.id)
    await repo.claim_next_run("w", 60)
    values = {"method_job_id": job_id}
    if started_seconds_ago:
        values["started_at"] = datetime.now(timezone.utc) - timedelta(seconds=started_seconds_ago)
    await repo.update(run.id, **values)
    return run.id


async def fresh(session, run_id):
    session.expire_all()
    return await RunRepository(session).get_by_id(run_id)


def mock_jobs(monkeypatch, statuses, result=None):
    submit = AsyncMock(return_value="job-1")
    monkeypatch.setattr(worker.jobs, "submit_job", submit)
    monkeypatch.setattr(worker.jobs, "get_job_status", AsyncMock(side_effect=statuses))
    monkeypatch.setattr(worker.jobs, "get_job_result", AsyncMock(return_value=result))
    cancel = AsyncMock(return_value=True)
    monkeypatch.setattr(worker.jobs, "cancel_job", cancel)
    return submit, cancel


def error_code(run) -> str | None:
    try:
        return json.loads(run.error)["error"]["code"]
    except (TypeError, ValueError, KeyError):
        return None


async def rows(session, model, run_id):
    return (await session.execute(select(model).where(model.run_id == run_id))).scalars().all()


# ---- false DONE ------------------------------------------------------------ #
@pytest_integration
async def test_run_is_done_only_when_every_declared_artifact_is_in_the_store(worker_db, store, monkeypatch):
    run_id = await running(worker_db)
    await store.upload(NEWICK, "artifacts/r/j/tree.nwk")
    await store.upload(b"log\n", "artifacts/r/j/job.log")
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")], RESULT)
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.DONE
    assert len(await rows(worker_db, RunArtifact, run_id)) == 2
    assert len(await rows(worker_db, RunTree, run_id)) == 1


@pytest_integration
async def test_missing_artifacts_fail_the_run_instead_of_reporting_done(worker_db, store, monkeypatch):
    """The Phase 3 defect: uploads lost, run still DONE with nothing to download."""
    run_id = await running(worker_db)
    await store.upload(b"log\n", "artifacts/r/j/job.log")          # only the log made it
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")], RESULT)
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.ERROR
    assert error_code(run) == "ARTIFACTS_MISSING"
    assert "tree.nwk" in run.message and "not in the object store" in run.message
    assert run.finished_at is not None and run.worker_lease_until is None
    assert not await rows(worker_db, RunTree, run_id)
    kept = await rows(worker_db, RunArtifact, run_id)
    assert [a.filename for a in kept] == ["job.log"]                 # failed runs keep their (stored) log


@pytest_integration
async def test_an_artifact_of_the_wrong_size_is_not_accepted(worker_db, store, monkeypatch):
    run_id = await running(worker_db)
    await store.upload(b"(a", "artifacts/r/j/tree.nwk")              # truncated upload
    await store.upload(b"log\n", "artifacts/r/j/job.log")
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")], RESULT)
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.ERROR and error_code(run) == "ARTIFACTS_MISSING"
    assert "stored size 2 bytes" in run.message


@pytest_integration
async def test_upload_failures_reported_by_the_method_fail_the_run(worker_db, store, monkeypatch):
    """Even if a service still says DONE, declared upload failures are not a success."""
    run_id = await running(worker_db)
    await store.upload(b"log\n", "artifacts/r/j/job.log")
    result = {"ok": True, "trees": ["(a,b);"], "manifest_version": 1,
              "artifacts": [RESULT["artifacts"][1]],
              "artifact_upload_failures": [{"filename": "bundle.zip", "error": "connection refused"}]}
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")], result)
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.ERROR and error_code(run) == "ARTIFACT_UPLOAD_FAILED"
    assert "bundle.zip" in run.message
    assert "connection refused" not in run.message                   # internal detail stays out


@pytest_integration
async def test_a_store_outage_at_completion_fails_the_run_after_bounded_retries(worker_db, monkeypatch):
    run_id = await running(worker_db)
    outage = FakeStore({}, failures=99)
    monkeypatch.setattr(worker, "_artifact_storage", outage)
    monkeypatch.setenv("ARTIFACT_VERIFY_ATTEMPTS", "3")
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")], RESULT)
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.ERROR and error_code(run) == "ARTIFACT_STORE_UNAVAILABLE"
    assert outage.calls == 3
    assert not await rows(worker_db, RunArtifact, run_id)


@pytest_integration
async def test_done_trees_and_artifacts_become_visible_together(worker_db, store, monkeypatch):
    """A reader must never see DONE without the rows that belong to it."""
    run_id = await running(worker_db)
    await store.upload(NEWICK, "artifacts/r/j/tree.nwk")
    await store.upload(b"log\n", "artifacts/r/j/job.log")
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")], RESULT)

    seen = {}
    original = ArtifactRepository.replace_for_run
    observer = async_sessionmaker(worker_db.bind, expire_on_commit=False)

    async def spy(self, rid, artifacts):
        # Called after the status update, before the commit: another connection
        # must still see the run as running and without trees.
        async with observer() as other:
            seen["status"] = (await other.execute(
                text("SELECT status FROM runs WHERE id = :id"), {"id": rid})).scalar_one()
            seen["trees"] = (await other.execute(
                text("SELECT count(*) FROM run_trees WHERE run_id = :id"), {"id": rid})).scalar_one()
        return await original(self, rid, artifacts)

    monkeypatch.setattr(ArtifactRepository, "replace_for_run", spy)
    await worker.process_run(run_id, "w")
    assert seen == {"status": "RUNNING", "trees": 0}
    assert (await fresh(worker_db, run_id)).status == RunStatus.DONE


@pytest_integration
async def test_a_failure_while_saving_the_result_leaves_no_half_finished_run(worker_db, store, monkeypatch):
    run_id = await running(worker_db)
    await store.upload(NEWICK, "artifacts/r/j/tree.nwk")
    await store.upload(b"log\n", "artifacts/r/j/job.log")
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")], RESULT)
    monkeypatch.setattr(RunTreeRepository, "replace_for_run", AsyncMock(side_effect=RuntimeError("disk full")))
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.ERROR                             # never DONE without its trees
    assert "disk full" not in (run.message or "")
    assert not await rows(worker_db, RunArtifact, run_id)


# ---- time limit ------------------------------------------------------------ #
@pytest_integration
async def test_a_run_past_its_time_limit_is_stopped_and_fails_as_timeout(worker_db, monkeypatch):
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "3600")
    run_id = await running(worker_db, started_seconds_ago=3700)
    owner = (await fresh(worker_db, run_id)).user_id
    waiting = await RunRepository(worker_db).create_run(method_id="gctree", params={}, user_id=owner)
    waiting_id = waiting.id
    _, cancel = mock_jobs(monkeypatch, [JobStatus(False, "job-1", "CANCELLED")])
    await worker.process_run(run_id, "w")
    cancel.assert_awaited_once_with("gctree", "job-1")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.ERROR and error_code(run) == "TIMEOUT"
    assert "maximum run time of 60 minutes" in run.message
    assert run.finished_at is not None and run.worker_lease_until is None
    assert (await fresh(worker_db, waiting_id)).dispatch_seq is not None    # the owner's next run moves up


@pytest_integration
async def test_a_timed_out_run_keeps_the_last_lines_its_job_printed(worker_db, monkeypatch):
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "60")
    run_id = await running(worker_db, started_seconds_ago=120)
    stopped = JobStatus(False, "job-1", "CANCELLED",
                        raw={"status": "CANCELLED", "log_tail": "clone 12 of 40\nbuilding tree"})
    mock_jobs(monkeypatch, [stopped])
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert error_code(run) == "TIMEOUT"
    tails = [e["out"] for e in run.result["logs"] if e["step"] == "method.job.log_tail"]
    assert tails == ["clone 12 of 40\nbuilding tree"]
    assert "building tree" not in run.message                        # the message itself stays short


@pytest_integration
async def test_a_run_inside_its_time_limit_is_left_alone(worker_db, store, monkeypatch):
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "3600")
    run_id = await running(worker_db, started_seconds_ago=3000)
    _, cancel = mock_jobs(monkeypatch, [JobStatus(True, "job-1", "RUNNING"), JobStatus(False, "job-1", "ERROR",
                                                                                      message="method failure")])
    await worker.process_run(run_id, "w")
    cancel.assert_not_awaited()
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.ERROR and error_code(run) is None and run.error == "method failure"


@pytest_integration
async def test_the_time_limit_can_be_set_per_method_and_disabled(worker_db, monkeypatch):
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS_GCTREE", "0")
    run_id = await running(worker_db, started_seconds_ago=100000)
    _, cancel = mock_jobs(monkeypatch, [JobStatus(False, "job-1", "CANCELLED")])
    await worker.process_run(run_id, "w")
    cancel.assert_not_awaited()
    assert (await fresh(worker_db, run_id)).status == RunStatus.CANCELLED


@pytest_integration
async def test_a_job_that_cannot_be_stopped_still_ends_the_run_as_timeout(worker_db, monkeypatch):
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("WORKER_CANCEL_CONFIRM_SECONDS", "0")
    run_id = await running(worker_db, started_seconds_ago=120)
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "RUNNING")] * 3)
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.ERROR and error_code(run) == "TIMEOUT"
    assert json.loads(run.error)["error"]["details"]["stop_confirmed"] is False


@pytest_integration
async def test_a_job_that_finished_just_before_the_stop_keeps_its_result(worker_db, store, monkeypatch):
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "60")
    run_id = await running(worker_db, started_seconds_ago=120)
    await store.upload(NEWICK, "artifacts/r/j/tree.nwk")
    await store.upload(b"log\n", "artifacts/r/j/job.log")
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")], RESULT)
    await worker.process_run(run_id, "w")
    assert (await fresh(worker_db, run_id)).status == RunStatus.DONE


@pytest_integration
async def test_a_user_cancel_is_never_reported_as_a_timeout(worker_db, monkeypatch):
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "60")
    run_id = await running(worker_db, started_seconds_ago=120)
    await RunRepository(worker_db).request_cancel(run_id)
    mock_jobs(monkeypatch, [JobStatus(False, "job-1", "CANCELLED")])
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.CANCELLED and run.error is None


# ---- lost job / unreachable service ---------------------------------------- #
@pytest_integration
async def test_a_job_the_service_no_longer_knows_fails_the_run_without_resubmitting(worker_db, monkeypatch):
    run_id = await running(worker_db)
    submit, _ = mock_jobs(monkeypatch, [MethodJobNotFound("gone")])
    await worker.process_run(run_id, "w")
    submit.assert_not_awaited()
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.ERROR and error_code(run) == "METHOD_RESTARTED"
    assert "submit it again" in run.message


@pytest_integration
async def test_an_unreachable_service_is_tolerated_only_for_a_bounded_time(worker_db, monkeypatch):
    monkeypatch.setenv("WORKER_METHOD_UNREACHABLE_SECONDS", "0")
    run_id = await running(worker_db)
    mock_jobs(monkeypatch, [httpx.ConnectError("refused")])
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.ERROR and error_code(run) == "METHOD_UNREACHABLE"
    assert "refused" not in run.message


@pytest_integration
async def test_a_short_outage_does_not_fail_the_run(worker_db, monkeypatch):
    run_id = await running(worker_db)
    mock_jobs(monkeypatch, [httpx.ConnectError("refused")] * 4 + [JobStatus(False, "job-1", "CANCELLED")])
    await worker.process_run(run_id, "w")
    assert (await fresh(worker_db, run_id)).status == RunStatus.CANCELLED


@pytest_integration
async def test_cancelling_while_the_service_is_gone_still_ends_as_cancelled(worker_db, monkeypatch):
    monkeypatch.setenv("WORKER_METHOD_UNREACHABLE_SECONDS", "0")
    run_id = await running(worker_db)
    await RunRepository(worker_db).request_cancel(run_id)
    mock_jobs(monkeypatch, [httpx.ConnectError("refused")])
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.CANCELLED and run.error is None


@pytest_integration
async def test_a_cancel_the_service_never_confirms_is_still_closed(worker_db, monkeypatch):
    monkeypatch.setenv("WORKER_CANCEL_CONFIRM_SECONDS", "0")
    run_id = await running(worker_db)
    await RunRepository(worker_db).request_cancel(run_id)
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "RUNNING")] * 3)
    await worker.process_run(run_id, "w")
    assert (await fresh(worker_db, run_id)).status == RunStatus.CANCELLED


@pytest_integration
async def test_a_result_that_cannot_be_fetched_fails_the_run_after_retries(worker_db, monkeypatch):
    run_id = await running(worker_db)
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")])
    fetch = AsyncMock(side_effect=httpx.ReadTimeout("slow"))
    monkeypatch.setattr(worker.jobs, "get_job_result", fetch)
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.ERROR and error_code(run) == "RESULT_UNAVAILABLE"
    assert fetch.await_count == worker.RESULT_FETCH_ATTEMPTS


@pytest_integration
async def test_a_failure_code_set_by_the_method_service_is_kept_with_the_run(worker_db, monkeypatch):
    run_id = await running(worker_db)
    status = JobStatus(False, "job-1", "ERROR", message="The job ran out of memory.",
                       raw={"status": "ERROR", "message": "The job ran out of memory.", "error_code": "OUT_OF_MEMORY"})
    mock_jobs(monkeypatch, [status])
    await worker.process_run(run_id, "w")
    run = await fresh(worker_db, run_id)
    assert run.status == RunStatus.ERROR and error_code(run) == "OUT_OF_MEMORY"
    assert run.message == "The job ran out of memory."


@pytest_integration
async def test_an_unreachable_service_at_submit_requeues_the_run(worker_db, monkeypatch):
    user = await make_user(worker_db, "s")
    repo = RunRepository(worker_db)
    run = await repo.create_run(method_id="gctree", params={}, user_id=user.id)
    await repo.promote_next_for_user(user.id)
    await repo.claim_next_run("w", 60)
    monkeypatch.setattr(worker.jobs, "submit_job", AsyncMock(side_effect=httpx.ConnectError("refused")))
    await worker.process_run(run.id, "w")
    again = await fresh(worker_db, run.id)
    assert again.status == RunStatus.QUEUED and again.stage == "WAITING_FOR_CAPACITY"
    assert again.started_at is None and again.dispatch_seq is not None
    assert "not reachable" in again.stage_message


@pytest_integration
async def test_submit_carries_the_remaining_time_as_the_services_own_deadline(worker_db, monkeypatch):
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "1000")
    user = await make_user(worker_db, "d")
    repo = RunRepository(worker_db)
    run = await repo.create_run(method_id="gctree", params={}, user_id=user.id)
    await repo.promote_next_for_user(user.id)
    await repo.claim_next_run("w", 60)
    submit, _ = mock_jobs(monkeypatch, [JobStatus(False, "job-1", "CANCELLED")])
    await worker.process_run(run.id, "w")
    deadline = submit.await_args.kwargs["timeout_seconds"]
    assert 990 + limits.METHOD_DEADLINE_GRACE_SECONDS <= deadline <= 1000 + limits.METHOD_DEADLINE_GRACE_SECONDS


# ---- queue-wait limit ------------------------------------------------------- #
async def ready_run(session, tag: str, waited_seconds: float = 0):
    user = await make_user(session, tag)
    repo = RunRepository(session)
    run = await repo.create_run(method_id="dowser", params={}, user_id=user.id)
    await repo.promote_next_for_user(user.id)
    if waited_seconds:
        await repo.update(run.id, dispatch_ready_at=datetime.now(timezone.utc) - timedelta(seconds=waited_seconds))
    return run.id, user.id


@pytest_integration
async def test_promotion_records_when_a_run_became_ready(worker_db):
    run_id, _ = await ready_run(worker_db, "p")
    run = await fresh(worker_db, run_id)
    assert run.dispatch_ready_at is not None
    assert abs((datetime.now(timezone.utc) - run.dispatch_ready_at).total_seconds()) < 30


@pytest_integration
async def test_a_run_that_waited_too_long_for_a_slot_ends_with_a_clear_message(worker_db, monkeypatch):
    monkeypatch.setenv("RUN_QUEUE_WAIT_TIMEOUT_SECONDS", "3600")
    old_id, owner = await ready_run(worker_db, "old", waited_seconds=4000)
    behind = await RunRepository(worker_db).create_run(method_id="dowser", params={}, user_id=owner)
    behind_id = behind.id
    recent_id, _ = await ready_run(worker_db, "recent", waited_seconds=100)

    expired = await worker.expire_waiting_runs()
    assert expired == [old_id]
    old = await fresh(worker_db, old_id)
    assert old.status == RunStatus.ERROR and error_code(old) == "QUEUE_TIMEOUT"
    assert "waited more than 60 minutes" in old.message and "Nothing was executed" in old.message
    assert old.started_at is None and old.finished_at is not None      # it never ran
    assert (await fresh(worker_db, recent_id)).status == RunStatus.QUEUED
    assert (await fresh(worker_db, behind_id)).dispatch_seq is not None  # the owner's next run moves up
    assert await worker.expire_waiting_runs() == []                     # idempotent


@pytest_integration
async def test_the_queue_wait_limit_never_touches_started_runs_and_can_be_disabled(worker_db, monkeypatch):
    monkeypatch.setenv("RUN_QUEUE_WAIT_TIMEOUT_SECONDS", "3600")
    running_id = await running(worker_db, tag="r")
    await RunRepository(worker_db).update(
        running_id, dispatch_ready_at=datetime.now(timezone.utc) - timedelta(days=30))
    assert await worker.expire_waiting_runs() == []
    assert (await fresh(worker_db, running_id)).status == RunStatus.RUNNING

    waiting_id, _ = await ready_run(worker_db, "w", waited_seconds=10**6)
    monkeypatch.setenv("RUN_QUEUE_WAIT_TIMEOUT_SECONDS", "0")
    assert await worker.expire_waiting_runs() == []
    assert (await fresh(worker_db, waiting_id)).status == RunStatus.QUEUED


@pytest_integration
async def test_waiting_for_capacity_does_not_restart_the_waiting_clock(worker_db):
    run_id, _ = await ready_run(worker_db, "c", waited_seconds=500)
    repo = RunRepository(worker_db)
    before = (await fresh(worker_db, run_id)).dispatch_ready_at
    await repo.claim_next_run("w", 60)
    assert await repo.release_for_capacity(run_id, "w", "busy")
    assert (await fresh(worker_db, run_id)).dispatch_ready_at == before


# ---- slow store / lease ------------------------------------------------------ #
async def test_a_store_that_never_answers_counts_as_unavailable(monkeypatch):
    import asyncio

    class Silent:
        calls = 0

        async def stat(self, key):
            Silent.calls += 1
            await asyncio.sleep(60)

    monkeypatch.setenv("ARTIFACT_VERIFY_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(verification, "verify_timeout_seconds", lambda: 0.05)
    with pytest.raises(verification.ArtifactStoreUnavailable):
        await verification.verify_artifacts(rows_for(("k/a", 1, None)), Silent(), attempts=2, retry_seconds=0)
    assert Silent.calls == 2


@pytest_integration
async def test_the_lease_is_kept_while_a_slow_completion_is_in_hand(worker_db, store, monkeypatch):
    """A run being finished must not look abandoned and be claimed a second time."""
    import asyncio

    monkeypatch.setattr(worker, "LEASE_SECONDS", 3)          # renewed every second
    run_id = await running(worker_db)
    await store.upload(NEWICK, "artifacts/r/j/tree.nwk")
    await store.upload(b"log\n", "artifacts/r/j/job.log")
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")])
    leases = []

    async def slow_result(*_):
        for _ in range(3):
            await asyncio.sleep(1.2)
            leases.append((await fresh(worker_db, run_id)).worker_lease_until)
        return RESULT

    monkeypatch.setattr(worker.jobs, "get_job_result", slow_result)
    await worker.process_run(run_id, "w")
    assert leases[0] < leases[1] < leases[2]                 # extended while waiting
    assert all(lease > datetime.now(timezone.utc) - timedelta(seconds=4) for lease in leases)
    assert (await fresh(worker_db, run_id)).status == RunStatus.DONE
