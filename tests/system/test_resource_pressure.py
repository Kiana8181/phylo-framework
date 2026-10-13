"""The system under pressure, on the real stack.

Requires the stack ``npm run test:system`` starts: the isolated ``phylo-tests``
project with container limits and restart policies as in production. Nothing
is mocked. Each test puts the stack into one of the situations a shared server
produces (a full method service, a memory limit reached, a container that
dies, a worker that restarts, a mail server that is away) and checks that the
outcome is correct, visible to the user, and that the system serves the next
run afterwards.

These tests stop, kill and reconfigure containers of that one project. They
never touch anything else on the machine, and they are not for a production
server.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from tests.system.helpers import (METHOD_PORTS, TERMINAL, capacity, error_code, eventually, job_status, run_row, sql)

pytestmark = pytest.mark.system

# The sample needs about this much in an R job; a limit this far below
# "service + job" guarantees the job cannot fit (measured: idle service
# ~860 MiB, job ~950 MiB under emulation, a few hundred MiB less natively).
TIGHT_R_LIMIT = "1400m"
ADMIT_ANYWAY = {"METHOD_BASELINE_MEMORY_MB": "100", "METHOD_JOB_MEMORY_MB": "100", "METHOD_MEMORY_HEADROOM_PERCENT": "0"}


async def running_job(user, run_id: str, method: str, seconds: float = 120) -> dict:
    """The run's job at its method service, once its process has started."""
    async def started():
        row = await run_row(run_id)
        if not row["method_job_id"]:
            return None
        status = await job_status(method, row["method_job_id"])
        return {**status, "job_id": row["method_job_id"]} if status and status.get("pid") else None
    return await eventually(started, seconds, f"the {method} job of run {run_id} to start", every=0.2)


# --------------------------------------------------------------------------- #
# 1. Several users at once
# --------------------------------------------------------------------------- #
async def test_several_users_submit_at_once_and_every_run_finishes_in_its_owners_account(stack, users):
    people = await users(4)
    methods = ["gctree", "clonaltree", "dowser", "brepphylo"]
    # Eight runs within the same moment: every user two, spread over all four methods.
    submitted = await asyncio.gather(*[
        user.start(methods[(index + offset) % 4]) for index, user in enumerate(people) for offset in (0, 1)])
    by_user = {user: submitted[2 * index: 2 * index + 2] for index, user in enumerate(people)}

    over_capacity = []

    async def watch():
        while True:
            for method in METHOD_PORTS:
                report = await capacity(method)
                if report["running_jobs"] > report["job_slots"]:
                    over_capacity.append((method, report["running_jobs"], report["job_slots"]))
            await asyncio.sleep(0.3)

    watcher = asyncio.create_task(watch())
    try:
        finals = await asyncio.gather(*[user.wait(run_id, 420) for user, ids in by_user.items() for run_id in ids])
    finally:
        watcher.cancel()
    assert [f["status"] for f in finals] == ["DONE"] * 8, [(f["status"], f.get("message")) for f in finals]
    assert over_capacity == []                                              # no service ever ran more than it has room for
    for user, ids in by_user.items():
        listed = await user.runs()
        assert sorted(r["id"] for r in listed) == sorted(ids)                # own runs, all of them, nobody else's
        other = next(u for u in people if u is not user)
        assert (await other.api.get(f"/runs/{ids[0]}/status")).status_code in (403, 404)
        # A user's second run waited for the first: one at a time per user.
        first, second = (await run_row(ids[0]), await run_row(ids[1]))
        earlier, later = sorted((first, second), key=lambda r: r["started_at"])
        assert later["started_at"] >= earlier["finished_at"]


