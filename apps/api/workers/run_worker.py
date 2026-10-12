"""DB-backed run worker / orchestrator.

A standalone process (separate from the API) that:
  - claims QUEUED runs atomically (SELECT ... FOR UPDATE SKIP LOCKED + lease),
    but only for methods whose service reports a free job slot, so a run that
    cannot start yet waits in the queue instead of oversubscribing a container,
  - stages/preprocesses the input,
  - submits an async job to the method service (/jobs),
  - polls the method job status (stage-based, no fake timers),
  - propagates cancellation to the method service,
  - enforces the run time limit and the queue-wait limit (workers/limits.py),
  - fails a run whose method job was lost or whose service stays unreachable,
  - confirms every artifact is in the object store before a run becomes DONE,
  - persists the final result/error using the existing contracts,
  - resumes orphaned runs after a lease expires,
  - keeps a log for failed jobs and tells the method service to forget a job
    once its result is stored,
  - delivers run notifications from the outbox (workers/notifier.py) and
    removes results past their date (workers/retention.py), as separate tasks
    that cannot affect run processing.

Run with:  python -m apps.api.workers.run_worker
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import sys
import time
import traceback
from typing import Any, Optional
from uuid import UUID

import httpx

from apps.api.database.base import AsyncSessionLocal
from apps.api.database.models import ArtifactKind, RunStatus
from apps.api.repositories.artifact_repository import ArtifactRepository
from apps.api.repositories.file_repository import FileRepository
from apps.api.repositories.run_repository import RunRepository
from apps.api.repositories.run_tree_repository import RunTreeRepository
from apps.api.services import method_jobs_client as jobs
from apps.api.services.artifact_service import (
    ArtifactService,
    ManifestError,
    parse_manifest,
)
from apps.api.services.artifact_verification import (
    ArtifactStoreUnavailable,
    verify_artifacts,
)
from apps.api.services.completion import (
    CODE_INCOMPLETE_RESULT,
    LOG_MISSING_WARNING,
    NO_EXECUTION_RECORD,
    has_execution_log,
    has_step_log,
    missing_requirements,
)
from apps.api.logging_setup import configure_logging
from apps.api.preprocess.prepare_input import PREPROCESS_LOG_PREFIX
from apps.api.security.errors import log_internal_error
from apps.api.security.production_config import (
    InsecureConfigurationError,
    enforce_production_config,
)
from apps.api.services.run_staging import (
    StagingError,
    cleanup_workspace,
    normalize_failed_result_payload,
    prepare_method_input,
    run_work_root,
)
from apps.api.services.stage_map import progress_for_stage
from apps.api.services.tree_contract import assemble_unified_tree_result
from apps.api.services.version_info import attach_version_info
from apps.api.storage import get_artifact_storage, get_storage
from apps.api.utils.datetime_util import utc_now
from apps.api.workers import limits
from apps.api.workers.capacity import CapacityTracker
from apps.api.workers.notifier import notification_loop
from apps.api.workers.retention import retention_loop

POLL_INTERVAL = float(os.getenv("WORKER_POLL_INTERVAL", "3"))
METHOD_POLL_INTERVAL = float(os.getenv("WORKER_METHOD_POLL_INTERVAL", "10"))
LEASE_SECONDS = int(os.getenv("WORKER_LEASE_SECONDS", "180"))
CAPACITY_REFRESH_SECONDS = float(os.getenv("WORKER_CAPACITY_REFRESH_SECONDS", "5"))
# How often a finished job's result is asked for again when the fetch fails.
RESULT_FETCH_ATTEMPTS = max(1, int(os.getenv("WORKER_RESULT_FETCH_ATTEMPTS", "3")))

# Codes stored with a failed run (shown to the user as "[CODE] message").
CODE_TIMEOUT = "TIMEOUT"
CODE_QUEUE_TIMEOUT = "QUEUE_TIMEOUT"
CODE_METHOD_RESTARTED = "METHOD_RESTARTED"
CODE_METHOD_UNREACHABLE = "METHOD_UNREACHABLE"
CODE_RESULT_UNAVAILABLE = "RESULT_UNAVAILABLE"
CODE_ARTIFACT_UPLOAD_FAILED = "ARTIFACT_UPLOAD_FAILED"
CODE_ARTIFACTS_MISSING = "ARTIFACTS_MISSING"
CODE_ARTIFACT_STORE_UNAVAILABLE = "ARTIFACT_STORE_UNAVAILABLE"
CODE_STAGING_TIMEOUT = "STAGING_TIMEOUT"
# Used only while no method service has reported its capacity yet.
FALLBACK_CONCURRENT_RUNS = 1


def configured_max_concurrent() -> Optional[int]:
    """Operator override for how many runs this worker drives at once.

    Unset or empty (the default) means: derive it from the method services, as
    the sum of the job slots they report. The services size those slots from
    their own CPU and memory limits, so there is no fixed number to maintain.
    """
    raw = (os.getenv("WORKER_MAX_CONCURRENT_RUNS") or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def max_concurrent_runs(tracker: CapacityTracker) -> int:
    configured = configured_max_concurrent()
    if configured is not None:
        return configured
    return max(FALLBACK_CONCURRENT_RUNS, tracker.total_slots())

_storage = None
_artifact_storage = None


def _storage_backend():
    """Lazily build the dataset storage client (avoids connecting at import time)."""
    global _storage
    if _storage is None:
        _storage = get_storage()
    return _storage


def _artifact_storage_backend():
    """Lazily build the artifact-bucket client used to verify uploads."""
    global _artifact_storage
    if _artifact_storage is None:
        _artifact_storage = get_artifact_storage()
    return _artifact_storage


def _log(msg: str, **fields: Any) -> None:
    suffix = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    print(f"[run_worker] {msg} {suffix}".rstrip(), flush=True)


def _normalize_method_poll_stage(
    method_status: str,
    stage: str | None,
    progress: int | None,
) -> tuple[str, int | None]:
    """Never regress a claimed run back to QUEUED in the API stage column."""
    normalized = stage or "RUNNING_METHOD"
    if normalized == "QUEUED" or method_status == "QUEUED":
        normalized = "RUNNING_METHOD"
    mapped = progress_for_stage(normalized)
    if progress is None or progress == 0:
        progress = mapped
    elif mapped is not None:
        progress = max(progress, mapped)
    return normalized, progress


async def _resolve_input_storage_path(run, file_repo: FileRepository) -> Optional[str]:
    if run.input_file_id:
        f = await file_repo.get_by_id(run.input_file_id)
        if f:
            return f.storage_path
    files = await file_repo.get_by_run(run.id)
    if files:
        return files[0].storage_path
    return None


def _merge_preprocess_logs(
    unified_result: dict[str, Any], run: Any
) -> dict[str, Any]:
    """Prepend the run's already-stored `preprocess.*` entries to its logs.

    Staging writes the preprocessing trace into `result["logs"]` before the
    method job is submitted; the unified record built from the service response
    knows nothing about it. Runs staged before this change carry no such
    entries, and are returned unchanged.
    """
    stored = getattr(run, "result", None)
    if not isinstance(stored, dict):
        return unified_result
    preprocess_logs = [
        entry
        for entry in (stored.get("logs") or [])
        if isinstance(entry, dict)
        and str(entry.get("step", "")).startswith(f"{PREPROCESS_LOG_PREFIX}.")
    ]
    if not preprocess_logs:
        return unified_result

    merged = dict(unified_result)
    service_logs = merged.get("logs")
    merged["logs"] = preprocess_logs + (
        list(service_logs) if isinstance(service_logs, list) else []
    )
    return merged


async def _fail(
    run_id: UUID,
    code: str,
    message: str,
    *,
    step: str,
    details: Optional[dict[str, Any]] = None,
    extra_logs: Optional[list[dict[str, Any]]] = None,
) -> None:
    """Fail a run for a reason the worker itself established."""
    await _persist_error(
        run_id,
        error_message=message,
        code=code,
        details=details,
        result_payload={
            "ok": False,
            "error": message,
            "error_code": code,
            "logs": [{"step": step, "ok": False, "out": message}, *(extra_logs or [])],
        },
    )


def _reported_upload_failures(result: dict[str, Any]) -> list[str]:
    """Names of artifacts the method service says it could not upload."""
    failures = result.get("artifact_upload_failures")
    if not isinstance(failures, list):
        return []
    names = []
    for item in failures:
        if isinstance(item, dict):
            names.append(str(item.get("filename") or item.get("path") or "artifact"))
        elif item:
            names.append(str(item))
    return names


async def _keep_verified_logs(
    run_id: UUID, artifact_rows: list[dict[str, Any]], verified_keys: set[str]
) -> None:
    """A failed run keeps its logs. Register only the ones known to be stored."""
    log_rows = [
        row for row in artifact_rows
        if row.get("artifact_kind") == ArtifactKind.LOG and row.get("object_key") in verified_keys
    ]
    if not log_rows:
        return
    try:
        async with AsyncSessionLocal() as db:
            await ArtifactRepository(db).replace_for_run(run_id, log_rows)
            await db.commit()
    except Exception:  # noqa: BLE001 - never let log retention mask the real error
        traceback.print_exc()


async def _persist_done(
    run_id: UUID, method_id: str, method_job_id: str, result: dict[str, Any]
) -> None:
    # 1) Validate the artifact manifest (no base64 fallback; fail loudly).
    try:
        manifest = parse_manifest(result)
    except ManifestError as exc:
        await _persist_error(
            run_id,
            error_message=f"Method result manifest invalid: {exc}",
            result_payload={
                "ok": False,
                "error": f"Method result manifest invalid: {exc}",
                "logs": [{"step": "api.worker.manifest", "ok": False, "out": str(exc)}],
            },
        )
        return

    # 2) A method that could not store all of its output has not finished the
    #    run, whatever status it reports.
    failed_uploads = _reported_upload_failures(result)
    if failed_uploads:
        shown = ", ".join(failed_uploads[:5]) + (
            f", and {len(failed_uploads) - 5} more" if len(failed_uploads) > 5 else ""
        )
        await _fail(
            run_id,
            CODE_ARTIFACT_UPLOAD_FAILED,
            f"The analysis finished, but {len(failed_uploads)} result file(s) could not be "
            f"saved to storage ({shown}). The run was not completed; please run it again.",
            step="api.worker.artifacts",
            details={"method_id": method_id, "files": failed_uploads},
        )
        return

    # 3) Build the lightweight scientific summary + per-tree rows (no base64).
    unified_result, tree_rows = await asyncio.to_thread(
        assemble_unified_tree_result, method_id, result
    )

    # 4) Build DB rows from the manifest. The method service uploaded the files
    #    itself, using its scoped credentials.
    artifact_service = ArtifactService()
    artifact_rows = artifact_service.ingest(
        run_id=run_id,
        method_id=method_id,
        manifest_artifacts=manifest,
    )

    # 5) A result is only a result if it has what this method always delivers
    #    (at least one tree and its result bundle). Without this, a method that
    #    reports success but declares nothing would pass the file check below
    #    with an empty list.
    missing = missing_requirements(method_id, result, tree_rows, artifact_rows)
    log_stored = has_execution_log(artifact_rows)
    if not log_stored and not has_step_log(result):
        # Without the log file the step log is the only account of the run.
        missing.append(NO_EXECUTION_RECORD)
    if missing:
        _log("result incomplete", run_id=run_id, method_id=method_id, missing="; ".join(missing))
        await _fail(
            run_id,
            CODE_INCOMPLETE_RESULT,
            f"The {method_id} analysis reported success, but its result is incomplete: "
            f"{'; '.join(missing)}. The run was not completed; please run it again, and "
            "contact support if it keeps happening.",
            step="api.worker.completion",
            details={"method_id": method_id, "missing": missing},
        )
        return
    if not log_stored:
        # The scientific output is complete and the step log is stored with the
        # run; keep it and say what is missing.
        unified_result = dict(unified_result)
        unified_result["warnings"] = [*(unified_result.get("warnings") or []), dict(LOG_MISSING_WARNING)]

    # 6) Do not take the manifest's word for it: every declared file must be in
    #    the object store, with the declared size, before the run is DONE.
    try:
        report = await verify_artifacts(artifact_rows, _artifact_storage_backend())
    except ArtifactStoreUnavailable as exc:
        _log("artifact verification impossible", run_id=run_id, error=repr(exc.__cause__ or exc))
        await _fail(
            run_id,
            CODE_ARTIFACT_STORE_UNAVAILABLE,
            "The analysis finished, but the result storage could not be reached to confirm "
            "that its files were saved. The run was not completed; please run it again.",
            step="api.worker.artifacts",
            details={"method_id": method_id, "artifacts": len(artifact_rows)},
        )
        return
    if not report.ok:
        _log("artifacts not stored as declared", run_id=run_id, problems=report.summary())
        await _fail(
            run_id,
            CODE_ARTIFACTS_MISSING,
            f"The analysis finished, but {len(report.problems)} of {report.checked} result "
            f"file(s) are not in storage as expected ({report.summary()}). "
            "The run was not completed; please run it again.",
            step="api.worker.artifacts",
            details={"method_id": method_id, "problems": report.problems},
        )
        await _keep_verified_logs(run_id, artifact_rows, report.verified_keys)
        return

    # 7) Persist run summary + trees + artifact references in ONE transaction:
    #    a reader either sees the run still running, or DONE with all of them.
    async with AsyncSessionLocal() as db:
        run_repo = RunRepository(db)
        # set_result overwrites `result` wholesale, so re-attach the
        # preprocessing entries stored at staging time ahead of the service's
        # own logs. Runs staged before this change simply have none.
        unified_result = _merge_preprocess_logs(
            unified_result, await run_repo.get_by_id(run_id)
        )
        # Record the environment identity alongside the result. Degrades to a
        # no-op when the deployment carries no version-information file.
        unified_result = attach_version_info(unified_result, method_id)
        if "version_info" not in unified_result:
            _log("version info unavailable", run_id=run_id, method_id=method_id)
        await run_repo.set_result(run_id, unified_result, RunStatus.DONE, commit=False)
        tree_repo = RunTreeRepository(db)
        await tree_repo.replace_for_run(run_id, tree_rows)
        artifact_repo = ArtifactRepository(db)
        await artifact_repo.replace_for_run(run_id, artifact_rows)
        await db.commit()
    _log(
        "run completed",
        run_id=run_id,
        method_id=method_id,
        artifacts=len(artifact_rows),
    )


async def _persist_error(
    run_id: UUID,
    *,
    error_message: str,
    result_payload: dict[str, Any] | None = None,
    code: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Finish a run as ERROR. With ``code`` the stored error is the structured
    form the API already understands for staging errors, so the user sees the
    code next to the message."""
    payload, normalized_error = normalize_failed_result_payload(
        result_payload, fallback_message=error_message
    )
    stored_error = normalized_error
    if code:
        stored_error = json.dumps(
            {"ok": False, "error": {"code": code, "message": normalized_error, "details": details or {}}},
            ensure_ascii=True,
            sort_keys=True,
            default=str,
        )
    async with AsyncSessionLocal() as db:
        # One transaction: the run fails, its owner's next run moves up, and
        # the owner's notification is queued.
        await RunRepository(db).fail_run(
            run_id, error=stored_error, message=normalized_error, result=payload
        )
    _log("run errored", run_id=run_id, code=code)


