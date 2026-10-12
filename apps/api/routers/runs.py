from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.access import ensure_run_access
from apps.api.auth.dependencies import get_current_user_required
from apps.api.config import method_service_url
from apps.api.contracts.loader import get_ui_hints
from apps.api.database import get_db
from apps.api.database.models import Run, RunStatus, StorageState, User
from apps.api.repositories.artifact_repository import ArtifactRepository
from apps.api.repositories.file_repository import FileRepository
from apps.api.repositories.run_repository import RunRepository
from apps.api.repositories.run_tree_repository import RunTreeRepository
from apps.api.security.errors import internal_error
from apps.api.services import run_quota

router = APIRouter(prefix="/runs", tags=["runs"])

TERMINAL_STATUSES = (RunStatus.DONE, RunStatus.ERROR, RunStatus.CANCELLED)

# Limits on creating runs (hourly quota, queue size, submission ceiling) live in
# apps/api/services/run_quota.py and are configurable through the environment.


# --------------------------------------------------------------------------- #
# Serialization helpers
# --------------------------------------------------------------------------- #
def _normalized_run_params(run: Run) -> dict[str, Any]:
    raw = getattr(run, "params", None)
    return raw if isinstance(raw, dict) else {}


def _clone_ids_from_result_payload(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    clones = payload.get("clones")
    if not isinstance(clones, dict):
        return []
    raw_clone_ids = clones.get("clone_id")
    if not isinstance(raw_clone_ids, list):
        return []

    out: list[str] = []
    for clone_id in raw_clone_ids:
        clone_text = str(clone_id).strip()
        out.append(clone_text if clone_text else "")
    return out


def _attach_clone_ids_to_result_trees(payload: dict[str, Any]) -> dict[str, Any]:
    trees = payload.get("trees")
    if not isinstance(trees, list):
        return payload

    clone_ids = _clone_ids_from_result_payload(payload)
    if not clone_ids:
        return payload

    for idx, tree in enumerate(trees):
        if not isinstance(tree, dict):
            continue
        if idx >= len(clone_ids):
            continue
        clone_id = clone_ids[idx]
        if not clone_id:
            continue
        tree.setdefault("clone_id", clone_id)
    return payload


async def _dataset_descriptor(run: Run, file_repo: FileRepository) -> dict[str, Any] | None:
    """Lightweight metadata for the dataset a run used (incl. deletion state).

    Never includes the binary or a storage path — only history-safe metadata so
    the UI can show a deleted dataset's name while preserving the run.
    """
    file_id = getattr(run, "input_file_id", None)
    if not file_id:
        return None
    f = await file_repo.get_by_id(file_id)
    if f is None:
        return None
    state = f.storage_state.value if hasattr(f.storage_state, "value") else str(f.storage_state)
    return {
        "id": str(f.id),
        "original_filename": f.original_filename,
        "file_size": f.file_size,
        "checksum_sha256": f.checksum_sha256,
        "mime_type": f.mime_type,
        "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None,
        "storage_state": state,
        "is_deleted": state == StorageState.DELETED.value,
        "deleted_at": f.deleted_at.isoformat() if f.deleted_at else None,
    }


async def _resolve_dataset_meta(run: Run, file_repo: FileRepository) -> tuple[str | None, list[str]]:
    names: list[str] = []

    def add_name(raw: Any) -> None:
        if not isinstance(raw, str):
            return
        cleaned = raw.strip()
        if cleaned and cleaned not in names:
            names.append(cleaned)

    add_name(getattr(run, "dataset_name", None))

    input_file_id = getattr(run, "input_file_id", None)
    if input_file_id is not None:
        linked_input = await file_repo.get_by_id(input_file_id)
        if linked_input is not None:
            add_name(getattr(linked_input, "original_filename", None))

    run_files = await file_repo.get_by_run(run.id)
    for file_row in run_files:
        add_name(getattr(file_row, "original_filename", None))

    dataset_name = names[0] if names else None
    return dataset_name, names


def _public_status(
    run: Run,
    *,
    include_run_id: bool = False,
    dataset_name: str | None = None,
    dataset_files: list[str] | None = None,
) -> dict[str, Any]:
    """Convert Run model to public status dict (stage-aware)."""
    resolved_dataset_name = dataset_name
    if resolved_dataset_name is None:
        raw_dataset_name = getattr(run, "dataset_name", None)
        resolved_dataset_name = raw_dataset_name if isinstance(raw_dataset_name, str) else None

    resolved_dataset_files = dataset_files if dataset_files is not None else []
    if not resolved_dataset_files and resolved_dataset_name:
        resolved_dataset_files = [resolved_dataset_name]

    input_file_id = getattr(run, "input_file_id", None)

    out = {
        "status": run.status.value if hasattr(run.status, "value") else str(run.status),
        "progress": run.progress,
        "message": run.message,
        "stage": getattr(run, "stage", None),
        "stage_message": getattr(run, "stage_message", None),
        "method_id": run.method_id,
        "params": _normalized_run_params(run),
        "dataset_name": resolved_dataset_name,
        "dataset_files": resolved_dataset_files,
        "input_file_id": str(input_file_id) if input_file_id else None,
        "cancel_requested": getattr(run, "cancel_requested_at", None) is not None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
    raw_error = getattr(run, "error", None)
    if raw_error:
        try:
            parsed = json.loads(raw_error)
            if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
                out["error"] = parsed["error"]
                parsed_message = parsed["error"].get("message")
                if isinstance(parsed_message, str) and parsed_message.strip():
                    out["message"] = parsed_message
        except Exception:
            pass
    if include_run_id:
        out["run_id"] = str(run.id)
    return out


def _run_summary(run) -> dict:
    """Build a run summary for list responses."""
    raw_dataset_name = getattr(run, "dataset_name", None)
    dataset_name = raw_dataset_name if isinstance(raw_dataset_name, str) else None
    return {
        "id": str(run.id),
        "method_id": run.method_id,
        "status": run.status.value if hasattr(run.status, "value") else str(run.status),
        "progress": run.progress,
        "message": run.message,
        "stage": getattr(run, "stage", None),
        "params": _normalized_run_params(run),
        "dataset_name": dataset_name,
        "dataset_files": [dataset_name] if dataset_name else [],
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


async def _load_run_with_access(
    run_id: str,
    *,
    current_user: User,
    run_repo: RunRepository,
) -> Run:
    try:
        run_uuid = UUID(run_id)
    except ValueError:
        raise HTTPException(400, "Invalid run ID format")

    run = await run_repo.get_by_id(run_uuid)
    if not run:
        raise HTTPException(404, "Run not found")

    ensure_run_access(run, current_user)
    return run


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@router.get("")
async def list_runs(
    current_user: User = Depends(get_current_user_required),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    run_id: Optional[str] = Query(None),
    dataset: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    method_id: Optional[str] = Query(None),
    created_on: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List current user's runs with optional DB-level filters (auth required).

    `status` is coerced to a RunStatus and ignored when unrecognized, so an
    unexpected value never 422s — it simply applies no status filter.
    """
    status_filter: Optional[RunStatus] = None
    if status:
        try:
            status_filter = RunStatus(status.strip().upper())
        except ValueError:
            status_filter = None

    run_repo = RunRepository(db)
    runs = await run_repo.get_by_user(
        current_user.id,
        skip=skip,
        limit=limit,
        run_id=run_id,
        dataset=dataset,
        status=status_filter,
        method_id=(method_id.strip() or None) if method_id else None,
        created_on=created_on,
    )
    return [_run_summary(r) for r in runs]


class CreateRunBody(BaseModel):
    params: dict[str, Any] = {}
    file_id: Optional[str] = None


def _limit_error(quota: run_quota.QuotaState) -> HTTPException:
    """The refusal for a run that may not be created right now.

    A full queue is a conflict with the user's own unfinished runs (409, as
    before). The two rolling limits are rate limits (429) and say when to try
    again, in the body and in a Retry-After header.
    """
    blocked = quota.blocked_by
    if blocked == run_quota.CODE_QUEUE_FULL:
        return HTTPException(
            status_code=409,
            detail={"code": blocked, "message": quota.message, "limit": quota.max_queued},
        )
    window = quota.hourly if blocked == run_quota.CODE_QUOTA else quota.submissions
    retry_after = quota.retry_after_seconds or 1
    return HTTPException(
        status_code=429,
        detail={
            "code": blocked,
            "message": quota.message,
            "limit": window.limit,
            "used": window.used,
            "reset_at": window.reset_at.isoformat() if window.reset_at else None,
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )


@router.post("")
async def create_run(
    method: str = Query(..., description="Method ID (e.g., 'dowser')"),
    body: CreateRunBody = Body(default_factory=CreateRunBody),
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Create a new run.

    Run creation is durable and quick: it only validates input, creates a
    QUEUED run row and returns the run_id immediately. The separate worker
    process picks up the run and orchestrates the method job. Upload your file
    first via the /uploads endpoints and pass the returned file_id here.
    """
    base = method_service_url(method)
    if not base:
        raise HTTPException(
            400,
            f"No service URL configured for method '{method}'. Set METHOD_{method.upper()}_URL.",
        )

    ui_hints = get_ui_hints(method)
    requires_file = ui_hints.get("requiresFile", True)

    params = body.params if isinstance(body.params, dict) else {}
    file_id = (body.file_id or "").strip() or None

    run_repo = RunRepository(db)
    file_repo = FileRepository(db)

    # Run creation always belongs to an authenticated user: every quota and
    # the per-user queue are keyed on this id.
    user_id = current_user.id

    if requires_file and not file_id:
        raise HTTPException(
            400,
            "This method requires an input file. Upload a file first and pass its file_id.",
        )

    existing_file = None
    if file_id:
        try:
            existing_file_id = UUID(file_id)
        except ValueError:
            raise HTTPException(400, "Invalid file_id format.")
        existing_file = await file_repo.get_by_id_and_user(existing_file_id, user_id)
        if not existing_file:
            raise HTTPException(404, "File not found or you do not have access to it.")
        # A deleted dataset's object no longer exists; block rerun until re-upload.
        if existing_file.storage_state == StorageState.DELETED:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DATASET_DELETED",
                    "message": "This dataset has been deleted. Re-upload the file to run again.",
                    "dataset_id": str(existing_file.id),
                },
            )

    # Limits, checked and enforced as one step: from here until the new run is
    # committed no other request of this user can create a run, so concurrent
    # requests cannot each pass a check that only one of them should.
    await run_repo.lock_run_creation(user_id)
    quota = await run_quota.quota_state(run_repo, user_id)
    if quota.blocked_by is not None:
        await db.rollback()  # nothing was written; release the lock at once
        raise _limit_error(quota)

    run = await run_repo.create_run(
        method_id=method,
        params=params,
        user_id=user_id,
        input_file_id=existing_file.id if existing_file else None,
        dataset_name=existing_file.original_filename if existing_file else None,
    )

    # Promote so a user with a free turn dispatches immediately.
    await run_repo.promote_next_for_user(user_id)

    # Report whether this run became the active turn or is waiting in the personal
    # queue (and, if waiting, its 1-based position).
    fresh = await run_repo.get_by_id(run.id)
    is_active_turn = fresh is not None and fresh.dispatch_seq is not None
    queue_position: Optional[int] = None
    if not is_active_turn:
        personal_queue = await run_repo.get_personal_queue_for_user(user_id)
        for idx, queued_run in enumerate(personal_queue):
            if queued_run.id == run.id:
                queue_position = idx + 1
                break

    return {
        "run_id": str(run.id),
        "queued": not is_active_turn,
        "queue_position": queue_position,
    }


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Request cancellation of a run. Idempotent.

    - Terminal run -> returns current status, no-op.
    - QUEUED & unclaimed -> cancelled immediately.
    - RUNNING -> marks cancel_requested + stage=CANCELLING; the worker
      terminates the method child process and finalizes as CANCELLED.
    """
    run_repo = RunRepository(db)
    file_repo = FileRepository(db)
    run = await _load_run_with_access(run_id, current_user=current_user, run_repo=run_repo)

    if run.status in TERMINAL_STATUSES:
        dataset_name, dataset_files = await _resolve_dataset_meta(run, file_repo)
        return _public_status(
            run, include_run_id=True, dataset_name=dataset_name, dataset_files=dataset_files
        )

    if run.status == RunStatus.QUEUED and getattr(run, "worker_lease_until", None) is None:
        cancelled = await run_repo.cancel_if_queued(run.id, "Cancelled by user")
        if not cancelled:
            # Worker claimed it between our read and write; request graceful cancel.
            await run_repo.request_cancel(run.id, "Cancelling...")
    else:
        await run_repo.request_cancel(run.id, "Cancelling...")

    refreshed = await run_repo.get_by_id(run.id) or run
    dataset_name, dataset_files = await _resolve_dataset_meta(refreshed, file_repo)
    return _public_status(
        refreshed, include_run_id=True, dataset_name=dataset_name, dataset_files=dataset_files
    )


@router.post("/{run_id}/cancel-queued")
async def cancel_queued_run(
    run_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a QUEUED run the user owns — whether it is the promoted turn or a plain
    personal-queue item. Cancelling the active turn promotes the user's next queued
    run; cancelling a personal-queue item disturbs no other user's ordering.

    Cancelling a RUNNING run is not handled here — use POST /runs/{run_id}/cancel,
    which drives the graceful worker-cancellation flow.
    """
    run_repo = RunRepository(db)
    file_repo = FileRepository(db)
    run = await _load_run_with_access(run_id, current_user=current_user, run_repo=run_repo)

    if run.status in TERMINAL_STATUSES:
        dataset_name, dataset_files = await _resolve_dataset_meta(run, file_repo)
        return _public_status(
            run, include_run_id=True, dataset_name=dataset_name, dataset_files=dataset_files
        )

    if run.status != RunStatus.QUEUED:
        # RUNNING (or otherwise claimed): defer to the graceful cancel flow.
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RUN_NOT_QUEUED",
                "message": "This run is no longer queued; use the cancel endpoint instead.",
            },
        )

    cancelled = await run_repo.cancel_queued_run(run.id, current_user.id, "Cancelled by user")
    if cancelled is None:
        # Raced with the worker claiming it; fall back to graceful cancel.
        await run_repo.request_cancel(run.id, "Cancelling...")

    refreshed = await run_repo.get_by_id(run.id) or run
    dataset_name, dataset_files = await _resolve_dataset_meta(refreshed, file_repo)
    return _public_status(
        refreshed, include_run_id=True, dataset_name=dataset_name, dataset_files=dataset_files
    )


