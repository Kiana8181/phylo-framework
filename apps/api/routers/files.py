from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.dependencies import get_current_user_required
from apps.api.config import STORAGE_QUOTA_PER_USER_BYTES
from apps.api.database import get_db
from apps.api.database.models import StorageState, User
from apps.api.repositories.file_repository import FileRepository
from apps.api.services.dataset_service import DeleteOutcome, delete_dataset
from apps.api.storage import get_dataset_storage

router = APIRouter(prefix="/files", tags=["files"])

_storage_inst = None


def storage():
    """Lazily build the dataset storage client (avoids connecting at import time)."""
    global _storage_inst
    if _storage_inst is None:
        _storage_inst = get_dataset_storage()
    return _storage_inst


def _file_summary(f) -> dict:
    """Build a file summary for list responses (no internal storage paths)."""
    state = f.storage_state.value if hasattr(f.storage_state, "value") else str(f.storage_state)
    return {
        "id": str(f.id),
        "original_filename": f.original_filename,
        "file_size": f.file_size,
        "mime_type": f.mime_type,
        "checksum_sha256": f.checksum_sha256,
        "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None,
        "run_id": str(f.run_id) if f.run_id else None,
        "storage_state": state,
    }


@router.get("")
async def list_files(
    current_user: User = Depends(get_current_user_required),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """List current user's *active* datasets with storage quota (auth required).

    Deleted datasets are omitted from the file panel; their metadata is still
    visible in run history via the run result's dataset descriptor.
    """
    file_repo = FileRepository(db)
    files = await file_repo.get_by_user(current_user.id, skip=skip, limit=limit)
    active = [f for f in files if f.storage_state != StorageState.DELETED]
    total_bytes_used = await file_repo.get_total_size_by_user(current_user.id)
    return {
        "files": [_file_summary(f) for f in active],
        "total_bytes_used": total_bytes_used,
        "quota_bytes": STORAGE_QUOTA_PER_USER_BYTES,
    }


@router.delete("/{file_id}")
async def delete_file(
    file_id: UUID,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Delete a dataset: hard-delete the object, soft-delete the metadata row.

    Idempotent; preserves run history; refuses while an active run needs it.
    """
    result = await delete_dataset(
        db=db, storage=storage(), file_id=file_id, user=current_user
    )
    if result.outcome == DeleteOutcome.NOT_FOUND:
        raise HTTPException(404, "File not found or you do not have access to it.")
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