async def _persist_staging_error(run_id: UUID, err: StagingError) -> None:
    async with AsyncSessionLocal() as db:
        await RunRepository(db).fail_run(
            run_id,
            error=json.dumps(err.error_payload, ensure_ascii=True, sort_keys=True),
            message=err.message,
            result=err.error_payload,
        )
    _log("run staging error", run_id=run_id, code=err.code)


async def _ingest_failure_logs(
    run_id: UUID, method_id: str, raw_result: dict[str, Any] | None
) -> None:
    """Failed-run retention: register the method's own log uploads.

    The method service auto-uploads ``job.log`` to MinIO at the end of every
    job (success or failure) and appends a manifest entry for it. So on
    failure we just parse the same manifest the success path uses and pull out
    the ``log`` rows. If the method crashed before writing its result we have
    nothing to register — accept that.

    Cancelled runs intentionally ingest nothing (output is incomplete).
    """
    if not isinstance(raw_result, dict):
        return
    try:
        manifest = parse_manifest(raw_result)
    except ManifestError:
        return
    try:
        artifact_service = ArtifactService()
        log_rows = artifact_service.ingest(
            run_id=run_id,
            method_id=method_id,
            manifest_artifacts=manifest,
            logs_only=True,
        )
        if not log_rows:
            return
        async with AsyncSessionLocal() as db:
            artifact_repo = ArtifactRepository(db)
            await artifact_repo.replace_for_run(run_id, log_rows)
            await db.commit()
        _log("failure logs ingested", run_id=run_id, logs=len(log_rows))
    except Exception:  # noqa: BLE001 - never let log ingest mask the real error
        traceback.print_exc()


