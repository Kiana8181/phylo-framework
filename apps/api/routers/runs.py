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
from apps.api.database.models import RunStatus, StorageType, User
from apps.api.preprocess.method_capabilities import extension_from_path, is_native_accept
from apps.api.preprocess.prepare_input import PreprocessError, prepare_input_for_method
from apps.api.repositories.file_repository import FileRepository
from apps.api.repositories.run_repository import RunRepository
from apps.api.storage import get_storage

router = APIRouter(prefix="/runs", tags=["runs"])

# Storage instance (singleton)
storage = get_storage()

METHOD_SERVICE_FILE_PREFIX = "METHOD_SERVICE_FILE_PREFIX"
HOST_RUNTIME_SHARED_ROOT = "HOST_RUNTIME_SHARED_ROOT"


def _runtime_shared_root_host() -> Path:
    raw = (os.getenv(HOST_RUNTIME_SHARED_ROOT) or str(ROOT_DIR / "runtime/storage")).strip()
    root = Path(raw)
    if not root.is_absolute():
        root = ROOT_DIR / root
    return root.resolve()


def _runtime_shared_root_container() -> Path:
    raw = (os.getenv(METHOD_SERVICE_FILE_PREFIX) or "/runtime/storage").strip()
    root = Path(raw)
    if not root.is_absolute():
        root = Path("/") / raw.lstrip("/")
    return root


def _run_work_dir(run_id: UUID) -> Path:
    path = _runtime_shared_root_host() / "runs" / str(run_id) / "work" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


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


async def stage_storage_path_to_workspace(storage_path: str, workspace: Path) -> Path:
    source = Path(storage_path)
    suffix = source.suffix.lower()
    staged = workspace / f"00_staged_input{suffix}"
    file_bytes = await storage.download(storage_path)
    staged.write_bytes(file_bytes)
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