# --------------------------------------------------------------------------- #
# 2. A method at its CPU limit
# --------------------------------------------------------------------------- #
async def test_a_job_that_asks_for_64_cores_runs_inside_the_containers_cpu_limit(stack, users):
    user = await users()
    report = await capacity("dowser")
    assert report["cpus"] == 1 and report["threads_per_job"] == 1           # derived from the container's limit
    run_id = await user.start("dowser", nproc=64)
    await running_job(user, run_id, "dowser")
    samples = []
    while (await user.status(run_id))["status"] not in TERMINAL:
        samples.append(stack.cpu_percent("dowser"))
    final = await user.status(run_id)
    assert final["status"] == "DONE", final.get("message")
    # One CPU allowed: the container never used meaningfully more (docker's
    # sampling is not exact, hence the margin), however many cores were asked for.
    assert samples and max(samples) <= 125, samples
    result = (await user.api.get(f"/runs/{run_id}/result")).json()
    logged = [entry for entry in result.get("data", result).get("logs", []) if entry.get("step") == "dowser.params.nproc"]
    assert logged and "requested=64, effective=1" in str(logged[0]), logged   # and the result says what really happened


# --------------------------------------------------------------------------- #
# 3. Memory
# --------------------------------------------------------------------------- #
async def test_a_job_the_service_can_never_hold_is_refused_with_the_reason(stack, users):
    user = await users()
    stack.reconfigure("gctree", environment={"METHOD_JOB_MEMORY_MB": "4000"})    # one job needs more than the container has
    await stack.ready("gctree")
    report = await capacity("gctree")
    assert report["job_slots"] == 0 and report["accepting"] is False
    final = await user.wait(await user.start("gctree"), 120)
    assert final["status"] == "ERROR"
    assert "memory" in final["message"].lower() and "gctree" in final["message"].lower(), final["message"]
    row = await run_row(final.get("run_id") or (await user.runs())[0]["id"])
    assert row["method_job_id"] is None                                     # it never started
    stack.restore()
    await stack.ready("gctree")
    assert (await user.wait(await user.start("gctree"), 300))["status"] == "DONE"


@pytest.mark.parametrize("method", ["dowser", "brepphylo"])
async def test_a_job_that_needs_too_much_memory_is_stopped_by_the_kernel_and_the_service_survives(stack, users, method):
    """A real out-of-memory kill, not a simulated one: the container's limit is
    set below what service + job need, and the job is submitted as usual."""
    user = await users()
    stack.reconfigure(method, mem_limit=TIGHT_R_LIMIT, memswap_limit=TIGHT_R_LIMIT, environment=ADMIT_ANYWAY)
    await stack.ready(method)
    before = stack.state(method)
    assert stack.memory_events(method)["oom_kill"] == 0

    run_id = await user.start(method)
    job = await running_job(user, run_id, method)
    assert stack.exec(method, "cat", f"/proc/{job['pid']}/oom_score_adj").strip() == "800"    # the job volunteers
    main = next(p for p in stack.processes(method) if "plumber" in p["args"] and "job_runner" not in p["args"])
    assert stack.exec(method, "cat", f"/proc/{main['pid']}/oom_score_adj").strip() == "0"     # the service does not
    final = await user.wait(run_id, 300)

    assert final["status"] == "ERROR" and error_code(final) == "OUT_OF_MEMORY", (final["status"], final.get("message"))
    assert "ran out of memory" in final["message"] and "1400 MiB" in final["message"]
    assert "smaller dataset" in final["message"]                             # tells the user what to do
    after = stack.state(method)
    assert after["restarts"] == before["restarts"] and after["started"] == before["started"]  # the service kept running
    assert stack.memory_events(method)["oom_kill"] >= 1                      # the kernel did it
    report = await capacity(method)
    assert report["running_jobs"] == 0 and report["free_slots"] == report["job_slots"] == 1   # the slot is free again
    assert not [p for p in stack.processes(method) if "job_runner" in p["args"]]
    # The run keeps a downloadable log of what the job got done before it was stopped.
    logs = [a for a in await user.artifacts(run_id) if a["filename"] == "job.log"]
    assert len(logs) == 1 and (await user.api.get(logs[0]["download_url"])).status_code == 200

    stack.restore()                                                          # normal limits again
    await stack.ready(method)
    assert (await user.wait(await user.start(method), 300))["status"] == "DONE"