async def _mark_cancelled(
    run_id: UUID, message: str = "Run cancelled", *, never_started: bool = False
) -> None:
    async with AsyncSessionLocal() as db:
        run_repo = RunRepository(db)
        await run_repo.mark_cancelled(run_id, message, never_started=never_started)
    _log("run cancelled", run_id=run_id, never_started=never_started or None)


async def _release_for_capacity(
    run_id: UUID, worker_id: str, method_id: str, reason: str, retry_after: float,
    tracker: Optional[CapacityTracker],
) -> None:
    """The method service could not start the job yet: put the run back in the
    queue (it keeps its position) and pause offers to that method briefly."""
    if tracker is not None:
        tracker.mark_busy(method_id, reason, retry_after)
    async with AsyncSessionLocal() as db:
        released = await RunRepository(db).release_for_capacity(run_id, worker_id, reason)
    _log("run waiting for capacity", run_id=run_id, method_id=method_id, released=released, reason=reason)


async def _keep_lease(run_id: UUID, worker_id: str) -> None:
    """Renew this worker's lease on a run for as long as it is working on it.

    Staging a large input, fetching a large result or waiting for the object
    store can each take longer than one lease. Without renewal the run would
    look abandoned and be picked up a second time while still in hand. If the
    worker dies, this stops with it and the lease expires as intended.
    """
    interval = max(1.0, LEASE_SECONDS / 3)
    while True:
        await asyncio.sleep(interval)
        try:
            async with AsyncSessionLocal() as db:
                await RunRepository(db).renew_lease(run_id, worker_id, LEASE_SECONDS)
        except Exception:  # noqa: BLE001 - a missed renewal is retried next round
            traceback.print_exc()