@router.get("/current")
async def get_current_run(
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's active run (PENDING, QUEUED, or RUNNING), if any."""
    run_repo = RunRepository(db)
    file_repo = FileRepository(db)
    active = await run_repo.get_active_run_for_user(current_user.id)
    if not active:
        return {"run_id": None, "status": None, "progress": None, "message": None}

    dataset_name, dataset_files = await _resolve_dataset_meta(active, file_repo)
    return _public_status(
        active,
        include_run_id=True,
        dataset_name=dataset_name,
        dataset_files=dataset_files,
    )


@router.get("/dashboard")
async def get_dashboard(
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Live dashboard payload for the run queue: the active-turn run, the personal
    queue (FIFO), and quota limits. Returns only non-terminal runs — a finished run
    simply drops out of the payload (the client detects completion by diffing ids).
    """
    run_repo = RunRepository(db)
    file_repo = FileRepository(db)

    active = await run_repo.get_active_turn_run_for_user(current_user.id)
    queue = await run_repo.get_personal_queue_for_user(current_user.id)
    nonterminal = await run_repo.count_nonterminal_for_user(current_user.id)
    max_queued = run_quota.max_queued_runs()

    active_payload = None
    if active is not None:
        dataset_name, dataset_files = await _resolve_dataset_meta(active, file_repo)
        active_payload = _public_status(
            active,
            include_run_id=True,
            dataset_name=dataset_name,
            dataset_files=dataset_files,
        )

    return {
        "active": active_payload,
        "queue": [_run_summary(r) for r in queue],
        "limits": {
            "max_queued": max_queued,
            "queued_count": len(queue),
            "can_add": nonterminal < max_queued + 1,
        },
    }


@router.get("/quota")
async def get_run_quota(
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Where the current user stands against the limits on creating runs: the
    rolling hourly quota, the submission ceiling and the queue size. The same
    rules decide POST /runs, so a client can tell beforehand whether a new run
    would be accepted and, if not, why and until when.
    """
    quota = await run_quota.quota_state(RunRepository(db), current_user.id)
    return quota.as_dict()


# Declare same-dataset before other /{run_id}/... routes so the path "same-dataset" is matched
@router.get("/{run_id}/same-dataset")
async def list_same_dataset_runs(
    run_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """List DONE runs that used the same input file (dataset) as the given run."""
    try:
        run_repo = RunRepository(db)
        file_repo = FileRepository(db)
        run = await _load_run_with_access(run_id, current_user=current_user, run_repo=run_repo)
        input_file_id = getattr(run, "input_file_id", None)
        file_ids = []
        if input_file_id is not None:
            file_ids = [input_file_id]
        else:
            files = await file_repo.get_by_run(run.id)
            file_ids = [f.id for f in files]
        if not file_ids:
            return []
        same_runs = await run_repo.get_by_same_dataset_file_ids(
            file_ids,
            exclude_run_id=run.id,
            current_user_id=current_user.id,
            is_admin=bool(current_user.is_admin),
        )
        return [_run_summary(r) for r in same_runs]
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("Same-dataset lookup failed.", e, context=f"run_id={run_id}")


@router.get("/{run_id}/status")
async def run_status(
    run_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Get run status (status, progress, stage, stage_message, method_id, params, dataset, timestamps)."""
    run_repo = RunRepository(db)
    file_repo = FileRepository(db)
    run = await _load_run_with_access(run_id, current_user=current_user, run_repo=run_repo)

    dataset_name, dataset_files = await _resolve_dataset_meta(run, file_repo)
    return _public_status(run, dataset_name=dataset_name, dataset_files=dataset_files)


@router.get("/{run_id}/result")
async def run_result(
    run_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Get run result."""
    run_repo = RunRepository(db)
    file_repo = FileRepository(db)
    run = await _load_run_with_access(run_id, current_user=current_user, run_repo=run_repo)

    if run.status not in (RunStatus.DONE, RunStatus.ERROR, RunStatus.CANCELLED):
        raise HTTPException(409, "Run not finished")

    dataset_name, dataset_files = await _resolve_dataset_meta(run, file_repo)
    if isinstance(run.result, dict):
        base_result = dict(run.result)
    else:
        base_result = {"ok": run.status == RunStatus.DONE}

    if run.status in (RunStatus.ERROR, RunStatus.CANCELLED):
        raw_error = getattr(run, "error", None)
        parsed_error_payload: dict[str, Any] | None = None
        if isinstance(raw_error, str) and raw_error.strip():
            try:
                maybe_json = json.loads(raw_error)
                if isinstance(maybe_json, dict):
                    parsed_error_payload = maybe_json
            except Exception:
                parsed_error_payload = None

        if parsed_error_payload is not None:
            if "error" in parsed_error_payload:
                base_result.setdefault("error", parsed_error_payload.get("error"))
            if isinstance(parsed_error_payload.get("logs"), list):
                base_result.setdefault("logs", parsed_error_payload.get("logs"))

        if "error" not in base_result:
            base_result["error"] = run.message or "Run failed"
        base_result["ok"] = False
        if not isinstance(base_result.get("logs"), list):
            base_result["logs"] = []

    payload = dict(base_result)
    payload.setdefault("run_id", str(run.id))
    payload.setdefault("method_id", run.method_id)
    payload.setdefault("params", _normalized_run_params(run))
    payload.setdefault("dataset_name", dataset_name)
    payload.setdefault("dataset_files", dataset_files)
    _result_input_file_id = getattr(run, "input_file_id", None)
    payload.setdefault(
        "input_file_id", str(_result_input_file_id) if _result_input_file_id else None
    )
    payload.setdefault("started_at", run.started_at.isoformat() if run.started_at else None)
    payload.setdefault("finished_at", run.finished_at.isoformat() if run.finished_at else None)

    # Lightweight, base64-free additions: a dataset descriptor (incl. deletion
    # state for history) and an artifact count. Binaries are fetched lazily via
    # the /artifacts endpoints — never embedded here.
    payload["dataset"] = await _dataset_descriptor(run, file_repo)
    artifact_repo = ArtifactRepository(db)
    payload["artifact_count"] = await artifact_repo.count_for_run(run.id)
    return _attach_clone_ids_to_result_trees(payload)


@router.get("/{run_id}/trees")
async def list_run_trees(
    run_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """List lightweight tree metadata for a completed run."""
    run_repo = RunRepository(db)
    run = await _load_run_with_access(run_id, current_user=current_user, run_repo=run_repo)
    if run.status != RunStatus.DONE:
        raise HTTPException(409, "Run not finished")

    tree_repo = RunTreeRepository(db)
    trees = await tree_repo.list_for_run(run.id)
    clone_ids = _clone_ids_from_result_payload(run.result)
    if clone_ids:
        for tree in trees:
            tree_index = int(tree.get("treeIndex", -1))
            if tree_index < 0 or tree_index >= len(clone_ids):
                continue
            clone_id = clone_ids[tree_index]
            if clone_id:
                tree["cloneId"] = clone_id
    return {"trees": trees}


@router.get("/{run_id}/trees/{tree_id}")
async def get_run_tree_payload(
    run_id: str,
    tree_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Load full per-tree payload for a completed run."""
    run_repo = RunRepository(db)
    run = await _load_run_with_access(run_id, current_user=current_user, run_repo=run_repo)
    if run.status != RunStatus.DONE:
        raise HTTPException(409, "Run not finished")

    tree_repo = RunTreeRepository(db)
    payload = await tree_repo.get_tree_payload(run.id, tree_id)
    if payload is None:
        raise HTTPException(404, "Tree not found")
    return payload