@pytest.mark.parametrize("method", ["dowser", "brepphylo"])
async def test_when_the_kernel_stops_the_service_itself_the_container_restarts_and_serves_again(stack, users, method):
    """The other outcome of a real out-of-memory kill. With jobs no longer
    volunteering (as before the fix, or with METHOD_JOB_OOM_SCORE_ADJ=0) the
    kernel picks the largest process, which is the service while a job is
    still growing."""
    user = await users()
    stack.reconfigure(method, mem_limit=TIGHT_R_LIMIT, memswap_limit=TIGHT_R_LIMIT,
                      environment={**ADMIT_ANYWAY, "METHOD_JOB_OOM_SCORE_ADJ": "0"})
    await stack.ready(method)
    before = stack.state(method)
    run_id = await user.start(method)
    final = await user.wait(run_id, 300)
    assert final["status"] == "ERROR" and error_code(final) in ("METHOD_RESTARTED", "METHOD_UNREACHABLE"), (
        error_code(final), final.get("message"))
    assert "submit it again" in final["message"] or "not reachable" in final["message"].lower()

    async def restarted():
        state = stack.state(method)
        return state if state["restarts"] > before["restarts"] and state["status"] == "running" else None
    await eventually(restarted, 120, f"{method} to be restarted by its restart policy")
    await stack.ready(method)
    stack.restore()
    await stack.ready(method)
    assert (await user.wait(await user.start(method), 300))["status"] == "DONE"


# --------------------------------------------------------------------------- #
# 4. No free capacity
# --------------------------------------------------------------------------- #
async def test_runs_wait_visibly_while_a_method_is_full_and_then_take_their_turn(stack, users):
    people = await users(3)
    assert (await capacity("dowser"))["job_slots"] == 1
    run_ids = [await user.start("dowser") for user in people]
    seen_waiting, most_running = set(), 0
    statuses = {}
    deadline = time.monotonic() + 420
    while time.monotonic() < deadline:
        statuses = {run_id: await user.status(run_id) for user, run_id in zip(people, run_ids)}
        most_running = max(most_running, (await capacity("dowser"))["running_jobs"])
        for run_id, status in statuses.items():
            if status.get("stage") == "WAITING_FOR_CAPACITY":
                seen_waiting.add(run_id)
                assert status["status"] in ("QUEUED", "RUNNING", "PENDING")
                assert "dowser" in (status.get("stage_message") or status.get("message") or "").lower()   # says why
        if all(s["status"] in TERMINAL for s in statuses.values()):
            break
        await asyncio.sleep(0.3)
    assert [s["status"] for s in statuses.values()] == ["DONE"] * 3, [s.get("message") for s in statuses.values()]
    assert len(seen_waiting) >= 2                                           # the two that had no slot said so
    assert most_running == 1                                                # and the service never ran two
    rows = sorted([await run_row(r) for r in run_ids], key=lambda r: r["started_at"])
    assert rows[1]["started_at"] >= rows[0]["finished_at"] and rows[2]["started_at"] >= rows[1]["finished_at"]