async def process_run(
    run_id: UUID, worker_id: str, tracker: Optional[CapacityTracker] = None
) -> None:
    """Drive a single claimed run from staging -> method job -> result."""
    workspace = None
    method_id = ""
    reserved = False
    lease_keeper = asyncio.create_task(_keep_lease(run_id, worker_id))
    try:
        async with AsyncSessionLocal() as db:
            run_repo = RunRepository(db)
            file_repo = FileRepository(db)
            run = await run_repo.get_by_id(run_id)
            if run is None:
                return
            method_id = run.method_id
            params = run.params if isinstance(run.params, dict) else {}
            method_job_id = run.method_job_id
            started_at = run.started_at
            # Until the job is submitted the method service cannot count it, so
            # the tracker holds the slot for it.
            if tracker is not None and not method_job_id:
                tracker.reserve(method_id, run_id)
                reserved = True
            cancel_requested = run.cancel_requested_at is not None
            input_storage_path = await _resolve_input_storage_path(run, file_repo)

        # Resume path: a reclaimed run already submitted a method job.
        if not method_job_id:
            if cancel_requested:
                # Cancelled before we submitted anything to the method service:
                # the analysis never started, so the run is free for the quota.
                await _mark_cancelled(run_id, "Cancelled before execution", never_started=True)
                return

            # Stage + preprocess input.
            async with AsyncSessionLocal() as db:
                run_repo = RunRepository(db)
                await run_repo.update_stage(
                    run_id, "STAGING_INPUT", message="Staging input", progress=5
                )

            container_path: Optional[str] = None
            if input_storage_path:
                async with AsyncSessionLocal() as db:
                    run_repo = RunRepository(db)
                    await run_repo.update_stage(
                        run_id, "PREPROCESSING", message="Preparing input", progress=10
                    )
                staging_limit = limits.staging_timeout_seconds()
                try:
                    # Bounded like everything else a run does: fetching and
                    # converting the input must not hold the run for ever.
                    staged = await asyncio.wait_for(
                        prepare_method_input(
                            run_id=run_id,
                            method_id=method_id,
                            original_storage_path=input_storage_path,
                            params=params,
                            storage=_storage_backend(),
                        ),
                        timeout=staging_limit,
                    )
                except asyncio.TimeoutError:
                    # Its work directory is derived from the run id, so it can
                    # be removed although the preparation never returned it.
                    workspace = run_work_root(run_id)
                    await _fail(
                        run_id,
                        CODE_STAGING_TIMEOUT,
                        f"Preparing the input file took longer than {limits.describe_duration(staging_limit)} "
                        "and was stopped. The analysis was not started. The file may be too large or in a "
                        "format that is slow to convert; try a smaller file.",
                        step="api.worker.staging",
                        details={"method_id": method_id, "limit_seconds": int(staging_limit)},
                    )
                    return
                except StagingError as err:
                    if staged_workspace := getattr(err, "workspace", None):
                        workspace = staged_workspace
                    await _persist_staging_error(run_id, err)
                    return
                workspace = staged.workspace
                container_path = staged.container_path
                # Persist the preprocessing trace now, before the method job is
                # submitted. _persist_done merges it back ahead of the service's
                # own logs when it overwrites `result` with the unified record.
                if staged.log_entries:
                    async with AsyncSessionLocal() as db:
                        run_repo = RunRepository(db)
                        await run_repo.append_result_logs(run_id, staged.log_entries)
                        await db.commit()

            # Re-check cancellation just before submitting.
            async with AsyncSessionLocal() as db:
                run_repo = RunRepository(db)
                fresh = await run_repo.get_by_id(run_id)
                if fresh is not None and fresh.cancel_requested_at is not None:
                    await run_repo.mark_cancelled(
                        run_id, "Cancelled before submission", never_started=True
                    )
                    return
                await run_repo.update_stage(
                    run_id,
                    "SUBMITTING_METHOD_JOB",
                    message=f"Submitting job to {method_id}",
                    progress=20,
                )

            try:
                method_job_id = await jobs.submit_job(
                    method_id,
                    file_path=container_path,
                    params=params,
                    run_id=str(run_id),
                    timeout_seconds=_method_job_deadline(method_id, started_at),
                )
            except jobs.MethodBusy as busy:
                # Not a failure: the service is full (or short of memory) right
                # now. The run goes back to the queue and is offered again.
                await _release_for_capacity(
                    run_id, worker_id, method_id, busy.reason, busy.retry_after_seconds, tracker
                )
                return
            except httpx.TransportError as exc:
                # The service did not answer (restarting, or the network). The
                # run waits in the queue; the queue-wait limit bounds how long.
                # If the request did reach the service, submitting the same
                # run_id again returns that job instead of starting another.
                _log("method service unreachable at submit", run_id=run_id, method_id=method_id, error=repr(exc))
                await _release_for_capacity(
                    run_id, worker_id, method_id,
                    f"The {method_id} service is not reachable right now; "
                    "the run will start when it is back.",
                    10, tracker,
                )
                return
            if tracker is not None and reserved:
                tracker.submitted(method_id, run_id)
                reserved = False
            async with AsyncSessionLocal() as db:
                run_repo = RunRepository(db)
                await run_repo.set_method_job_id(run_id, method_job_id)
            _log("submitted method job", run_id=run_id, method_id=method_id, method_job_id=method_job_id)

        await _poll_method_job(run_id, method_id, method_job_id, worker_id)
        await _after_job(run_id, method_id, method_job_id)

    except jobs.MethodServiceUnavailable as exc:
        await _persist_error(run_id, error_message=str(exc))
    except jobs.MethodCapacityError as exc:
        # The service can never run this job with its current limits. Waiting
        # would not help, so the run fails with the service's explanation.
        message = f"The {method_id} service cannot run this job with its current resource limits: {exc}"
        await _persist_error(
            run_id,
            error_message=message,
            result_payload={
                "ok": False,
                "error": message,
                "logs": [{"step": "api.worker.capacity", "ok": False, "out": str(exc)}],
            },
        )
    except Exception as exc:  # noqa: BLE001
        # An orchestration fault (database, storage, network), not a scientific
        # error. The run owner sees this message, so it carries a reference id
        # instead of the exception text; the traceback goes to the worker log.
        error_id = log_internal_error("Run failed in worker", exc, context=f"run_id={run_id}")
        public_message = (
            f"Run failed because of an internal error (reference {error_id}). "
            "Please try again; if it keeps failing, contact support with this reference."
        )
        await _persist_error(
            run_id,
            error_message=public_message,
            result_payload={
                "ok": False,
                "error": public_message,
                "logs": [{"step": "api.worker.unhandled", "ok": False, "out": public_message}],
            },
        )
    finally:
        lease_keeper.cancel()
        if tracker is not None and reserved:
            tracker.release(method_id, run_id)
        if workspace is not None:
            await asyncio.to_thread(cleanup_workspace, workspace, run_id)


