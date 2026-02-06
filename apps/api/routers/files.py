from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.dependencies import get_current_user_required
from apps.api.config import STORAGE_QUOTA_PER_USER_BYTES
from apps.api.database import get_db
from apps.api.database.models import User
from apps.api.repositories.file_repository import FileRepository
from apps.api.storage import get_storage

router = APIRouter(prefix="/files", tags=["files"])
storage = get_storage()


def _file_summary(f) -> dict:
    """Build a file summary for list responses."""
    return {
        "id": str(f.id),
        "original_filename": f.original_filename,
        "file_size": f.file_size,
        "mime_type": f.mime_type,
        "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None,
        "run_id": str(f.run_id) if f.run_id else None,
        "storage_url": f.storage_url,
    }


@router.get("")
async def list_files(
    current_user: User = Depends(get_current_user_required),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """List current user's files with storage quota (auth required)."""
    file_repo = FileRepository(db)
    files = await file_repo.get_by_user(current_user.id, skip=skip, limit=limit)
    total_bytes_used = await file_repo.get_total_size_by_user(current_user.id)
    return {
        "files": [_file_summary(f) for f in files],
        "total_bytes_used": total_bytes_used,
        "quota_bytes": STORAGE_QUOTA_PER_USER_BYTES,
    }


@router.delete("/{file_id}")
async def delete_file(
    file_id: UUID,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Delete a file (auth required; must own the file). Returns 204."""
    file_repo = FileRepository(db)
    storage_path = await file_repo.delete_file(file_id, current_user.id)
    if storage_path is None:
        raise HTTPException(404, "File not found or you do not have access to it.")
    try:
        await storage.delete(storage_path)
    except Exception:
        pass  # Ignore if file already missing on disk
    return Response(status_code=204)