# --------------------------------------------------------------------------- #
# 5. A job over its time limit (and what is kept of it)
# --------------------------------------------------------------------------- #
async def test_a_run_over_its_time_limit_is_stopped_keeps_a_log_and_the_log_expires_with_it(stack, users):
    user = await users()
    stack.reconfigure("worker", environment={"RUN_TIMEOUT_SECONDS_DOWSER": "5"})
    await stack.ready("worker")
    run_id = await user.start("dowser")
    final = await user.wait(run_id, 180)
    assert final["status"] == "ERROR" and error_code(final) == "TIMEOUT", final.get("message")
    assert "maximum run time of 5 seconds" in final["message"]

    async def nothing_left_running():
        report = await capacity("dowser")
        jobs = [p for p in stack.processes("dowser") if "job_runner" in p["args"]]
        return report["running_jobs"] == 0 and not jobs
    await eventually(nothing_left_running, 60, "the timed-out job and its tools to be gone")

    # A downloadable, size-limited log, registered like any other file of the run.
    async def log_kept():
        return [a for a in await user.artifacts(run_id) if a["filename"] == "job.log"]
    (log,) = await eventually(log_kept, 30, "the log of the timed-out run")
    body = await user.api.get(log["download_url"])
    assert body.status_code == 200 and len(body.content) == log["size_bytes"] > 0
    assert log["size_bytes"] <= 5 * 1024 * 1024 + 512                        # METHOD_JOB_LOG_MAX_MB
    key = (await sql("SELECT object_key FROM run_artifacts WHERE run_id = $1", run_id))[0]["object_key"]
    assert key.startswith(f"artifacts/{run_id}/")
    # The service keeps nothing of the job.
    assert await job_status("dowser", (await run_row(run_id))["method_job_id"]) is None

    # Other methods are not affected, and the same user can go on.
    assert (await user.wait(await user.start("gctree"), 300))["status"] == "DONE"

    # The log expires with the run: after its date it is gone from the store and answers 410.
    assert (await user.status(run_id))["expires_at"]
    await sql("UPDATE runs SET expires_at = now() - interval '1 minute' WHERE id = $1", run_id)
    async def expired():
        return (await user.status(run_id))["results_expired"]
    await eventually(expired, 60, "the timed-out run's log to expire")
    gone = await user.api.get(log["download_url"])
    assert gone.status_code == 410 and gone.json()["data"]["code"] == "RESULT_EXPIRED"
    assert (await user.status(run_id))["status"] == "ERROR"                  # the run itself stays in the history


async def test_a_job_whose_process_disappears_is_reported_as_lost_with_its_log(stack, users):
    user = await users()
    run_id = await user.start("brepphylo")
    job = await running_job(user, run_id, "brepphylo")
    stack.exec("brepphylo", "kill", "-9", str(job["pid"]))
    final = await user.wait(run_id, 180)
    assert final["status"] == "ERROR" and error_code(final) == "JOB_PROCESS_LOST", (error_code(final), final.get("message"))
    logs = [a for a in await user.artifacts(run_id) if a["filename"] == "job.log"]
    assert len(logs) == 1 and (await user.api.get(logs[0]["download_url"])).status_code == 200
    report = await capacity("brepphylo")
    assert report["running_jobs"] == 0 and report["accepting"]
    assert (await user.wait(await user.start("brepphylo"), 300))["status"] == "DONE"


async def test_an_input_that_takes_too_long_to_prepare_ends_the_run_and_leaves_nothing_behind(stack, users):
    user = await users()
    stack.reconfigure("worker", environment={"RUN_STAGING_TIMEOUT_SECONDS": "0.001"})   # no real preparation is this fast
    await stack.ready("worker")
    run_id = await user.start("gctree")
    final = await user.wait(run_id, 120)
    assert final["status"] == "ERROR" and error_code(final) == "STAGING_TIMEOUT", final.get("message")
    assert "was not started" in final["message"]
    assert (await run_row(run_id))["method_job_id"] is None                  # the method never saw it
    left = stack.exec("worker", "sh", "-c", f"ls -A /runtime/storage/runs/{run_id} 2>/dev/null | wc -l").strip()
    assert left == "0"                                                       # no work directory left on disk
    stack.restore()
    await stack.ready("worker")
    assert (await user.wait(await user.start("gctree"), 300))["status"] == "DONE"       # the user's next run starts