async def _keep_job_log(run_id: UUID, method_id: str, method_job_id: str) -> bool:
    """Give a failed run a downloadable log when it has none.

    A job that ends normally uploads its own log. One that was stopped at its
    time limit, crashed or was killed could not; its service still has the log
    and offers it in bounded form. Fetch it, store it as the run's log file and
    register it, so that every failed run has a log to download and the log
    expires with the run's other files. Returns True when a log was stored.
    """
    async with AsyncSessionLocal() as db:
        if await ArtifactRepository(db).has_log(run_id):
            return False
    text = await jobs.get_job_log(method_id, method_job_id)
    if not text or not text.strip():
        return False
    data = text.encode("utf-8")
    object_key = f"artifacts/{run_id}/{method_job_id}/job.log"
    await _artifact_storage_backend().upload(data, object_key, "text/plain")
    service = ArtifactService()
    row = {
        "storage_backend": service.backend,
        "storage_bucket": service.bucket,
        "object_key": object_key,
        "filename": "job.log",
        "content_type": "text/plain",
        "size_bytes": len(data),
        "checksum_sha256": hashlib.sha256(data).hexdigest(),
        "artifact_kind": ArtifactKind.LOG,
        "artifact_role": "log",
        "is_previewable": True,
    }
    async with AsyncSessionLocal() as db:
        await ArtifactRepository(db).add_for_run(run_id, [row])
        await db.commit()
    _log("job log kept", run_id=run_id, bytes=len(data))
    return True