def _public_status(run, include_run_id: bool = False) -> dict:
    """Convert Run model to public status dict."""
    out = {
        "status": run.status.value if hasattr(run.status, "value") else str(run.status),
        "progress": run.progress,
        "message": run.message,
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


async def _progress_updater(
    run_id: UUID,
    stop_event: asyncio.Event,
):
    """Gradually increase progress while waiting for method service response."""
    from apps.api.database.base import AsyncSessionLocal
    
    progress = 5
    max_progress = 90  # Don't go to 100% until we get the response
    increment = 3  # Increase by 3% each time
    interval = 3  # Update every 3 seconds
    
    while not stop_event.is_set() and progress < max_progress:
        await asyncio.sleep(interval)
        if stop_event.is_set():
            break
        progress = min(progress + increment, max_progress)
        try:
            async with AsyncSessionLocal() as db:
                run_repo = RunRepository(db)
                await run_repo.update_progress(run_id, progress, "Processing...")
                await db.commit()
        except Exception:
            # If run was deleted or error occurred, stop updating
            break


async def _execute_method_async(
    run_id: UUID,
    params: dict,
    file_path: Optional[str] = None,
):
    """Execute method in background (async version)."""
    # Create new database session for background task
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
        
        # Mark as QUEUED (in queue, worker has picked it up)
        await run_repo.update_status(run_id, RunStatus.QUEUED, "In queue")
        await db.commit()
        
        routes = get_service_routes(method_id) or {"run": "/run"}
        url = f"{base.rstrip('/')}{routes.get('run', '/run')}"
        
        # Update status to RUNNING when actually calling the method
        await run_repo.update_status(run_id, RunStatus.RUNNING, f"Submitting to {method_id}")
        await run_repo.update_progress(run_id, 5, f"Submitting to {method_id}")
        await db.commit()

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
                    existing_shared = _resolve_storage_path_under_shared_mount(original_storage_path)
                    if existing_shared is not None and existing_shared.is_file():
                        method_input_host_path = existing_shared
                    else:
                        run_workspace = _run_work_dir(run_id)
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
                    run_workspace = _run_work_dir(run_id)
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
                        prepared = prepare_input_for_method(
                            method_id=method_id,  # type: ignore[arg-type]
                            uploaded_path=staged_original,
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

                if method_input_host_path is None or not method_input_host_path.exists():
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
                    file_path = _to_container_path(method_input_host_path)
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

            # Start progress updater task
            stop_progress = asyncio.Event()
            progress_task = asyncio.create_task(
                _progress_updater(run_id, stop_progress)
            )

            try:
                # Use async httpx client
                async with httpx.AsyncClient(timeout=HTTP_CLIENT_TIMEOUT, trust_env=False) as client:
                    response = await client.post(url, json=payload)

                    # Stop progress updater
                    stop_progress.set()
                    try:
                        await asyncio.wait_for(progress_task, timeout=1.0)
                    except asyncio.TimeoutError:
                        progress_task.cancel()

                    if response.status_code >= 400:
                        err_msg = None
                        try:
                            j = response.json()
                            if isinstance(j, dict):
                                err_msg = j.get("error") or j.get("message")
                        except Exception:
                            pass
                        err_msg = err_msg or response.text or f"{response.status_code} {response.reason_phrase}"
                        await run_repo.set_error(run_id, err_msg)
                        await db.commit()
                        return

                    result = response.json()

                    # Save result to database with 100% progress
                    await run_repo.set_result(run_id, result, RunStatus.DONE)
                    await run_repo.update_progress(run_id, 100, "Complete")
                    await db.commit()

            except httpx.ConnectError as e:
                stop_progress.set()
                try:
                    await asyncio.wait_for(progress_task, timeout=1.0)
                except asyncio.TimeoutError:
                    progress_task.cancel()
                friendly = (
                    "Could not connect to the method service. "
                    "Make sure the service is running and METHOD_*_URL (e.g. METHOD_GCTREE_URL) is set correctly."
                )
                await run_repo.set_error(
                    run_id,
                    friendly + "\n\nTechnical detail: " + str(e),
                )
                await db.commit()
            except Exception as e:
                stop_progress.set()
                try:
                    await asyncio.wait_for(progress_task, timeout=1.0)
                except asyncio.TimeoutError:
                    progress_task.cancel()
                msg = str(e)
                error_detail = f"{msg}\n{traceback.format_exc()}"
                await run_repo.set_error(run_id, error_detail)
                await db.commit()
        finally:
            _cleanup_workspace(run_workspace, run_id)


def _run_summary(run) -> dict:
    """Build a run summary for list responses."""
    return {
        "id": str(run.id),
        "method_id": run.method_id,
        "status": run.status.value if hasattr(run.status, "value") else str(run.status),
        "progress": run.progress,
        "message": run.message,
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

    # Create run in database
    run = await run_repo.create_run(
        method_id=method,
        params=p,
        user_id=user_id,
    )

    file_path = None
    file_record = None

    # Use existing file by file_id (only when no new file uploaded)
    if file is None and file_id and file_id.strip() and user_id:
        try:
            existing_file_id = UUID(file_id.strip())
        except ValueError:
            raise HTTPException(400, "Invalid file_id format.")
        existing_file = await file_repo.get_by_id_and_user(existing_file_id, user_id)
        if not existing_file:
            raise HTTPException(404, "File not found or you do not have access to it.")
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
            
            # Update run with file path (for method service compatibility)
            # Method services expect file_path, so we'll pass storage_path
            file_path = storage_path_result
            
            # Update run status
            await run_repo.update_progress(run.id, 5, f"File uploaded: {file.filename}")
            
        except Exception as e:
            await run_repo.set_error(run.id, f"Failed to upload file: {e}")
            raise HTTPException(500, f"Failed to save upload: {e}")
    
    # Start background task
    # Background task will create its own database session
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
    active = await run_repo.get_active_run_for_user(current_user.id)
    if not active:
        return {"run_id": None, "status": None, "progress": None, "message": None}

    return _public_status(active, include_run_id=True)


@router.get("/{run_id}/status")
async def run_status(
    run_id: str,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get run status."""
    try:
        run_uuid = UUID(run_id)
    except ValueError:
        raise HTTPException(400, "Invalid run ID format")
    
    run_repo = RunRepository(db)
    run = await run_repo.get_by_id(run_uuid)
    
    if not run:
        raise HTTPException(404, "Run not found")
    
    # Check authorization (user can only see their own runs, unless admin)
    if current_user:
        if not current_user.is_admin and run.user_id != current_user.id:
            raise HTTPException(403, "Access denied")
    
    return _public_status(run)


@router.get("/{run_id}/result")
async def run_result(
    run_id: str,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get run result."""
    try:
        run_uuid = UUID(run_id)
    except ValueError:
        raise HTTPException(400, "Invalid run ID format")
    
    run_repo = RunRepository(db)
    run = await run_repo.get_by_id(run_uuid)
    
    if not run:
        raise HTTPException(404, "Run not found")
    
    # Check authorization
    if current_user:
        if not current_user.is_admin and run.user_id != current_user.id:
            raise HTTPException(403, "Access denied")
    
    if run.status != RunStatus.DONE:
        raise HTTPException(409, "Run not finished")
    
    return run.result or {"ok": False}