# --------------------------------------------------------------------------- #
# 6. A method container dies
# --------------------------------------------------------------------------- #
async def test_a_method_container_that_dies_fails_only_its_own_run_and_comes_back(stack, users):
    victim, bystander = await users(2)
    before = stack.state("brepphylo")
    doomed = await victim.start("brepphylo")
    await running_job(victim, doomed, "brepphylo")
    untouched = await bystander.start("dowser")
    stack.crash("brepphylo")                                                # the service process is killed outright

    final = await victim.wait(doomed, 400)
    assert final["status"] == "ERROR" and error_code(final) in ("METHOD_RESTARTED", "METHOD_UNREACHABLE"), (
        error_code(final), final.get("message"))
    assert (await bystander.wait(untouched, 300))["status"] == "DONE"        # another method, another user: unaffected

    async def back():
        state = stack.state("brepphylo")
        return state["status"] == "running" and state["restarts"] > before["restarts"]
    await eventually(back, 120, "brepphylo to be restarted")
    await stack.ready("brepphylo")
    report = await capacity("brepphylo")
    assert report["running_jobs"] == 0 and report["accepting"]              # it does not think the lost job still runs
    # Not repeated automatically; submitted again by the user, it completes.
    assert len(await victim.runs()) == 1
    assert (await victim.wait(await victim.start("brepphylo"), 300))["status"] == "DONE"


# --------------------------------------------------------------------------- #
# 7. The worker, the API and the database restart during a run
# --------------------------------------------------------------------------- #
async def test_a_worker_restart_does_not_lose_or_repeat_a_running_job(stack, users):
    user = await users()
    run_id = await user.start("dowser")
    job = await running_job(user, run_id, "dowser")
    stack.restart("worker")
    await stack.ready("worker")
    final = await user.wait(run_id, 300)
    assert final["status"] == "DONE", final.get("message")
    row = await run_row(run_id)
    assert row["method_job_id"] == job["job_id"]                             # the same job was followed to its end
    assert len({a["filename"] for a in await user.artifacts(run_id)}) == len(await user.artifacts(run_id))   # no duplicates
    assert (await capacity("dowser"))["running_jobs"] == 0

    async def one_mail():
        return await user.mail("has finished")
    assert len(await eventually(one_mail, 60, "the notification")) == 1
    await asyncio.sleep(5)
    assert len(await user.mail("has finished")) == 1                         # told once, not once per worker


async def test_an_api_restart_does_not_disturb_a_running_job(stack, users):
    user = await users()
    run_id = await user.start("brepphylo")
    await running_job(user, run_id, "brepphylo")
    stack.restart("api")
    await stack.ready("api")
    final = await user.wait(run_id, 300)                                     # the same session keeps working
    assert final["status"] == "DONE", final.get("message")
    assert (await user.api.get(f"/runs/{run_id}/result")).status_code == 200


async def test_a_database_restart_during_a_run_is_survived(stack, users):
    user = await users()
    run_id = await user.start("dowser")
    job = await running_job(user, run_id, "dowser")
    stack.restart("postgres")
    final = await user.wait(run_id, 400)
    # The job does not need the database and is not touched by its absence;
    # the worker waits for it and follows the same job to its end.
    assert final["status"] == "DONE", (final["status"], final.get("message"))
    assert (await run_row(run_id))["method_job_id"] == job["job_id"]
    assert "database is back" in stack.logs("worker", tail=400)
    await stack.ready("api", "worker")
    assert (await capacity("dowser"))["running_jobs"] == 0
    assert (await user.wait(await user.start("gctree"), 300))["status"] == "DONE"       # and everything works again