async def _after_job(run_id: UUID, method_id: str, method_job_id: str) -> None:
    """Housekeeping once a run's method job has reached its end: keep the log
    of a failed job, then let the service forget the job so nothing of it stays
    on the service's disk. Best effort: the run's outcome is already stored and
    nothing here may change it (a service that does not answer keeps the job
    record until its own retention time removes it)."""
    try:
        async with AsyncSessionLocal() as db:
            run = await RunRepository(db).get_by_id(run_id)
        if run is None or run.status not in (RunStatus.DONE, RunStatus.ERROR, RunStatus.CANCELLED):
            return                       # e.g. handed back to the queue: the job is not over
        if run.status == RunStatus.ERROR:
            try:
                await _keep_job_log(run_id, method_id, method_job_id)
            except Exception as exc:  # noqa: BLE001
                _log("job log not kept", run_id=run_id, error=repr(exc))
        await jobs.delete_job(method_id, method_job_id)
    except Exception as exc:  # noqa: BLE001
        _log("job record not removed at the service", run_id=run_id, method_job_id=method_job_id, error=repr(exc))


def _elapsed_seconds(started_at: Any) -> Optional[float]:
    if started_at is None:
        return None
    return (utc_now() - started_at).total_seconds()


def _method_job_deadline(method_id: str, started_at: Any) -> Optional[float]:
    """Seconds the method service should allow the job before stopping it by
    itself: what is left of the run's time limit, plus a margin so that the
    worker is normally the one that reports the timeout."""
    limit = limits.run_timeout_seconds(method_id)
    if limit is None:
        return None
    remaining = limit - (_elapsed_seconds(started_at) or 0.0)
    return max(1.0, remaining) + limits.method_deadline_grace_seconds()


def _timeout_message(method_id: str, limit: float) -> str:
    return (
        f"The run was stopped because it exceeded the maximum run time of "
        f"{limits.describe_duration(limit)} for {method_id}. No result was saved. "
        "Try a smaller dataset or lighter settings, or ask the administrator to raise the limit."
    )


def _job_log_tail(status: Optional[jobs.JobStatus]) -> Optional[str]:
    """The end of the job's own output, when the method service attached it to
    the status of a job it stopped."""
    if status is None:
        return None
    raw = status.raw or {}
    tail = raw.get("log_tail")
    if not tail and isinstance(status.error, dict):
        for entry in status.error.get("logs") or []:
            if isinstance(entry, dict) and entry.get("step") == "method.job.log_tail":
                tail = entry.get("out")
    return tail.strip() if isinstance(tail, str) and tail.strip() else None


async def _fail_timeout(
    run_id: UUID,
    method_id: str,
    limit: float,
    *,
    stop_confirmed: bool,
    status: Optional[jobs.JobStatus] = None,
) -> None:
    # Keep the last lines the job printed: they show how far it got.
    tail = _job_log_tail(status)
    await _fail(
        run_id,
        CODE_TIMEOUT,
        _timeout_message(method_id, limit),
        step="api.worker.timeout",
        details={
            "method_id": method_id,
            "limit_seconds": int(limit),
            "stop_confirmed": stop_confirmed,
        },
        extra_logs=[{"step": "method.job.log_tail", "ok": False, "out": tail}] if tail else None,
    )


def _method_error_code(status: jobs.JobStatus) -> Optional[str]:
    """Failure code a method service attached to its ERROR status, if any."""
    raw = status.raw or {}
    code = raw.get("error_code")
    if not code and isinstance(status.error, dict):
        code = status.error.get("error_code")
    return str(code).strip() if isinstance(code, str) and code.strip() else None


async def _fetch_result(method_id: str, method_job_id: str) -> dict[str, Any]:
    """Fetch a finished job's result, retrying a few times on a failed request."""
    last: Exception | None = None
    for attempt in range(1, RESULT_FETCH_ATTEMPTS + 1):
        try:
            return await jobs.get_job_result(method_id, method_job_id)
        except jobs.MethodJobNotFound:
            raise
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < RESULT_FETCH_ATTEMPTS:
                await asyncio.sleep(METHOD_POLL_INTERVAL)
    assert last is not None
    raise last


