from __future__ import annotations

import asyncio
import json
import os
import shutil
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.dependencies import get_current_user, get_current_user_required
from apps.api.contracts.loader import get_service_routes, get_ui_hints
from apps.api.config import (
    HTTP_CLIENT_TIMEOUT,
    ROOT_DIR,
    STORAGE_QUOTA_PER_USER_BYTES,
    method_service_url,
)
from apps.api.database import get_db
from apps.api.database.models import ACTIVE_RUN_STATUSES, Run, RunStatus, StorageType, User
from apps.api.preprocess.method_capabilities import extension_from_path, is_native_accept
from apps.api.preprocess.prepare_input import PreprocessError, prepare_input_for_method
from apps.api.repositories.file_repository import FileRepository
from apps.api.repositories.run_repository import RunRepository
from apps.api.repositories.run_tree_repository import RunTreeRepository
from apps.api.services.tree_contract import assemble_unified_tree_result
from apps.api.storage import get_storage

router = APIRouter(prefix="/runs", tags=["runs"])

# Storage instance (singleton)
storage = get_storage()

METHOD_SERVICE_FILE_PREFIX = "METHOD_SERVICE_FILE_PREFIX"
HOST_RUNTIME_SHARED_ROOT = "HOST_RUNTIME_SHARED_ROOT"
STORAGE_LOCAL_PATH = "STORAGE_LOCAL_PATH"
DEFAULT_CONTAINER_RUNTIME_ROOT = Path("/runtime/storage")


def _storage_local_root_host() -> Path:
    raw = (os.getenv(STORAGE_LOCAL_PATH) or "runtime/storage").strip()
    root = Path(raw)
    if not root.is_absolute():
        root = ROOT_DIR / root
    return root.resolve()


def _runtime_shared_root_host() -> Path:
    raw = (os.getenv(HOST_RUNTIME_SHARED_ROOT) or "").strip()
    if not raw:
        return _storage_local_root_host()

    root = Path(raw)
    if not root.is_absolute():
        root = ROOT_DIR / root
        return root.resolve()

    # Guard against a common local-dev misconfiguration where a container-only
    # mount path is copied into host config.
    if root == DEFAULT_CONTAINER_RUNTIME_ROOT or DEFAULT_CONTAINER_RUNTIME_ROOT in root.parents:
        return _storage_local_root_host()
    return root.resolve()


def _runtime_shared_root_container() -> Path:
    raw = (os.getenv(METHOD_SERVICE_FILE_PREFIX) or "/runtime/storage").strip()
    root = Path(raw)
    if not root.is_absolute():
        root = Path("/") / raw.lstrip("/")
    return root


def _run_work_dir_sync(run_id: UUID) -> Path:
    """Sync helper: create work dir and return path. Use via asyncio.to_thread to avoid blocking."""
    path = _runtime_shared_root_host() / "runs" / str(run_id) / "work" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _run_work_dir(run_id: UUID) -> Path:
    """Create work dir for run; runs in thread to avoid blocking event loop."""
    return await asyncio.to_thread(_run_work_dir_sync, run_id)


def _to_container_path(host_path: Path) -> str:
    shared = _runtime_shared_root_host().resolve()
    rel = host_path.resolve().relative_to(shared)
    return (_runtime_shared_root_container() / rel).as_posix()


def _resolve_storage_path_under_shared_mount(storage_path: str) -> Path | None:
    shared = _runtime_shared_root_host().resolve()
    raw_path = Path(storage_path)
    candidates: list[Path] = []

    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.append(shared / raw_path)
        base_path = getattr(storage, "base_path", None)
        if isinstance(base_path, Path):
            candidates.append(base_path / raw_path)

    seen: set[str] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if not resolved.exists():
            continue
        try:
            resolved.relative_to(shared)
            return resolved
        except ValueError:
            continue
    return None


def _path_is_file(p: Path) -> bool:
    """Sync helper for Path.is_file(); use via asyncio.to_thread to avoid blocking."""
    return p.is_file()