# --------------------------------------------------------------------------- #
# 8. Cancelling a queued run
# --------------------------------------------------------------------------- #
async def test_cancelling_a_queued_run_costs_nothing_and_sends_nothing(stack, users):
    user = await users()
    active = await user.start("dowser")
    queued = await user.start("gctree")                                      # waits behind the user's own active run
    assert (await user.quota())["hourly"]["used"] == 2
    cancelled = await user.api.post(f"/runs/{queued}/cancel-queued")
    assert cancelled.status_code == 200, cancelled.text
    status = await user.status(queued)
    assert status["status"] == "CANCELLED"
    row = await run_row(queued)
    assert row["started_at"] is None and row["method_job_id"] is None        # it never ran
    assert (await user.quota())["hourly"]["used"] == 1                       # and does not count against the hour
    assert (await user.wait(active, 300))["status"] == "DONE"                # the active run is untouched

    async def finished_mail():
        return await user.mail("has finished")
    assert len(await eventually(finished_mail, 60, "the mail for the finished run")) == 1
    await asyncio.sleep(4)
    subjects = [m["subject"] for m in await user.mail() if "Confirm your" not in m["subject"]]
    assert len(subjects) == 1, subjects                                      # nothing was sent about the cancelled one
    assert await sql("SELECT 1 FROM notification_outbox WHERE run_id = $1", queued) == []


# --------------------------------------------------------------------------- #
# 9. The hourly quota
# --------------------------------------------------------------------------- #
async def test_the_sixth_run_within_an_hour_is_refused_and_says_when_to_come_back(stack, users):
    user = await users()
    run_ids = [await user.start("dowser") for _ in range(5)]                 # one runs, four wait
    refused = await user.submit("dowser")
    assert refused.status_code == 429
    body = refused.json()
    assert body["data"]["code"] == "RUN_QUOTA_EXCEEDED" and "5 runs per hour" in body["message"]
    assert 3500 < int(refused.headers["retry-after"]) <= 3600
    quota = await user.quota()
    assert quota["can_submit"] is False and quota["blocked_by"] == "RUN_QUOTA_EXCEEDED"
    assert quota["hourly"]["used"] == 5 and quota["hourly"]["remaining"] == 0 and quota["hourly"]["reset_at"]
    assert len(await user.runs()) == 5                                       # the refused one was not created
    # Another user is not affected by this one's limit.
    other = await users()
    assert (await other.submit("gctree")).status_code == 200
    # Giving back runs that never started gives back the allowance.
    for run_id in run_ids[1:]:
        assert (await user.api.post(f"/runs/{run_id}/cancel-queued")).status_code == 200
    quota = await user.quota()
    assert quota["hourly"]["used"] == 1 and quota["can_submit"] is True
    await user.api.post(f"/runs/{run_ids[0]}/cancel")
    await user.wait(run_ids[0], 120)


# --------------------------------------------------------------------------- #
# 10. The mail server is away
# --------------------------------------------------------------------------- #
async def test_a_mail_outage_changes_no_run_and_the_notification_arrives_later_once(stack, users):
    user = await users()                                                    # registered while mail still works
    stack.stop("mail")
    run_id = await user.start("gctree")
    final = await user.wait(run_id, 300)
    assert final["status"] == "DONE", final.get("message")                   # the run does not care
    assert (await user.api.get(f"/runs/{run_id}/result")).status_code == 200

    async def tried():
        rows = await sql("SELECT status, attempts, last_error FROM notification_outbox WHERE run_id = $1", run_id)
        return rows[0] if rows and rows[0]["attempts"] >= 2 else None
    waiting = await eventually(tried, 60, "delivery attempts while the mail server is away")
    assert waiting["status"] == "PENDING" and waiting["last_error"]          # kept, with the reason, to try again
    assert (await user.status(run_id))["status"] == "DONE"                   # still

    stack.start("mail")

    async def delivered():
        rows = await sql("SELECT status FROM notification_outbox WHERE run_id = $1", run_id)
        return rows and rows[0]["status"] == "SENT"
    await eventually(delivered, 90, "the notification to be delivered once the mail server is back")
    mails = await user.mail("has finished")                                  # the restarted test server starts empty
    assert len(mails) == 1 and run_id in mails[0]["text"]
    await asyncio.sleep(6)
    assert len(await user.mail("has finished")) == 1                         # once