async def _poll_method_job(
    run_id: UUID, method_id: str, method_job_id: str, worker_id: str
) -> None:
    """Follow one method job to a terminal state.

    Every way out of this loop is bounded: the job finishes, is cancelled, runs
    past its time limit, disappears from its service, or the service stays
    unreachable for longer than allowed. No run polls for ever.
    """
    cancel_sent_at: Optional[float] = None      # user cancel forwarded to the service
    timed_out_at: Optional[float] = None        # time limit exceeded, stop requested
    timed_out_limit = 0.0
    unreachable_since: Optional[float] = None

    while True:
        async with AsyncSessionLocal() as db:
            run_repo = RunRepository(db)
            await run_repo.renew_lease(run_id, worker_id, LEASE_SECONDS)
            run = await run_repo.get_by_id(run_id)
        if run is None:
            return

        now = time.monotonic()
        cancel_requested = run.cancel_requested_at is not None
        if cancel_requested and cancel_sent_at is None:
            _log("cancel requested -> cancelling method job", run_id=run_id, method_job_id=method_job_id)
            try:
                await jobs.cancel_job(method_id, method_job_id)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            cancel_sent_at = now
            async with AsyncSessionLocal() as db:
                run_repo = RunRepository(db)
                await run_repo.update_stage(run_id, "CANCELLING", message="Cancelling...")

        # Time limit, measured from the persisted start so it also holds across
        # a worker restart.
        limit = limits.run_timeout_seconds(method_id)
        elapsed = _elapsed_seconds(run.started_at)
        if (
            limit is not None
            and elapsed is not None
            and elapsed > limit
            and timed_out_at is None
            and not cancel_requested
        ):
            _log("run exceeded its time limit -> stopping method job",
                 run_id=run_id, method_job_id=method_job_id, limit=int(limit), elapsed=int(elapsed))
            try:
                await jobs.cancel_job(method_id, method_job_id)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            timed_out_at = now
            timed_out_limit = limit
            async with AsyncSessionLocal() as db:
                await RunRepository(db).update_stage(
                    run_id, None, message="Stopping: the run exceeded its maximum run time"
                )

        try:
            status = await jobs.get_job_status(method_id, method_job_id)
            unreachable_since = None
        except jobs.MethodJobNotFound:
            # The service is up but has no record of the job: its job state is
            # gone (container recreated). The job cannot be followed any more.
            if cancel_requested:
                await _mark_cancelled(run_id, "Run cancelled")
            elif timed_out_at is not None:
                await _fail_timeout(run_id, method_id, timed_out_limit, stop_confirmed=True)
            else:
                await _fail(
                    run_id,
                    CODE_METHOD_RESTARTED,
                    f"The {method_id} service was restarted while this run was in progress, "
                    "so its work was lost. The run was not repeated automatically; please submit it again.",
                    step="api.worker.method_job",
                    details={"method_id": method_id, "method_job_id": method_job_id},
                )
            return
        except Exception as exc:  # noqa: BLE001
            # The service did not answer. Keep the lease and retry, but only for
            # so long: a service that stays away must not hold the run for ever.
            if unreachable_since is None:
                unreachable_since = now
            waited = now - unreachable_since
            allowed = limits.method_unreachable_seconds()
            _log("status poll failed", run_id=run_id, error=str(exc), waited=int(waited), allowed=int(allowed))
            if waited >= allowed:
                if cancel_requested:
                    await _mark_cancelled(run_id, "Run cancelled")
                elif timed_out_at is not None:
                    await _fail_timeout(run_id, method_id, timed_out_limit, stop_confirmed=False)
                else:
                    await _fail(
                        run_id,
                        CODE_METHOD_UNREACHABLE,
                        f"The {method_id} service stopped responding while this run was in progress "
                        f"and did not come back within {limits.describe_duration(allowed)}. "
                        "The run was not repeated automatically; please submit it again.",
                        step="api.worker.method_job",
                        details={"method_id": method_id, "method_job_id": method_job_id,
                                 "waited_seconds": int(waited)},
                    )
                return
            await asyncio.sleep(METHOD_POLL_INTERVAL)
            continue

        method_status = status.status

        if method_status == "DONE":
            # A job that finished before a stop request took effect is a valid
            # result; it is kept.
            async with AsyncSessionLocal() as db:
                run_repo = RunRepository(db)
                await run_repo.update_stage(
                    run_id, "FETCHING_RESULT", message="Fetching result", progress=95
                )
            try:
                result = await _fetch_result(method_id, method_job_id)
            except Exception as exc:  # noqa: BLE001
                _log("result fetch failed", run_id=run_id, error=repr(exc))
                await _fail(
                    run_id,
                    CODE_RESULT_UNAVAILABLE,
                    f"The {method_id} service finished the analysis but its result could not be "
                    "retrieved. The run was not completed; please run it again.",
                    step="api.worker.method_job",
                    details={"method_id": method_id, "method_job_id": method_job_id},
                )
                return
            await _persist_done(run_id, method_id, method_job_id, result)
            return

        if method_status == "ERROR":
            if timed_out_at is not None:
                await _fail_timeout(run_id, method_id, timed_out_limit, stop_confirmed=True, status=status)
                return
            payload, err_msg = normalize_failed_result_payload(
                status.raw or {},
                fallback_message=status.message
                or (status.error if isinstance(status.error, str) else None),
            )
            # Retention policy: failed runs keep logs only. The method already
            # uploaded job.log to MinIO and stamped a manifest entry for it;
            # the status payload carries that manifest under status.error.
            method_result = status.error if isinstance(status.error, dict) else None
            await _ingest_failure_logs(run_id, method_id, method_result)
            # A code set by the service (its own time limit, a lost job process,
            # an out-of-memory kill, a failed upload) is kept with the run.
            code = _method_error_code(status)
            await _persist_error(
                run_id,
                error_message=err_msg,
                result_payload=payload,
                code=code,
                details={"method_id": method_id, "reported_by": "method service"} if code else None,
            )
            return

        if method_status == "CANCELLED":
            if timed_out_at is not None and not cancel_requested:
                await _fail_timeout(run_id, method_id, timed_out_limit, stop_confirmed=True, status=status)
            else:
                await _mark_cancelled(run_id, "Run cancelled")
            return

        # Still in progress. A stop that was asked for must be confirmed within
        # a bounded time; after that the run is closed regardless.
        confirm = limits.cancel_confirm_seconds()
        if timed_out_at is not None and now - timed_out_at >= confirm:
            await _fail_timeout(run_id, method_id, timed_out_limit, stop_confirmed=False)
            return
        if cancel_sent_at is not None and now - cancel_sent_at >= confirm:
            _log("cancel not confirmed by the method service", run_id=run_id, method_job_id=method_job_id)
            await _mark_cancelled(run_id, "Run cancelled")
            return

        if timed_out_at is not None or cancel_sent_at is not None:
            # Still running after a stop request: ask again (the call is
            # idempotent), in case the first one never reached the service.
            try:
                await jobs.cancel_job(method_id, method_job_id)
            except Exception:  # noqa: BLE001
                pass

        # Reflect the method's stage/progress/message (no fake timers).
        if not cancel_requested and timed_out_at is None:
            poll_stage, poll_progress = _normalize_method_poll_stage(
                method_status,
                status.stage,
                status.progress,
            )
            async with AsyncSessionLocal() as db:
                run_repo = RunRepository(db)
                await run_repo.update_stage(
                    run_id,
                    poll_stage,
                    message=status.message,
                    progress=poll_progress,
                )

        await asyncio.sleep(METHOD_POLL_INTERVAL)


