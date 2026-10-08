"""DB-backed run worker / orchestrator.

A standalone process (separate from the API) that:
  - claims QUEUED runs atomically (SELECT ... FOR UPDATE SKIP LOCKED + lease),
  - stages/preprocesses the input,
  - submits an async job to the method service (/jobs),
  - polls the method job status (stage-based, no fake timers),
  - propagates cancellation to the method service,
  - persists the final result/error using the existing contracts,
  - resumes orphaned runs after a lease expires.

Run with:  python -m apps.api.workers.run_worker
"""
from __future__ import annotations

import asyncio
import os
import socket
import sys
import traceback
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.sql import func

from apps.api.database.base import AsyncSessionLocal
from apps.api.database.models import RunStatus
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
)
from apps.api.services.stage_map import progress_for_stage
from apps.api.services.tree_contract import assemble_unified_tree_result
from apps.api.services.version_info import attach_version_info
from apps.api.storage import get_storage

POLL_INTERVAL = float(os.getenv("WORKER_POLL_INTERVAL", "3"))
METHOD_POLL_INTERVAL = float(os.getenv("WORKER_METHOD_POLL_INTERVAL", "10"))
LEASE_SECONDS = int(os.getenv("WORKER_LEASE_SECONDS", "180"))
MAX_CONCURRENT = int(os.getenv("WORKER_MAX_CONCURRENT_RUNS", "4"))

_storage = None


def _storage_backend():
    """Lazily build the dataset storage client (avoids connecting at import time)."""
    global _storage
    if _storage is None:
        _storage = get_storage()
    return _storage


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

    # 2) Build the lightweight scientific summary + per-tree rows (no base64).
    unified_result, tree_rows = await asyncio.to_thread(
        assemble_unified_tree_result, method_id, result
    )

    # 3) Build DB rows from the manifest. Files are already in MinIO — the
    #    method service uploaded them directly using its scoped credentials.
    artifact_service = ArtifactService()
    artifact_rows = artifact_service.ingest(
        run_id=run_id,
        method_id=method_id,
        manifest_artifacts=manifest,
    )

    # 4) Persist run summary + trees + artifact references.
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
        await run_repo.set_result(run_id, unified_result, RunStatus.DONE)
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
) -> None:
    payload, normalized_error = normalize_failed_result_payload(
        result_payload, fallback_message=error_message
    )
    async with AsyncSessionLocal() as db:
        run_repo = RunRepository(db)
        updated = await run_repo.update(
            run_id,
            status=RunStatus.ERROR,
            stage="ERROR",
            error=normalized_error,
            message=normalized_error,
            stage_message=normalized_error,
            progress=100,
            result=payload,
            finished_at=func.now(),
            worker_lease_until=None,
        )
        # Free the owner's turn so their next queued run dispatches promptly.
        await run_repo.promote_next_for_user(updated.user_id if updated else None)
    _log("run errored", run_id=run_id)


async def _persist_staging_error(run_id: UUID, err: StagingError) -> None:
    import json

    async with AsyncSessionLocal() as db:
        run_repo = RunRepository(db)
        updated = await run_repo.update(
            run_id,
            status=RunStatus.ERROR,
            stage="ERROR",
            error=json.dumps(err.error_payload, ensure_ascii=True, sort_keys=True),
            message=err.message,
            stage_message=err.message,
            progress=100,
            result=err.error_payload,
            finished_at=func.now(),
            worker_lease_until=None,
        )
        # Free the owner's turn so their next queued run dispatches promptly.
        await run_repo.promote_next_for_user(updated.user_id if updated else None)
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


async def _mark_cancelled(run_id: UUID, message: str = "Run cancelled") -> None:
    async with AsyncSessionLocal() as db:
        run_repo = RunRepository(db)
        await run_repo.mark_cancelled(run_id, message)
    _log("run cancelled", run_id=run_id)