def _path_exists(p: Path) -> bool:
    """Sync helper for Path.exists(); use via asyncio.to_thread to avoid blocking."""
    return p.exists()


def _write_bytes_to_path(path: Path, data: bytes) -> None:
    """Sync helper for writing bytes to path (used in thread to avoid blocking)."""
    path.write_bytes(data)


async def stage_storage_path_to_workspace(storage_path: str, workspace: Path) -> Path:
    source = Path(storage_path)
    suffix = source.suffix.lower()
    staged = workspace / f"00_staged_input{suffix}"
    file_bytes = await storage.download(storage_path)
    # Large writes would block the event loop; run in thread
    await asyncio.to_thread(_write_bytes_to_path, staged, file_bytes)
    return staged


def _cleanup_workspace(workspace: Path | None, run_id: UUID) -> None:
    if workspace is None:
        return
    if not workspace.exists():
        return

    allowed_root = (_runtime_shared_root_host() / "runs" / str(run_id) / "work").resolve()
    try:
        workspace.resolve().relative_to(allowed_root)
    except ValueError:
        return

    shutil.rmtree(workspace, ignore_errors=True)


def _structured_error_payload(
    *,
    code: str,
    message: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message, "details": details}}


def _extract_error_message(value: Any) -> str | None:
    if isinstance(value, str):
        txt = value.strip()
        return txt or None
    if isinstance(value, dict):
        msg = value.get("message")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()
        code = value.get("code")
        if isinstance(code, str) and code.strip():
            return code.strip()
    return None


def _normalize_failed_result_payload(
    raw_payload: Any,
    *,
    status_code: int | None = None,
    fallback_message: str | None = None,
) -> tuple[dict[str, Any], str]:
    payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
    payload["ok"] = False

    error_message = _extract_error_message(payload.get("error"))
    if not error_message:
        error_message = _extract_error_message(payload.get("message"))
    if not error_message and fallback_message:
        cleaned = fallback_message.strip()
        if cleaned:
            error_message = cleaned
    if not error_message and status_code is not None:
        error_message = f"Method service returned HTTP {status_code}."
    if not error_message:
        error_message = "Method service execution failed."

    payload.setdefault("error", error_message)
    if not isinstance(payload.get("logs"), list):
        payload["logs"] = []
    return payload, error_message


