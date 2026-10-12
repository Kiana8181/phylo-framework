"""Run notifications: the outbox and its delivery.

Real PostgreSQL and a real (local) SMTP server; only the scientific method
service is controlled. The questions answered here:

  - who gets an email: DONE, ERROR and QUEUE_TIMEOUT do, CANCELLED never does;
  - can a notification exist without its run's final status, or twice: no;
  - can the mail server (down, slow, refusing) change a run: no;
  - does delivery stop trying, and does it avoid sending twice: yes.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.api.database.models import NotificationOutbox, Run, RunStatus, RunTree
from apps.api.repositories.notification_repository import NotificationRepository
from apps.api.repositories.run_repository import RunRepository
from apps.api.repositories.run_tree_repository import RunTreeRepository
from apps.api.services.method_jobs_client import JobStatus
from apps.api.storage.local_storage import LocalStorage
from apps.api.tests.test_run_recovery import RESULT, make_user, mock_jobs, running, store_result_files
from apps.api.workers import notifier
from apps.api.workers import run_worker as worker
from tests.support.smtp_sink import SmtpSink

pytestmark = pytest.mark.integration

SMTP_ENV = ("SMTP_HOST", "SMTP_PORT", "SMTP_SECURITY", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM",
            "SMTP_TIMEOUT_SECONDS", "SMTP_TLS_VERIFY", "SMTP_TLS_CA_FILE", "RUN_NOTIFICATIONS_ENABLED",
            "NOTIFICATION_MAX_ATTEMPTS", "NOTIFICATION_RETRY_BASE_SECONDS", "NOTIFICATION_RETRY_MAX_SECONDS",
            "NOTIFICATION_POLL_SECONDS")


@pytest.fixture
def store(tmp_path, monkeypatch):
    bucket = LocalStorage(str(tmp_path / "artifact-bucket"))
    monkeypatch.setattr(worker, "_artifact_storage", bucket)
    return bucket


@pytest.fixture
def db(session, monkeypatch, store):
    """Worker and notifier use the test database; email starts switched off."""
    maker = async_sessionmaker(session.bind, expire_on_commit=False)
    monkeypatch.setattr(worker, "AsyncSessionLocal", maker)
    monkeypatch.setattr(notifier, "AsyncSessionLocal", maker)
    monkeypatch.setattr(worker, "METHOD_POLL_INTERVAL", 0)
    monkeypatch.setattr(notifier, "FRONTEND_URL", "https://phylo.lab.example")
    for name in (*SMTP_ENV, "RUN_TIMEOUT_SECONDS", "RUN_QUEUE_WAIT_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    return session


@pytest.fixture
async def sink(monkeypatch, db):
    """A mail server, and the application configured to use it."""
    async with SmtpSink() as server:
        monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
        monkeypatch.setenv("SMTP_PORT", str(server.port))
        monkeypatch.setenv("SMTP_SECURITY", "none")
        monkeypatch.setenv("SMTP_FROM", "Phylo Runner <phylo@lab.example>")
        monkeypatch.setenv("SMTP_TIMEOUT_SECONDS", "3")
        yield server


async def outbox(session, run_id=None) -> list[NotificationOutbox]:
    stmt = select(NotificationOutbox).order_by(NotificationOutbox.created_at).execution_options(populate_existing=True)
    if run_id is not None:
        stmt = stmt.where(NotificationOutbox.run_id == run_id)
    return list((await session.execute(stmt)).scalars().all())


async def run_row(session, run_id) -> Run:
    return (await session.execute(select(Run).where(Run.id == run_id).execution_options(populate_existing=True))).scalar_one()


async def owner_email(session, run_id) -> str:
    return (await session.execute(
        text("SELECT u.email FROM users u JOIN runs r ON r.user_id = u.id WHERE r.id = :id"), {"id": run_id})).scalar_one()


async def finish_done(session, store, monkeypatch, **kwargs):
    run_id = await running(session, **kwargs)
    await store_result_files(store)
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")], RESULT)
    await worker.process_run(run_id, "w")
    assert (await run_row(session, run_id)).status == RunStatus.DONE
    return run_id


async def finish_error(session, monkeypatch, *, raw=None, message="IgPhyML exited with status 2", **kwargs):
    run_id = await running(session, **kwargs)
    mock_jobs(monkeypatch, [JobStatus(False, "job-1", "ERROR", message=message, raw=raw)])
    await worker.process_run(run_id, "w")
    assert (await run_row(session, run_id)).status == RunStatus.ERROR
    return run_id


async def expire_in_queue(session, tag="q"):
    user = await make_user(session, tag)
    repo = RunRepository(session)
    run = await repo.create_run(method_id="dowser", params={}, user_id=user.id, dataset_name="clones.tsv")
    await repo.promote_next_for_user(user.id)
    await repo.update(run.id, dispatch_ready_at=datetime.now(timezone.utc) - timedelta(hours=50))
    assert await worker.expire_waiting_runs() == [run.id]
    return run.id


async def make_due(session, run_id):
    await session.execute(update(NotificationOutbox).where(NotificationOutbox.run_id == run_id)
                          .values(next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    await session.commit()


# --------------------------------------------------------------------------- #
# Who is owed an email
# --------------------------------------------------------------------------- #
async def test_a_finished_run_owes_its_owner_one_email(db, store, monkeypatch):
    run_id = await finish_done(db, store, monkeypatch)
    (row,) = await outbox(db, run_id)
    assert (row.kind, row.outcome, row.status, row.attempts) == ("run_finished", "DONE", "PENDING", 0)
    assert row.user_id == (await run_row(db, run_id)).user_id and row.sent_at is None


async def test_a_failed_run_owes_its_owner_one_email(db, monkeypatch):
    run_id = await finish_error(db, monkeypatch)
    (row,) = await outbox(db, run_id)
    assert (row.outcome, row.status) == ("ERROR", "PENDING")


async def test_a_run_that_expired_in_the_queue_owes_an_email_with_its_own_outcome(db):
    run_id = await expire_in_queue(db)
    (row,) = await outbox(db, run_id)
    assert (row.outcome, row.status) == ("QUEUE_TIMEOUT", "PENDING")
    assert (await run_row(db, run_id)).started_at is None


async def test_every_way_the_worker_fails_a_run_queues_the_email(db, store, monkeypatch):
    """Timeout, lost job, missing files, staging error: all go through one door."""
    from apps.api.services.method_jobs_client import MethodJobNotFound
    from apps.api.services.run_staging import StagingError

    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "60")
    timed_out = await running(db, started_seconds_ago=120, tag="t")
    mock_jobs(monkeypatch, [JobStatus(False, "job-1", "CANCELLED")])
    await worker.process_run(timed_out, "w")
    monkeypatch.delenv("RUN_TIMEOUT_SECONDS")

    lost = await running(db, tag="l")
    mock_jobs(monkeypatch, [MethodJobNotFound("gone")])
    await worker.process_run(lost, "w")

    incomplete = await running(db, tag="i")
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")], RESULT)           # files never stored
    await worker.process_run(incomplete, "w")

    staging = await running(db, tag="s")
    await worker._persist_staging_error(staging, StagingError(code="INVALID_INPUT", message="The file is not a valid FASTA."))

    for run_id in (timed_out, lost, incomplete, staging):
        assert (await run_row(db, run_id)).status == RunStatus.ERROR
        (row,) = await outbox(db, run_id)
        assert row.outcome == "ERROR"


async def test_cancelled_runs_owe_no_email_however_they_were_cancelled(db, monkeypatch):
    repo = RunRepository(db)
    # 1) cancelled while waiting in the queue
    user = await make_user(db, "c1")
    queued = await repo.create_run(method_id="gctree", params={}, user_id=user.id)
    await repo.promote_next_for_user(user.id)
    assert await repo.cancel_if_queued(queued.id, "Cancelled by user")
    # 2) cancelled after pickup, before anything was submitted
    before_submit = (await repo.create_run(method_id="gctree", params={}, user_id=(await make_user(db, "c2")).id)).id
    await repo.promote_all_eligible()
    await repo.claim_next_run("w", 60)
    await repo.request_cancel(before_submit)
    monkeypatch.setattr(worker.jobs, "submit_job", AsyncMock())
    await worker.process_run(before_submit, "w")
    # 3) cancelled while its method job was running
    during = await running(db, tag="c3")
    await repo.request_cancel(during)
    mock_jobs(monkeypatch, [JobStatus(False, "job-1", "CANCELLED")])
    await worker.process_run(during, "w")
    # 4) cancelled while the method service was unreachable
    monkeypatch.setenv("WORKER_METHOD_UNREACHABLE_SECONDS", "0")
    gone = await running(db, tag="c4")
    await repo.request_cancel(gone)
    mock_jobs(monkeypatch, [ConnectionError("refused")])
    await worker.process_run(gone, "w")

    for run_id in (queued.id, before_submit, during, gone):
        assert (await run_row(db, run_id)).status == RunStatus.CANCELLED
    assert await outbox(db) == []


async def test_a_run_without_an_owner_owes_no_email(db):
    repo = RunRepository(db)
    orphan = await repo.create_run(method_id="gctree", params={}, user_id=None)
    await repo.fail_run(orphan.id, error="x", message="x")
    assert (await run_row(db, orphan.id)).status == RunStatus.ERROR
    assert await outbox(db) == []


# --------------------------------------------------------------------------- #
# The row belongs to the transaction that ends the run; never two rows
# --------------------------------------------------------------------------- #
async def test_notification_and_final_status_commit_together(db, store, monkeypatch):
    """While DONE is not yet visible, neither is the notification; afterwards both are."""
    run_id = await running(db)
    await store_result_files(store)
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")], RESULT)
    observer = async_sessionmaker(db.bind, expire_on_commit=False)
    seen = {}
    original = RunTreeRepository.replace_for_run

    async def spy(self, rid, trees):
        async with observer() as other:                               # after the status update, before commit
            seen["status"] = (await other.execute(text("SELECT status FROM runs WHERE id = :i"), {"i": rid})).scalar_one()
            seen["rows"] = (await other.execute(
                text("SELECT count(*) FROM notification_outbox WHERE run_id = :i"), {"i": rid})).scalar_one()
        return await original(self, rid, trees)

    monkeypatch.setattr(RunTreeRepository, "replace_for_run", spy)
    await worker.process_run(run_id, "w")
    assert seen == {"status": "RUNNING", "rows": 0}
    assert (await run_row(db, run_id)).status == RunStatus.DONE and len(await outbox(db, run_id)) == 1


async def test_a_rolled_back_completion_leaves_no_done_notification(db, store, monkeypatch):
    """Saving the result fails: the run ends as ERROR and its one email says so."""
    run_id = await running(db)
    await store_result_files(store)
    mock_jobs(monkeypatch, [JobStatus(True, "job-1", "DONE")], RESULT)
    monkeypatch.setattr(RunTreeRepository, "replace_for_run", AsyncMock(side_effect=RuntimeError("disk full")))
    await worker.process_run(run_id, "w")
    assert (await run_row(db, run_id)).status == RunStatus.ERROR
    (row,) = await outbox(db, run_id)
    assert row.outcome == "ERROR"
    assert not (await db.execute(select(RunTree).where(RunTree.run_id == run_id))).scalars().all()


async def test_writing_a_final_status_again_never_queues_a_second_email(db, monkeypatch):
    run_id = await finish_error(db, monkeypatch)
    repo = RunRepository(db)
    await repo.fail_run(run_id, error="again", message="again")
    await repo.set_error(run_id, "and again")
    await repo.set_result(run_id, {"ok": True}, RunStatus.DONE)       # even a different final status
    rows = await outbox(db, run_id)
    assert len(rows) == 1 and rows[0].outcome == "ERROR"              # the first one stands


async def test_the_database_itself_refuses_a_second_row_for_a_run(db, monkeypatch):
    run_id = await finish_error(db, monkeypatch)
    (row,) = await outbox(db, run_id)
    db.add(NotificationOutbox(id=uuid.uuid4(), run_id=run_id, user_id=row.user_id, kind="run_finished", outcome="DONE"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_deleting_a_run_removes_its_pending_notification(db, monkeypatch):
    run_id = await finish_error(db, monkeypatch)
    await db.execute(text("DELETE FROM runs WHERE id = :i"), {"i": run_id})
    await db.commit()
    assert await outbox(db) == []


# --------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------- #
async def test_done_email_is_sent_once_to_the_owner_with_a_link_to_the_results(db, store, monkeypatch, sink):
    run_id = await finish_done(db, store, monkeypatch)
    assert await notifier.deliver_due() == {"sent": 1}
    (mail,) = sink.messages
    assert mail["recipients"] == [await owner_email(db, run_id)]
    assert mail["subject"] == "Your GCtree run has finished" and mail["from"] == "Phylo Runner <phylo@lab.example>"
    assert f"https://phylo.lab.example/dashboard?runId={run_id}" in mail["text"]
    assert "results are ready" in mail["text"] and str(run_id) in mail["html"]
    (row,) = await outbox(db, run_id)
    assert (row.status, row.attempts, row.recipient) == ("SENT", 1, mail["recipients"][0])
    assert row.sent_at is not None and row.locked_until is None and row.last_error is None
    # Asking again sends nothing more.
    assert await notifier.deliver_due() == {} and len(sink.messages) == 1


async def test_error_email_carries_the_code_and_message_the_app_shows(db, monkeypatch, sink):
    raw = {"status": "ERROR", "message": "The job ran out of memory.", "error_code": "OUT_OF_MEMORY"}
    await finish_error(db, monkeypatch, raw=raw, message="The job ran out of memory.")
    assert await notifier.deliver_due() == {"sent": 1}
    (mail,) = sink.messages
    assert mail["subject"] == "Your GCtree run failed"
    assert "Reason: [OUT_OF_MEMORY] The job ran out of memory." in mail["text"]


async def test_queue_timeout_email_explains_that_the_run_never_started(db, sink):
    run_id = await expire_in_queue(db)
    assert await notifier.deliver_due() == {"sent": 1}
    (mail,) = sink.messages
    assert mail["subject"] == "Your Dowser run expired before it could start"
    assert 'run on "clones.tsv" waited too long for a free slot' in mail["text"]
    assert "It never started" in mail["text"] and "please submit the run again" in mail["text"]
    assert "QUEUE_TIMEOUT" not in mail["subject"] and (await outbox(db, run_id))[0].status == "SENT"


async def test_each_terminal_state_gets_exactly_the_email_it_should(db, store, monkeypatch, sink):
    """DONE, ERROR and QUEUE_TIMEOUT: one each. CANCELLED: none."""
    done = await finish_done(db, store, monkeypatch, tag="d")
    failed = await finish_error(db, monkeypatch, tag="e")
    expired = await expire_in_queue(db, "x")
    cancelled = await running(db, tag="c")
    await RunRepository(db).request_cancel(cancelled)
    mock_jobs(monkeypatch, [JobStatus(False, "job-1", "CANCELLED")])
    await worker.process_run(cancelled, "w")

    assert await notifier.deliver_due() == {"sent": 3}
    by_recipient = {m["recipients"][0]: m["subject"] for m in sink.messages}
    assert by_recipient == {
        await owner_email(db, done): "Your GCtree run has finished",
        await owner_email(db, failed): "Your GCtree run failed",
        await owner_email(db, expired): "Your Dowser run expired before it could start",
    }
    assert await owner_email(db, cancelled) not in by_recipient


# --------------------------------------------------------------------------- #
# The mail server cannot change a run; retries are bounded
# --------------------------------------------------------------------------- #
async def test_an_smtp_outage_leaves_the_run_done_and_the_email_is_sent_when_the_server_is_back(db, store, monkeypatch, sink):
    sink.mode = "refuse"                                               # the mail server is down
    run_id = await finish_done(db, store, monkeypatch)
    before = await run_row(db, run_id)
    assert await notifier.deliver_due() == {"retry": 1}
    after = await run_row(db, run_id)
    assert (after.status, after.finished_at, after.result, after.error) == (
        RunStatus.DONE, before.finished_at, before.result, None)       # the run is untouched
    (row,) = await outbox(db, run_id)
    assert (row.status, row.attempts) == ("PENDING", 1) and row.locked_until is None
    assert "mail server" in row.last_error
    assert 55 <= (row.next_attempt_at - datetime.now(timezone.utc)).total_seconds() <= 61

    assert await notifier.deliver_due() == {}                          # not before its time
    sink.mode = "ok"
    assert await notifier.deliver_due() == {}                          # still not due
    await make_due(db, run_id)
    assert await notifier.deliver_due() == {"sent": 1}
    (row,) = await outbox(db, run_id)
    assert (row.status, row.attempts, row.last_error) == ("SENT", 2, None)
    assert len(sink.messages) == 1                                     # one email in total


async def test_retries_stop_after_the_configured_number_of_attempts(db, store, monkeypatch, sink):
    monkeypatch.setenv("NOTIFICATION_MAX_ATTEMPTS", "3")
    sink.mode = "tempfail"
    run_id = await finish_done(db, store, monkeypatch)
    outcomes = []
    for _ in range(5):
        outcomes.append(await notifier.deliver_due())
        await make_due(db, run_id)
    assert outcomes == [{"retry": 1}, {"retry": 1}, {"failed": 1}, {}, {}]
    (row,) = await outbox(db, run_id)
    assert (row.status, row.attempts) == ("FAILED", 3) and "451" in row.last_error
    assert sink.connections == 3 and sink.messages == []               # no fourth attempt, ever
    assert (await run_row(db, run_id)).status == RunStatus.DONE        # and the run is still DONE


def test_waits_between_attempts_grow_and_are_capped(monkeypatch):
    for name in ("NOTIFICATION_RETRY_BASE_SECONDS", "NOTIFICATION_RETRY_MAX_SECONDS", "NOTIFICATION_MAX_ATTEMPTS"):
        monkeypatch.delenv(name, raising=False)
    assert [notifier.retry_delay_seconds(n) for n in range(1, 7)] == [60, 240, 960, 3840, 15360, 21600]
    assert notifier.max_attempts() == 6
    monkeypatch.setenv("NOTIFICATION_RETRY_BASE_SECONDS", "2")
    monkeypatch.setenv("NOTIFICATION_RETRY_MAX_SECONDS", "10")
    assert [notifier.retry_delay_seconds(n) for n in range(1, 5)] == [2, 8, 10, 10]
    monkeypatch.setenv("NOTIFICATION_MAX_ATTEMPTS", "junk")            # a typo keeps the default
    assert notifier.max_attempts() == 6


async def test_a_permanent_refusal_is_not_retried(db, store, monkeypatch, sink):
    sink.mode = "reject"                                               # 550: this recipient is refused for good
    run_id = await finish_done(db, store, monkeypatch)
    assert await notifier.deliver_due() == {"failed": 1}
    (row,) = await outbox(db, run_id)
    assert (row.status, row.attempts) == ("FAILED", 1) and "refused the recipient" in row.last_error
    await make_due(db, run_id)
    assert await notifier.deliver_due() == {} and sink.connections == 1


async def test_without_a_mail_server_notifications_are_skipped_not_kept_for_later(db, store, monkeypatch):
    run_id = await finish_done(db, store, monkeypatch)                 # SMTP_HOST is empty
    assert await notifier.deliver_due() == {"skipped": 1}
    (row,) = await outbox(db, run_id)
    assert row.status == "SKIPPED" and "SMTP_HOST is empty" in row.last_error
    assert (await run_row(db, run_id)).status == RunStatus.DONE
    async with SmtpSink() as late:                                     # the server arrives later
        monkeypatch.setenv("SMTP_HOST", "127.0.0.1"); monkeypatch.setenv("SMTP_PORT", str(late.port))
        monkeypatch.setenv("SMTP_SECURITY", "none"); monkeypatch.setenv("SMTP_FROM", "p@lab.example")
        await make_due(db, run_id)
        assert await notifier.deliver_due() == {} and late.messages == []


async def test_run_notifications_can_be_switched_off(db, store, monkeypatch, sink):
    monkeypatch.setenv("RUN_NOTIFICATIONS_ENABLED", "false")
    run_id = await finish_done(db, store, monkeypatch)
    assert await notifier.deliver_due() == {"skipped": 1}
    assert sink.messages == [] and "switched off" in (await outbox(db, run_id))[0].last_error


async def test_an_invalid_mail_configuration_fails_the_email_not_the_run(db, store, monkeypatch, sink):
    monkeypatch.setenv("SMTP_FROM", "")                                # misconfigured
    monkeypatch.setenv("NOTIFICATION_MAX_ATTEMPTS", "1")
    run_id = await finish_done(db, store, monkeypatch)
    assert await notifier.deliver_due() == {"failed": 1}
    (row,) = await outbox(db, run_id)
    assert row.status == "FAILED" and "SMTP_FROM is required" in row.last_error
    assert (await run_row(db, run_id)).status == RunStatus.DONE


# --------------------------------------------------------------------------- #
# No duplicates from concurrency, restarts or late answers
# --------------------------------------------------------------------------- #
async def test_two_senders_at_once_send_each_email_once(db, store, monkeypatch, sink):
    for i in range(6):
        await finish_error(db, monkeypatch, tag=f"p{i}")
    results = await asyncio.gather(notifier.deliver_due(limit=4), notifier.deliver_due(limit=4), notifier.deliver_due(limit=4))
    assert sum(r.get("sent", 0) for r in results) == 6
    recipients = [m["recipients"][0] for m in sink.messages]
    assert len(recipients) == 6 and len(set(recipients)) == 6
    assert {r.status for r in await outbox(db)} == {"SENT"}


async def test_a_row_in_another_senders_hands_is_left_alone_until_its_lease_ends(db, monkeypatch, sink):
    run_id = await finish_error(db, monkeypatch)
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as s:
        (held,) = await NotificationRepository(s).claim_due(limit=10, lease_seconds=120)
    assert held.run_id == run_id
    assert await notifier.deliver_due() == {} and sink.messages == []   # someone else is on it
    # That sender died: once its lease is over, the row is taken up again.
    await db.execute(update(NotificationOutbox).where(NotificationOutbox.run_id == run_id)
                     .values(locked_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
    await db.commit()
    assert await notifier.deliver_due() == {"sent": 1} and len(sink.messages) == 1


async def test_a_late_answer_does_not_overwrite_a_settled_row(db, monkeypatch):
    run_id = await finish_error(db, monkeypatch)
    (row,) = await outbox(db, run_id)
    repo = NotificationRepository(db)
    await repo.mark_failed(row.id, attempts=3, error="given up")
    await repo.mark_retry(row.id, attempts=4, next_attempt_at=datetime.now(timezone.utc), error="late")
    await repo.mark_sent(row.id, recipient="x@y.example", attempts=4)
    (row,) = await outbox(db, run_id)
    assert (row.status, row.attempts, row.last_error, row.sent_at) == ("FAILED", 3, "given up", None)


async def test_a_notification_for_a_vanished_owner_is_skipped(db, monkeypatch, sink):
    run_id = await finish_error(db, monkeypatch)
    await db.execute(text("UPDATE users SET email = '' WHERE id = (SELECT user_id FROM runs WHERE id = :i)"), {"i": run_id})
    await db.commit()
    assert await notifier.deliver_due() == {"skipped": 1} and sink.messages == []


# --------------------------------------------------------------------------- #
# Independence from run processing
# --------------------------------------------------------------------------- #
async def test_a_mail_server_that_hangs_does_not_slow_down_runs(db, store, monkeypatch, sink):
    """Delivery is its own task: while it waits on a silent mail server, runs finish as usual."""
    monkeypatch.setenv("SMTP_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("NOTIFICATION_POLL_SECONDS", "0.05")
    sink.mode = "hang"
    first = await finish_error(db, monkeypatch, tag="h1")              # its email will hang
    stop = asyncio.Event()
    loop_task = asyncio.create_task(notifier.notification_loop(stop))
    await asyncio.sleep(0.3)                                           # the sender is now stuck in SMTP
    assert sink.connections >= 1

    started = time.monotonic()
    second = await finish_done(db, store, monkeypatch, tag="h2")       # a whole run, start to DONE
    assert time.monotonic() - started < 1.5                            # not held up by the 2 s SMTP timeout
    assert (await run_row(db, second)).status == RunStatus.DONE

    await asyncio.sleep(2.3)                                           # let the hanging attempt time out
    stop.set()
    await asyncio.wait_for(loop_task, timeout=10)
    (row,) = await outbox(db, first)
    assert row.status == "PENDING" and row.attempts >= 1 and "did not answer in time" in row.last_error
    assert (await run_row(db, first)).status == RunStatus.ERROR        # unchanged by any of it


async def test_the_delivery_loop_survives_its_own_failures(db, monkeypatch):
    monkeypatch.setenv("NOTIFICATION_POLL_SECONDS", "0.05")
    calls = {"n": 0}
    stop = asyncio.Event()

    async def flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] >= 3:
            stop.set()
        raise RuntimeError("database is away")

    monkeypatch.setattr(notifier, "deliver_due", flaky)
    await asyncio.wait_for(notifier.notification_loop(stop), timeout=5)   # returns normally, did not raise
    assert calls["n"] == 3


async def test_one_unsendable_row_does_not_block_the_others(db, monkeypatch, sink):
    bad = await finish_error(db, monkeypatch, tag="b")
    good = await finish_error(db, monkeypatch, tag="g")
    original = notifier.build_run_email

    def explode_for_bad(notification, run):
        if run.id == bad:
            raise RuntimeError("template bug")
        return original(notification, run)

    monkeypatch.setattr(notifier, "build_run_email", explode_for_bad)
    assert await notifier.deliver_due() == {"error": 1, "sent": 1}
    assert [m["recipients"][0] for m in sink.messages] == [await owner_email(db, good)]
    assert (await outbox(db, bad))[0].status == "PENDING"              # kept; retried when its lease ends
