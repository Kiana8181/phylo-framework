from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.dependencies import get_current_user_required
from apps.api.database import get_db
from apps.api.database.models import StorageState, User
from apps.api.repositories.file_repository import FileRepository
from apps.api.services.dataset_service import DeleteOutcome, delete_dataset
from apps.api.services.fasta_id_style import (
    STYLE_PLAIN,
    classify_fasta_headers,
    extract_fasta_headers,
)
from apps.api.storage import get_dataset_storage

router = APIRouter(prefix="/datasets", tags=["datasets"])

# Enough of the file to see every header in any realistic clonal-family FASTA.
FASTA_PEEK_BYTES = 256 * 1024
FASTA_EXTENSIONS = (".fasta", ".fa", ".fna", ".faa", ".fas")

_storage_inst = None


def storage():
    """Lazily build the dataset storage client (avoids connecting at import time)."""
    global _storage_inst
    if _storage_inst is None:
        _storage_inst = get_dataset_storage()
    return _storage_inst


@router.get("/{dataset_id}/download")
async def download_dataset(
    dataset_id: UUID,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Stream the original uploaded dataset. 404 if missing, 410 if deleted."""
    file_repo = FileRepository(db)
    f = await file_repo.get_by_id_and_user(dataset_id, current_user.id)
    if f is None:
        raise HTTPException(404, "Dataset not found or you do not have access to it.")
    if f.storage_state == StorageState.DELETED:
        raise HTTPException(410, "This dataset has been deleted.")

    filename = f.original_filename or "dataset"
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
    }
    if f.file_size:
        headers["Content-Length"] = str(f.file_size)
    return StreamingResponse(
        storage().stream_download(f.storage_path),
        media_type=f.mime_type or "application/octet-stream",
        headers=headers,
    )


@router.get("/{dataset_id}/fasta-id-style")
async def dataset_fasta_id_style(
    dataset_id: UUID,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Report whether a FASTA dataset uses gctree's ``name@abundance`` headers.

    Lets the run form ask what the number after ``@`` means without downloading
    the whole dataset — only the first chunk is read, which is far more than
    enough headers to classify by.
    """
    file_repo = FileRepository(db)
    f = await file_repo.get_by_id_and_user(dataset_id, current_user.id)
    if f is None:
        raise HTTPException(404, "Dataset not found or you do not have access to it.")
    if f.storage_state == StorageState.DELETED:
        raise HTTPException(410, "This dataset has been deleted.")

    name = (f.original_filename or "").lower()
    if not name.endswith(FASTA_EXTENSIONS):
        return {"style": STYLE_PLAIN, "headers_checked": 0, "truncated": False}

    buf = bytearray()
    truncated = False
    async for chunk in storage().stream_download(f.storage_path):
        buf.extend(chunk)
        if len(buf) >= FASTA_PEEK_BYTES:
            truncated = True
            break

    headers = extract_fasta_headers(
        bytes(buf[:FASTA_PEEK_BYTES]).decode("utf-8", errors="ignore"),
        truncated=truncated,
    )
    return {
        "style": classify_fasta_headers(headers),
        "headers_checked": len(headers),
        "truncated": truncated,
    }


@router.delete("/{dataset_id}")
async def delete_dataset_endpoint(
    dataset_id: UUID,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete the stored object + soft-delete the row. Idempotent.

    409 if an active run still needs the dataset; never deletes run artifacts.
    """
    result = await delete_dataset(
        db=db, storage=storage(), file_id=dataset_id, user=current_user
    )
    if result.outcome == DeleteOutcome.NOT_FOUND:
        raise HTTPException(404, "Dataset not found or you do not have access to it.")
    if result.outcome == DeleteOutcome.IN_USE:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DATASET_IN_USE",
                "message": "Dataset is used by a run that is still in progress. "
                "Cancel or wait for that run before deleting.",
                "run_ids": [str(r) for r in (result.active_run_ids or [])],
            },
        )
    if result.outcome == DeleteOutcome.ALREADY_DELETED:
        return JSONResponse(status_code=200, content={"status": "already_deleted"})
    return JSONResponse(status_code=200, content={"status": "deleted"})
