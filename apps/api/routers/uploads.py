from __future__ import annotations

import hashlib
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
from apps.api.auth.verification import require_verified_user
from apps.api.config import STORAGE_QUOTA_PER_USER_BYTES
from apps.api.database import get_db
from apps.api.database.models import StorageType, UploadSessionStatus, User
from apps.api.repositories.file_repository import FileRepository
from apps.api.repositories.upload_session_repository import UploadSessionRepository
from apps.api.security.errors import internal_error
from apps.api.services import retention
from apps.api.storage import get_dataset_storage

router = APIRouter(prefix="/uploads", tags=["uploads"])

_storage_inst = None


def storage():
    """Lazily build the dataset storage client (avoids connecting at import time)."""
    global _storage_inst
    if _storage_inst is None:
        _storage_inst = get_dataset_storage()
    return _storage_inst


class _QuotaExceeded(Exception):
    pass


class _TooLarge(Exception):
    pass


def _megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):g} MB"


def _too_large_error() -> HTTPException:
    limit = retention.max_upload_bytes()
    return HTTPException(
        status_code=413,
        detail={
            "code": retention.CODE_UPLOAD_TOO_LARGE,
            "message": f"This file is larger than the {_megabytes(limit)} allowed for one upload.",
            "max_upload_bytes": limit,
        },
    )


@router.get("/limits")
async def upload_limits(
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """What the signed-in user may upload: the largest single file, and how
    much of the storage quota is left. Lets a client refuse a file before
    sending it."""
    used = await FileRepository(db).get_total_size_by_user(current_user.id)
    return {
        "max_upload_bytes": retention.max_upload_bytes(),
        "quota_bytes": STORAGE_QUOTA_PER_USER_BYTES,
        "used_bytes": used,
        "remaining_bytes": max(0, STORAGE_QUOTA_PER_USER_BYTES - used),
    }


class InitUploadBody(BaseModel):
    original_filename: str
    mime_type: Optional[str] = None
    expected_size: Optional[int] = None


def _ext_for(filename: str) -> str:
    if filename and "." in filename:
        return "." + filename.rsplit(".", 1)[1]
    return ""


def _is_local() -> bool:
    return storage().get_storage_type() == "local"


def _storage_type_enum() -> StorageType:
    t = storage().get_storage_type()
    if t == "s3":
        return StorageType.S3
    if t == "minio":
        return StorageType.MINIO
    return StorageType.LOCAL


def _temp_local_path(user_id: UUID, upload_id: UUID) -> Path:
    if _is_local():
        root = Path(storage().base_path) / "uploads" / "tmp" / str(user_id)
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
    # Uploading needs a confirmed email address (when that is required).
    current_user: User = Depends(require_verified_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an upload session. Returns upload_id + the content upload endpoint."""
    filename = (body.original_filename or "").strip() or "unknown"
    # Refused here, before a byte is sent, when the client says how large it is;
    # enforced again while the bytes arrive, whatever the client said.
    if body.expected_size is not None and body.expected_size > retention.max_upload_bytes():
        raise _too_large_error()
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
    current_user: User = Depends(require_verified_user),
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
    max_bytes = retention.max_upload_bytes()
    bytes_received = 0
    hasher = hashlib.sha256()

    try:
        async with aiofiles.open(tmp_path, "wb") as f:
            async for chunk in request.stream():
                if not chunk:
                    continue
                bytes_received += len(chunk)
                if bytes_received > max_bytes:
                    raise _TooLarge()
                if used + bytes_received > quota:
                    raise _QuotaExceeded()
                hasher.update(chunk)
                await f.write(chunk)
    except _TooLarge:
        _safe_unlink(str(tmp_path))
        await repo.mark_error(upload_id, "File larger than the upload limit")
        raise _too_large_error()
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
        raise internal_error("Upload failed.", exc, context=f"upload_id={upload_id}")

    if bytes_received == 0:
        _safe_unlink(str(tmp_path))
        await repo.mark_error(upload_id, "Empty upload")
        raise HTTPException(400, "No file content received.")

    # Store datasets under a dedicated prefix in the configured bucket.
    final_rel = f"datasets/{current_user.id}/{upload_id}{ext}"
    checksum_sha256 = hasher.hexdigest()
    try:
        if _is_local():
            tmp_rel = str(Path(tmp_path).resolve().relative_to(Path(storage().base_path).resolve()))
            final_storage_path = await storage().move(tmp_rel, final_rel)
        else:
            # Stream from disk into the object store (no full read into memory).
            final_storage_path = await storage().upload_file(
                str(tmp_path), final_rel, content_type=session.mime_type
            )
            _safe_unlink(str(tmp_path))
    except Exception as exc:
        _safe_unlink(str(tmp_path))
        await repo.mark_error(upload_id, f"Failed to store upload: {exc!s}")
        raise internal_error("Failed to store upload.", exc, context=f"upload_id={upload_id}")

    storage_url = await storage().get_url(final_storage_path)
    file_record = await file_repo.create_file(
        user_id=current_user.id,
        original_filename=session.original_filename,
        storage_type=_storage_type_enum(),
        storage_path=final_storage_path,
        storage_url=storage_url,
        file_size=bytes_received,
        mime_type=session.mime_type,
        storage_bucket=storage().bucket,
        checksum_sha256=checksum_sha256,
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
                    await storage().delete(storage_path)
                except Exception:
                    pass
            await repo.detach_final_file(upload_id)
        await repo.mark_cancelled(upload_id)
        return Response(status_code=204)

    return Response(status_code=204)