async def process_run(run_id: UUID, worker_id: str) -> None:
    """Drive a single claimed run from staging -> method job -> result."""
    workspace = None
    method_id = ""
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
            cancel_requested = run.cancel_requested_at is not None
            input_storage_path = await _resolve_input_storage_path(run, file_repo)

        # Resume path: a reclaimed run already submitted a method job.
        if not method_job_id:
            if cancel_requested:
                # Cancelled before we submitted anything to the method service.
                await _mark_cancelled(run_id, "Cancelled before execution")
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
                try:
                    staged = await prepare_method_input(
                        run_id=run_id,
                        method_id=method_id,
                        original_storage_path=input_storage_path,
                        params=params,
                        storage=_storage_backend(),
                    )
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
                    await run_repo.mark_cancelled(run_id, "Cancelled before submission")
                    return
                await run_repo.update_stage(
                    run_id,
                    "SUBMITTING_METHOD_JOB",
                    message=f"Submitting job to {method_id}",
                    progress=20,
                )

            method_job_id = await jobs.submit_job(
                method_id,
                file_path=container_path,
                params=params,
                run_id=str(run_id),
            )
            async with AsyncSessionLocal() as db:
                run_repo = RunRepository(db)
                await run_repo.set_method_job_id(run_id, method_job_id)
            _log("submitted method job", run_id=run_id, method_id=method_id, method_job_id=method_job_id)

        await _poll_method_job(run_id, method_id, method_job_id, worker_id)

    except jobs.MethodServiceUnavailable as exc:
        await _persist_error(run_id, error_message=str(exc))
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
        if workspace is not None:
            await asyncio.to_thread(cleanup_workspace, workspace, run_id)


async def _poll_method_job(
    run_id: UUID, method_id: str, method_job_id: str, worker_id: str
) -> None:
    cancel_sent = False
    while True:
        async with AsyncSessionLocal() as db:
            run_repo = RunRepository(db)
            await run_repo.renew_lease(run_id, worker_id, LEASE_SECONDS)
            run = await run_repo.get_by_id(run_id)
        if run is None:
            return

        cancel_requested = run.cancel_requested_at is not None
        if cancel_requested and not cancel_sent:
            _log("cancel requested -> cancelling method job", run_id=run_id, method_job_id=method_job_id)
            try:
                await jobs.cancel_job(method_id, method_job_id)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            cancel_sent = True
            async with AsyncSessionLocal() as db:
                run_repo = RunRepository(db)
                await run_repo.update_stage(run_id, "CANCELLING", message="Cancelling...")

        try:
            status = await jobs.get_job_status(method_id, method_job_id)
        except Exception as exc:  # noqa: BLE001
            # Transient method-service hiccup; lease keeps the run ours. Retry.
            _log("status poll failed; retrying", run_id=run_id, error=str(exc))
            await asyncio.sleep(METHOD_POLL_INTERVAL)
            continue

        method_status = status.status

        if method_status == "DONE":
            async with AsyncSessionLocal() as db:
                run_repo = RunRepository(db)
                await run_repo.update_stage(
                    run_id, "FETCHING_RESULT", message="Fetching result", progress=95
                )
            result = await jobs.get_job_result(method_id, method_job_id)
            await _persist_done(run_id, method_id, method_job_id, result)
            return

        if method_status == "ERROR":
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
            await _persist_error(run_id, error_message=err_msg, result_payload=payload)
            return

        if method_status == "CANCELLED":
            await _mark_cancelled(run_id, "Run cancelled")
            return

        # In-progress: reflect the method's stage/progress/message (no fake timers).
        if not cancel_requested:
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


async def main() -> None:
    # Same start-up gate as the API: never process runs on weak production secrets.
    enforce_production_config()
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    _log("starting", worker_id=worker_id, max_concurrent=MAX_CONCURRENT, lease=LEASE_SECONDS)
    active: set[UUID] = set()

    while True:
        try:
            # Promote every user's head-of-line first, so a slot freed since the last
            # cycle immediately makes the next-ready runs claimable. Idempotent + cheap;
            # this is the correctness backstop behind the per-transition promotion.
            async with AsyncSessionLocal() as db:
                run_repo = RunRepository(db)
                await run_repo.promote_all_eligible()

            claimed_any = False
            while len(active) < MAX_CONCURRENT:
                async with AsyncSessionLocal() as db:
                    run_repo = RunRepository(db)
                    run = await run_repo.claim_next_run(worker_id, LEASE_SECONDS)
                if run is None:
                    break
                run_id = run.id
                _log("claimed run", run_id=run_id, method_id=run.method_id)
                active.add(run_id)
                task = asyncio.create_task(process_run(run_id, worker_id))
                task.add_done_callback(lambda t, rid=run_id: active.discard(rid))
                claimed_any = True

            if not claimed_any:
                await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
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