def _queue_timeout_failure(limit: float) -> dict[str, Any]:
    message = (
        f"This run waited more than {limits.describe_duration(limit)} for a free slot of its "
        "method and was stopped before it started. Nothing was executed; please submit it again later."
    )
    details = {"limit_seconds": int(limit)}
    return {
        "message": message,
        "error": json.dumps(
            {"ok": False, "error": {"code": CODE_QUEUE_TIMEOUT, "message": message, "details": details}},
            ensure_ascii=True, sort_keys=True,
        ),
        "result": {
            "ok": False,
            "error": message,
            "error_code": CODE_QUEUE_TIMEOUT,
            "logs": [{"step": "api.worker.queue", "ok": False, "out": message}],
        },
    }


async def expire_waiting_runs() -> list[UUID]:
    """Fail runs that have waited for a slot longer than the configured limit."""
    limit = limits.queue_wait_timeout_seconds()
    if limit is None:
        return []
    async with AsyncSessionLocal() as db:
        expired = await RunRepository(db).expire_waiting_runs(limit, **_queue_timeout_failure(limit))
    for run_id in expired:
        _log("run expired in queue", run_id=run_id, limit=int(limit))
    return expired


async def dispatch_once(
    worker_id: str, active: set[UUID], tracker: CapacityTracker
) -> list[UUID]:
    """One dispatch cycle. Claims every run that can start now and returns
    their ids; runs whose method has no free capacity stay QUEUED."""
    async with AsyncSessionLocal() as db:
        run_repo = RunRepository(db)
        # Promote every user's head-of-line first, so a slot freed since the
        # last cycle immediately makes the next-ready runs claimable. Idempotent
        # and cheap; the correctness backstop behind per-transition promotion.
        await run_repo.promote_all_eligible()
    # Runs that have waited too long for a slot end here, which also promotes
    # their owners' next runs before this cycle looks for work.
    await expire_waiting_runs()
    async with AsyncSessionLocal() as db:
        ready_methods = await RunRepository(db).dispatch_ready_methods()

    await tracker.refresh(ready_methods)
    eligible = tracker.eligible(ready_methods)
    waiting = {
        m: reason for m in ready_methods if (reason := tracker.blocked_reason(m)) is not None
    }
    if waiting:
        async with AsyncSessionLocal() as db:
            await RunRepository(db).mark_waiting_for_capacity(waiting)

    claimed: list[UUID] = []
    limit = max_concurrent_runs(tracker)
    while len(active) + len(claimed) < limit:
        async with AsyncSessionLocal() as db:
            run = await RunRepository(db).claim_next_run(
                worker_id, LEASE_SECONDS, eligible_methods=eligible
            )
        if run is None:
            break
        _log("claimed run", run_id=run.id, method_id=run.method_id)
        claimed.append(run.id)
        # Hold the slot until the job is submitted, and stop offering this
        # method once its last free slot is taken.
        if not run.method_job_id:
            tracker.reserve(run.method_id, run.id)
            if tracker.blocked_reason(run.method_id) is not None:
                eligible.discard(run.method_id)
    return claimed


async def main() -> None:
    # Same start-up gate as the API: never process runs on weak production secrets.
    enforce_production_config()
    configure_logging()
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    tracker = CapacityTracker(jobs.get_capacity, ttl_seconds=CAPACITY_REFRESH_SECONDS)
    configured = configured_max_concurrent()
    _log(
        "starting",
        worker_id=worker_id,
        max_concurrent=configured if configured is not None else "auto (sum of method job slots)",
        lease=LEASE_SECONDS,
    )
    active: set[UUID] = set()
    # Run emails are delivered by their own task. It shares nothing with run
    # processing except the database, so a mail server that is down or slow
    # cannot delay a run or change its outcome.
    notifier = asyncio.create_task(notification_loop(), name="notifications")
    # So is the removal of results that are past their date.
    cleaner = asyncio.create_task(retention_loop(), name="retention")

    while True:
        try:
            claimed = await dispatch_once(worker_id, active, tracker)
            for run_id in claimed:
                active.add(run_id)
                task = asyncio.create_task(process_run(run_id, worker_id, tracker))
                task.add_done_callback(lambda t, rid=run_id: active.discard(rid))

            if not claimed:
                await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            notifier.cancel()
            cleaner.cancel()
            break
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except InsecureConfigurationError as exc:
        print(f"[run_worker] {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