async def _set_failed_run_with_payload(
    run_repo: RunRepository,
    run_id: UUID,
    *,
    error_message: str,
    result_payload: dict[str, Any] | None = None,
) -> None:
    payload, normalized_error = _normalize_failed_result_payload(
        result_payload,
        fallback_message=error_message,
    )
    await run_repo.update(
        run_id,
        status=RunStatus.ERROR,
        error=normalized_error,
        message=normalized_error,
        progress=100,
        result=payload,
        finished_at=datetime.utcnow(),
    )


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
    """Convert Run model to public status dict."""
    resolved_dataset_name = dataset_name
    if resolved_dataset_name is None:
        raw_dataset_name = getattr(run, "dataset_name", None)
        resolved_dataset_name = raw_dataset_name if isinstance(raw_dataset_name, str) else None

    resolved_dataset_files = dataset_files if dataset_files is not None else []
    if not resolved_dataset_files and resolved_dataset_name:
        resolved_dataset_files = [resolved_dataset_name]

    out = {
        "status": run.status.value if hasattr(run.status, "value") else str(run.status),
        "progress": run.progress,
        "message": run.message,
        "method_id": run.method_id,
        "params": _normalized_run_params(run),
        "dataset_name": resolved_dataset_name,
        "dataset_files": resolved_dataset_files,
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


async def _load_run_with_access(
    run_id: str,
    *,
    current_user: Optional[User],
    run_repo: RunRepository,
) -> Run:
    try:
        run_uuid = UUID(run_id)
    except ValueError:
        raise HTTPException(400, "Invalid run ID format")

    run = await run_repo.get_by_id(run_uuid)
    if not run:
        raise HTTPException(404, "Run not found")

    if current_user and not current_user.is_admin and run.user_id != current_user.id:
        raise HTTPException(403, "Access denied")
    return run


async def _progress_updater(
    run_id: UUID,
    stop_event: asyncio.Event,
):
    """Gradually increase progress while waiting for method service response."""
    from apps.api.database.base import AsyncSessionLocal

    max_progress = 90  # Don't go to 100% until we get the response
    increment = 3  # Increase by 3% each time
    interval = 3  # Update every 3 seconds

    while not stop_event.is_set():
        await asyncio.sleep(interval)
        if stop_event.is_set():
            break
        try:
            async with AsyncSessionLocal() as db:
                run_repo = RunRepository(db)
                run = await run_repo.get_by_id(run_id)
                if run is None:
                    break
                if run.status not in ACTIVE_RUN_STATUSES:
                    break

                current_progress = int(run.progress or 0)
                if current_progress >= max_progress:
                    break

                next_progress = min(current_progress + increment, max_progress)
                updated = await run_repo.update_progress(run_id, next_progress, "Processing...")
                if updated is None:
                    break
                await db.commit()
        except Exception:
            # If run was deleted or error occurred, stop updating
            break


async def _pending_run_executor_loop() -> None:
    """Periodically pick up PENDING runs that were never started (e.g. after server reload).
    Runs every 15s and schedules execution for runs PENDING for more than 15s."""
    from apps.api.database.base import AsyncSessionLocal

    while True:
        await asyncio.sleep(15)
        try:
            async with AsyncSessionLocal() as db:
                run_repo = RunRepository(db)
                file_repo = FileRepository(db)
                stale = await run_repo.get_stale_pending_runs(age_seconds=15, limit=3)
                for run in stale:
                    file_path: Optional[str] = None
                    if run.input_file_id:
                        f = await file_repo.get_by_id(run.input_file_id)
                        if f:
                            file_path = f.storage_path
                    if file_path is None:
                        files = await file_repo.get_by_run(run.id)
                        if files:
                            file_path = files[0].storage_path
                    params = run.params if isinstance(run.params, dict) else {}
                    asyncio.create_task(_execute_method_async(run.id, params, file_path))
        except asyncio.CancelledError:
            break
        except Exception:
            traceback.print_exc()


async def _execute_method_async(
    run_id: UUID,
    params: dict,
    file_path: Optional[str] = None,
):
    """Execute method in background. All blocking work runs in thread pool via asyncio.to_thread."""
    from apps.api.database.base import AsyncSessionLocal

    try:
        await _execute_method_async_impl(run_id, params, file_path)
    except Exception as e:
        traceback.print_exc()
        try:
            async with AsyncSessionLocal() as db:
                run_repo = RunRepository(db)
                await _set_failed_run_with_payload(
                    run_repo,
                    run_id,
                    error_message=f"Run failed: {e!s}",
                    result_payload={
                        "ok": False,
                        "error": f"Run failed: {e!s}",
                        "logs": [
                            {
                                "step": "api.worker.unhandled",
                                "ok": False,
                                "out": str(e),
                            }
                        ],
                    },
                )
                await db.commit()
        except Exception:
            pass


async def _execute_method_async_impl(
    run_id: UUID,
    params: dict,
    file_path: Optional[str],
):
    """Inner implementation; exceptions are caught by _execute_method_async."""
    from apps.api.database.base import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        run_repo = RunRepository(db)
        run = await run_repo.get_by_id(run_id)

        if not run:
            return

        method_id = run.method_id
        base = method_service_url(method_id)
        
        if not base:
            msg = f"No service URL configured for method '{method_id}'. Set METHOD_{method_id.upper()}_URL."
            await run_repo.set_error(run_id, msg)
            await db.commit()
            return

        # Claim run and set RUNNING immediately so the run is not stuck in PENDING
        # (e.g. if get_service_routes or staging hangs later, UI still shows RUNNING).
        claimed = await run_repo.transition_to_running_once(run_id, f"Submitting to {method_id}")
        if not claimed:
            await db.rollback()
            return
        await db.commit()

        # Contracts loader does sync file I/O; run in thread so event loop stays responsive
        routes = await asyncio.to_thread(get_service_routes, method_id) or {"run": "/run"}
        url = f"{base.rstrip('/')}{routes.get('run', '/run')}"

        # Start progress updater immediately so status/progress update during staging and POST
        stop_progress = asyncio.Event()
        progress_task = asyncio.create_task(_progress_updater(run_id, stop_progress))

        # Stage files to the shared runtime mount whenever needed so method-services
        # always receive a container-visible filesystem path.
        run_workspace: Path | None = None
        method_input_host_path: Path | None = None

        try:
            if file_path:
                original_storage_path = file_path
                input_ext = extension_from_path(Path(original_storage_path))

                native_ok = False
                try:
                    native_ok = is_native_accept(method_id, input_ext)  # type: ignore[arg-type]
                except Exception:
                    native_ok = False

                if native_ok:
                    existing_shared = await asyncio.to_thread(
                        _resolve_storage_path_under_shared_mount, original_storage_path
                    )
                    if existing_shared is not None and await asyncio.to_thread(_path_is_file, existing_shared):
                        method_input_host_path = existing_shared
                    else:
                        run_workspace = await _run_work_dir(run_id)
                        try:
                            method_input_host_path = await stage_storage_path_to_workspace(
                                original_storage_path,
                                run_workspace,
                            )
                        except Exception as exc:
                            structured = _structured_error_payload(
                                code="INVALID_FILE",
                                message="Failed to read uploaded file for method execution.",
                                details={
                                    "method_id": method_id,
                                    "storage_path": original_storage_path,
                                    "next_actions": [
                                        "Re-upload the input file and retry.",
                                        "If the file came from file history, verify it still exists.",
                                    ],
                                    "technical_error": str(exc),
                                },
                            )
                            await run_repo.set_error(run_id, json.dumps(structured, ensure_ascii=True, sort_keys=True))
                            await run_repo.update(run_id, message=structured["error"]["message"])
                            await db.commit()
                            return
                else:
                    run_workspace = await _run_work_dir(run_id)
                    try:
                        staged_original = await stage_storage_path_to_workspace(
                            original_storage_path,
                            run_workspace,
                        )
                    except Exception as exc:
                        structured = _structured_error_payload(
                            code="INVALID_FILE",
                            message="Failed to read uploaded file for preprocessing.",
                            details={
                                "method_id": method_id,
                                "storage_path": original_storage_path,
                                "next_actions": [
                                    "Re-upload the input file and retry.",
                                    "If the file came from file history, verify it still exists.",
                                ],
                                "technical_error": str(exc),
                            },
                        )
                        await run_repo.set_error(run_id, json.dumps(structured, ensure_ascii=True, sort_keys=True))
                        await run_repo.update(run_id, message=structured["error"]["message"])
                        await db.commit()
                        return

                    try:
                        # Run sync preprocessing in a thread to avoid blocking the event loop
                        prepared = await asyncio.to_thread(
                            prepare_input_for_method,
                            method_id,  # type: ignore[arg-type]
                            staged_original,
                            params=params or {},
                            work_dir=run_workspace,
                        )
                        method_input_host_path = prepared.final_path
                    except PreprocessError as exc:
                        structured = _structured_error_payload(
                            code=exc.code,
                            message=exc.message,
                            details=exc.details,
                        )
                        await run_repo.set_error(run_id, json.dumps(structured, ensure_ascii=True, sort_keys=True))
                        await run_repo.update(run_id, message=exc.message)
                        await db.commit()
                        return

                path_exists = (
                    await asyncio.to_thread(_path_exists, method_input_host_path)
                    if method_input_host_path is not None
                    else False
                )
                if method_input_host_path is None or not path_exists:
                    structured = _structured_error_payload(
                        code="INVALID_FILE",
                        message="Prepared input file is missing on the API server.",
                        details={
                            "method_id": method_id,
                            "storage_path": original_storage_path,
                            "next_actions": [
                                "Retry the run.",
                                "Re-upload the input file if the issue persists.",
                            ],
                        },
                    )
                    await run_repo.set_error(run_id, json.dumps(structured, ensure_ascii=True, sort_keys=True))
                    await run_repo.update(run_id, message=structured["error"]["message"])
                    await db.commit()
                    return

                try:
                    file_path = await asyncio.to_thread(_to_container_path, method_input_host_path)
                except Exception as exc:
                    structured = _structured_error_payload(
                        code="INTERNAL_PATH_ERROR",
                        message="Prepared input is outside the shared runtime mount.",
                        details={
                            "method_id": method_id,
                            "host_path": str(method_input_host_path),
                            "shared_root": str(_runtime_shared_root_host()),
                            "next_actions": [
                                "Contact support and include this run ID.",
                            ],
                            "technical_error": str(exc),
                        },
                    )
                    await run_repo.set_error(run_id, json.dumps(structured, ensure_ascii=True, sort_keys=True))
                    await run_repo.update(run_id, message=structured["error"]["message"])
                    await db.commit()
                    return

                container_root = _runtime_shared_root_container().as_posix().rstrip("/")
                if file_path != container_root and not file_path.startswith(f"{container_root}/"):
                    structured = _structured_error_payload(
                        code="INTERNAL_PATH_ERROR",
                        message="Method input path is not under the shared container runtime root.",
                        details={
                            "method_id": method_id,
                            "file_path": file_path,
                            "container_root": container_root,
                            "next_actions": [
                                "Contact support and include this run ID.",
                            ],
                        },
                    )
                    await run_repo.set_error(run_id, json.dumps(structured, ensure_ascii=True, sort_keys=True))
                    await run_repo.update(run_id, message=structured["error"]["message"])
                    await db.commit()
                    return

            # Prepare payload
            payload = {
                "file_path": file_path,
                "params": params or {},
            }

            try:
                # Use async httpx client
                async with httpx.AsyncClient(timeout=HTTP_CLIENT_TIMEOUT, trust_env=False) as client:
                    response = await client.post(url, json=payload)

                    if response.status_code >= 400:
                        raw_payload: Any = None
                        try:
                            raw_payload = response.json()
                        except Exception:
                            raw_payload = None

                        fallback = response.text or f"{response.status_code} {response.reason_phrase}"
                        failed_payload, err_msg = _normalize_failed_result_payload(
                            raw_payload,
                            status_code=response.status_code,
                            fallback_message=fallback,
                        )
                        logs = failed_payload.get("logs")
                        if isinstance(logs, list):
                            logs.append(
                                {
                                    "step": "api.method.http",
                                    "ok": False,
                                    "out": f"HTTP {response.status_code} from method service endpoint {url}",
                                }
                            )
                        await _set_failed_run_with_payload(
                            run_repo,
                            run_id,
                            error_message=err_msg,
                            result_payload=failed_payload,
                        )
                        await db.commit()
                        return

                    result = response.json()
                    unified_result, tree_rows = await asyncio.to_thread(
                        assemble_unified_tree_result, method_id, result
                    )

                    # Save unified result and per-tree payloads.
                    await run_repo.set_result(run_id, unified_result, RunStatus.DONE)
                    tree_repo = RunTreeRepository(db)
                    await tree_repo.replace_for_run(run_id, tree_rows)
                    await db.commit()

            except httpx.ConnectError as e:
                friendly = (
                    "Could not connect to the method service. "
                    "Make sure the service is running and METHOD_*_URL (e.g. METHOD_GCTREE_URL) is set correctly."
                )
                detail = friendly + "\n\nTechnical detail: " + str(e)
                await _set_failed_run_with_payload(
                    run_repo,
                    run_id,
                    error_message=detail,
                    result_payload={
                        "ok": False,
                        "error": detail,
                        "logs": [
                            {
                                "step": "api.method.connect",
                                "ok": False,
                                "out": str(e),
                            }
                        ],
                    },
                )
                await db.commit()
            except Exception as e:
                msg = str(e)
                error_detail = f"{msg}\n{traceback.format_exc()}"
                await _set_failed_run_with_payload(
                    run_repo,
                    run_id,
                    error_message=msg or "Run failed",
                    result_payload={
                        "ok": False,
                        "error": msg or "Run failed",
                        "logs": [
                            {
                                "step": "api.method.unhandled",
                                "ok": False,
                                "out": error_detail,
                            }
                        ],
                    },
                )
                await db.commit()
        finally:
            stop_progress.set()
            try:
                await asyncio.wait_for(progress_task, timeout=2.0)
            except asyncio.TimeoutError:
                progress_task.cancel()
            # Cleanup can be slow (rmtree); run in thread to avoid blocking event loop
            if run_workspace is not None:
                await asyncio.to_thread(_cleanup_workspace, run_workspace, run_id)


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
        "params": _normalized_run_params(run),
        "dataset_name": dataset_name,
        "dataset_files": [dataset_name] if dataset_name else [],
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@router.get("")
async def list_runs(
    current_user: User = Depends(get_current_user_required),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """List current user's runs (auth required)."""
    run_repo = RunRepository(db)
    runs = await run_repo.get_by_user(current_user.id, skip=skip, limit=limit)
    return [_run_summary(r) for r in runs]


@router.post("")
async def create_run(
    background: BackgroundTasks,
    method: str = Query(..., description="Method ID (e.g., 'dowser')"),
    params: str = Form("{}", description="JSON string of parameters"),
    file: UploadFile | None = File(None),
    file_id: Optional[str] = Form(None),
    current_user: Optional[User] = Depends(get_current_user),  # Optional auth
    db: AsyncSession = Depends(get_db),
):
    """Create a new run. Send either file (new upload) or file_id (existing file), or both (file takes precedence)."""
    base = method_service_url(method)
    if not base:
        raise HTTPException(
            400,
            f"No service URL configured for method '{method}'. Set METHOD_{method.upper()}_URL.",
        )

    ui_hints = get_ui_hints(method)
    requires_file = ui_hints.get("requiresFile", True)

    # Parse params
    try:
        p = json.loads(params or "{}")
        if not isinstance(p, dict):
            raise ValueError("params must be a JSON object")
    except Exception as e:
        raise HTTPException(400, f"Invalid params JSON: {e}")

    run_repo = RunRepository(db)
    file_repo = FileRepository(db)

    user_id = current_user.id if current_user else None

    # When method requires file, require either upload or file_id
    if requires_file and file is None and not (file_id and file_id.strip()):
        raise HTTPException(
            400,
            "This method requires an input file. Upload a file or select a previously uploaded file.",
        )

    # One active run per user: reject if user already has a run in PENDING/QUEUED/RUNNING
    if user_id:
        active = await run_repo.get_active_run_for_user(user_id)
        if active:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "RUN_IN_PROGRESS",
                    "message": "You already have a run in progress. Wait for it to finish or check its status.",
                    "run_id": str(active.id),
                    "status": active.status.value if hasattr(active.status, "value") else str(active.status),
                    "progress": active.progress,
                    "message": active.message,
                },
            )

    # Resolve existing file when file_id is provided (so we can set input_file_id on run)
    existing_file = None
    if file is None and file_id and file_id.strip() and user_id:
        try:
            existing_file_id = UUID(file_id.strip())
        except ValueError:
            raise HTTPException(400, "Invalid file_id format.")
        existing_file = await file_repo.get_by_id_and_user(existing_file_id, user_id)
        if not existing_file:
            raise HTTPException(404, "File not found or you do not have access to it.")

    # Create run in database
    run = await run_repo.create_run(
        method_id=method,
        params=p,
        user_id=user_id,
        input_file_id=existing_file.id if existing_file else None,
        dataset_name=existing_file.original_filename if existing_file else None,
    )

    file_path = None
    file_record = None

    if existing_file:
        file_path = existing_file.storage_path

    # Handle new file upload (takes precedence over file_id)
    if file is not None:
        # Generate unique file path
        file_ext = ""
        if file.filename:
            if "." in file.filename:
                file_ext = "." + file.filename.rsplit(".", 1)[1]

        storage_path = f"{run.id}/{uuid.uuid4()}{file_ext}"

        # Read file content
        file_content = await file.read()
        file_size = len(file_content)

        # Enforce per-user storage quota
        if user_id:
            total_used = await file_repo.get_total_size_by_user(user_id)
            if total_used + file_size > STORAGE_QUOTA_PER_USER_BYTES:
                raise HTTPException(
                    413,
                    "Storage quota exceeded. Delete some files in File management to free space.",
                )

        # Upload to storage
        try:
            storage_path_result = await storage.upload(
                file_content=file_content,
                file_path=storage_path,
                content_type=file.content_type,
            )
            
            # Get storage URL
            storage_url = await storage.get_url(storage_path_result)
            
            # Determine storage type
            storage_type = StorageType.LOCAL
            if storage.get_storage_type() == "s3":
                storage_type = StorageType.S3
            elif storage.get_storage_type() == "minio":
                storage_type = StorageType.MINIO
            
            # Create file record
            file_record = await file_repo.create_file(
                user_id=user_id,  # Can be None for anonymous users
                original_filename=file.filename or "unknown",
                storage_type=storage_type,
                storage_path=storage_path_result,
                storage_url=storage_url,
                file_size=file_size,
                mime_type=file.content_type,
                run_id=run.id,
            )
            await run_repo.update(
                run.id,
                input_file_id=file_record.id,
                dataset_name=file_record.original_filename,
            )

            # Update run with file path (for method service compatibility)
            # Method services expect file_path, so we'll pass storage_path
            file_path = storage_path_result

            # Update run status
            await run_repo.update_progress(run.id, 5, f"File uploaded: {file.filename}")
            await db.commit()
            
        except Exception as e:
            await run_repo.set_error(run.id, f"Failed to upload file: {e}")
            raise HTTPException(500, f"Failed to save upload: {e}")
    
    # Run on main event loop; blocking ops (file I/O, contracts, preprocessing) use asyncio.to_thread
    background.add_task(_execute_method_async, run.id, p, file_path)

    return {"run_id": str(run.id)}


