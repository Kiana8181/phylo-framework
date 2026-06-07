from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional
from uuid import UUID

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from apps.api.auth.dependencies import get_current_user_required
from apps.api.config import STORAGE_QUOTA_PER_USER_BYTES
from apps.api.database import get_db
from apps.api.database.models import StorageType, UploadSessionStatus, User
from apps.api.repositories.file_repository import FileRepository
from apps.api.repositories.upload_session_repository import UploadSessionRepository
from apps.api.storage import get_storage

router = APIRouter(prefix="/uploads", tags=["uploads"])
storage = get_storage()


class _QuotaExceeded(Exception):
    pass


class InitUploadBody(BaseModel):
    original_filename: str
    mime_type: Optional[str] = None
    expected_size: Optional[int] = None


def _ext_for(filename: str) -> str:
    if filename and "." in filename:
        return "." + filename.rsplit(".", 1)[1]
    return ""


def _is_local() -> bool:
    return storage.get_storage_type() == "local"


def _storage_type_enum() -> StorageType:
    t = storage.get_storage_type()
    if t == "s3":
        return StorageType.S3
    if t == "minio":
        return StorageType.MINIO
    return StorageType.LOCAL


def _temp_local_path(user_id: UUID, upload_id: UUID) -> Path:
    if _is_local():
        root = Path(storage.base_path) / "uploads" / "tmp" / str(user_id)
    else:
        root = Path(tempfile.gettempdir()) / "phylo-uploads" / str(user_id)
    return root / f"{upload_id}.part"


def _safe_unlink(path: Optional[str]) -> None:
    if not path:
        return
    try:
        p = Path(path)
        if p.exists():
            p.unlink()
    except Exception:
        pass


@router.post("/init")
async def init_upload(
    body: InitUploadBody,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Create an upload session. Returns upload_id + the content upload endpoint."""
    filename = (body.original_filename or "").strip() or "unknown"
    if body.expected_size is not None and body.expected_size > STORAGE_QUOTA_PER_USER_BYTES:
        raise HTTPException(413, "File exceeds your storage quota.")

    repo = UploadSessionRepository(db)
    session = await repo.create_session(
        user_id=current_user.id,
        original_filename=filename,
        mime_type=body.mime_type,
        expected_size=body.expected_size,
    )
    return {
        "upload_id": str(session.id),
        "content_url": f"/uploads/{session.id}/content",
        "status": session.status.value,
    }


@router.put("/{upload_id}/content")
async def upload_content(
    upload_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Receive the raw file body, persist to storage and create the File record."""
    repo = UploadSessionRepository(db)
    file_repo = FileRepository(db)
    session = await repo.get_by_id_and_user(upload_id, current_user.id)
    if session is None:
        raise HTTPException(404, "Upload session not found.")
    if session.status in (UploadSessionStatus.COMPLETED, UploadSessionStatus.CANCELLED):
        raise HTTPException(409, f"Upload session already {session.status.value}.")

    ext = _ext_for(session.original_filename)
    tmp_path = _temp_local_path(current_user.id, upload_id)
    tmp_path.parent.mkdir(parents=True, exist_ok=True)

    await repo.mark_uploading(upload_id, str(tmp_path))

    used = await file_repo.get_total_size_by_user(current_user.id)
    quota = STORAGE_QUOTA_PER_USER_BYTES
    bytes_received = 0

    try:
        async with aiofiles.open(tmp_path, "wb") as f:
            async for chunk in request.stream():
                if not chunk:
                    continue
                bytes_received += len(chunk)
                if used + bytes_received > quota:
                    raise _QuotaExceeded()
                await f.write(chunk)
    except _QuotaExceeded:
        _safe_unlink(str(tmp_path))
        await repo.mark_error(upload_id, "Storage quota exceeded")
        raise HTTPException(413, "Storage quota exceeded. Delete some files to free space.")
    except ClientDisconnect:
        # Browser aborted the upload. Leave cleanup to the explicit DELETE call,
        # but remove the partial temp file proactively.
        _safe_unlink(str(tmp_path))
        raise HTTPException(499, "Upload aborted by client.")
    except Exception as exc:
        _safe_unlink(str(tmp_path))
        await repo.mark_error(upload_id, f"Upload failed: {exc!s}")
        raise HTTPException(500, f"Upload failed: {exc!s}")

    if bytes_received == 0:
        _safe_unlink(str(tmp_path))
        await repo.mark_error(upload_id, "Empty upload")
        raise HTTPException(400, "No file content received.")

    final_rel = f"{current_user.id}/{upload_id}{ext}"
    try:
        if _is_local():
            tmp_rel = str(Path(tmp_path).resolve().relative_to(Path(storage.base_path).resolve()))
            final_storage_path = await storage.move(tmp_rel, final_rel)
        else:
            with open(tmp_path, "rb") as fh:
                final_storage_path = await storage.upload(fh, final_rel, session.mime_type)
            _safe_unlink(str(tmp_path))
    except Exception as exc:
        _safe_unlink(str(tmp_path))
        await repo.mark_error(upload_id, f"Failed to store upload: {exc!s}")
        raise HTTPException(500, f"Failed to store upload: {exc!s}")

    storage_url = await storage.get_url(final_storage_path)
    file_record = await file_repo.create_file(
        user_id=current_user.id,
        original_filename=session.original_filename,
        storage_type=_storage_type_enum(),
        storage_path=final_storage_path,
        storage_url=storage_url,
        file_size=bytes_received,
        mime_type=session.mime_type,
    )
    await repo.mark_completed(
        upload_id, final_file_id=file_record.id, bytes_received=bytes_received
    )

    return {
        "upload_id": str(upload_id),
        "file_id": str(file_record.id),
        "original_filename": file_record.original_filename,
        "file_size": file_record.file_size,
        "mime_type": file_record.mime_type,
        "storage_url": file_record.storage_url,
    }


@router.delete("/{upload_id}")
async def cancel_upload(
    upload_id: UUID,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Idempotently cancel an upload and clean up partial/temporary data.

    - INITIATED/UPLOADING/ERROR -> delete temp file + mark CANCELLED.
    - COMPLETED with an unreferenced final file -> delete the file + blob.
    - COMPLETED referenced by a run -> 409 (cannot cancel).
    Safe to call repeatedly.
    """
    repo = UploadSessionRepository(db)
    file_repo = FileRepository(db)
    session = await repo.get_by_id_and_user(upload_id, current_user.id)
    if session is None:
        # Idempotent: nothing to clean up.
        return Response(status_code=204)
    if session.status == UploadSessionStatus.CANCELLED:
        return Response(status_code=204)

    if session.status in (
        UploadSessionStatus.INITIATED,
        UploadSessionStatus.UPLOADING,
        UploadSessionStatus.ERROR,
    ):
        _safe_unlink(session.temp_storage_path)
        await repo.mark_cancelled(upload_id)
        return Response(status_code=204)

    if session.status == UploadSessionStatus.COMPLETED:
        final_file_id = session.final_file_id
        if final_file_id is not None:
            if await file_repo.is_referenced_by_run(final_file_id):
                raise HTTPException(
                    409,
                    "Upload already completed and is used by a run; it cannot be cancelled.",
                )
            storage_path = await file_repo.delete_file(final_file_id, current_user.id)
            if storage_path:
                try:
                    await storage.delete(storage_path)
                except Exception:
                    pass
            await repo.detach_final_file(upload_id)
        await repo.mark_cancelled(upload_id)
        return Response(status_code=204)

    return Response(status_code=204)