@router.get("/current")
async def get_current_run(
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current user's active run (PENDING, QUEUED, or RUNNING), if any.
    Returns 200 with run_id: null when no active run (so the client does not see an error).
    Requires authentication.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

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


# Declare same-dataset before other /{run_id}/... routes so the path "same-dataset" is matched
@router.get("/{run_id}/same-dataset")
async def list_same_dataset_runs(
    run_id: str,
    current_user: Optional[User] = Depends(get_current_user),
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
            # Fallback: runs created before input_file_id may have a file linked via run_id (upload)
            files = await file_repo.get_by_run(run.id)
            file_ids = [f.id for f in files]
        if not file_ids:
            return []
        user_id = current_user.id if current_user else None
        is_admin = getattr(current_user, "is_admin", False) if current_user else False
        same_runs = await run_repo.get_by_same_dataset_file_ids(
            file_ids,
            exclude_run_id=run.id,
            current_user_id=user_id,
            is_admin=is_admin,
        )
        return [_run_summary(r) for r in same_runs]
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Same-dataset lookup failed: {e!s}")


@router.get("/{run_id}/status")
async def run_status(
    run_id: str,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get run status."""
    run_repo = RunRepository(db)
    file_repo = FileRepository(db)
    run = await _load_run_with_access(run_id, current_user=current_user, run_repo=run_repo)

    dataset_name, dataset_files = await _resolve_dataset_meta(run, file_repo)
    return _public_status(run, dataset_name=dataset_name, dataset_files=dataset_files)


@router.get("/{run_id}/result")
async def run_result(
    run_id: str,
    current_user: Optional[User] = Depends(get_current_user),
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
    payload.setdefault("started_at", run.started_at.isoformat() if run.started_at else None)
    payload.setdefault("finished_at", run.finished_at.isoformat() if run.finished_at else None)
    return _attach_clone_ids_to_result_trees(payload)


@router.get("/{run_id}/trees")
async def list_run_trees(
    run_id: str,
    current_user: Optional[User] = Depends(get_current_user),
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
    current_user: Optional[User] = Depends(get_current_user),
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
