from __future__ import annotations

from typing import Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.dependencies import get_current_user
from apps.api.database import get_db
from apps.api.database.models import RunArtifact, StorageState, User
from apps.api.repositories.artifact_repository import ArtifactRepository
from apps.api.repositories.run_repository import RunRepository
from apps.api.storage import get_artifact_storage

router = APIRouter(tags=["artifacts"])

_storage_inst = None


def storage():
    """Lazily build the artifact storage client (avoids connecting at import time)."""
    global _storage_inst
    if _storage_inst is None:
        _storage_inst = get_artifact_storage()
    return _storage_inst


def _artifact_kind(a: RunArtifact) -> str:
    k = a.artifact_kind
    return k.value if hasattr(k, "value") else str(k)


def _descriptor(a: RunArtifact) -> dict:
    """Public artifact descriptor — API URLs only, never internal object keys."""
    return {
        "id": str(a.id),
        "filename": a.filename,
        "content_type": a.content_type,
        "size_bytes": a.size_bytes,
        "checksum_sha256": a.checksum_sha256,
        "artifact_kind": _artifact_kind(a),
        "artifact_role": a.artifact_role,
        "is_previewable": bool(a.is_previewable),
        "tree_id": a.tree_id,
        "download_url": f"/artifacts/{a.id}/download",
        "preview_url": f"/artifacts/{a.id}/preview" if a.is_previewable else None,
    }


async def _run_owned_or_403(run_id: UUID, current_user: Optional[User], db: AsyncSession):
    run = await RunRepository(db).get_by_id(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    if run.user_id is not None and current_user is None:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    if current_user and not current_user.is_admin and run.user_id != current_user.id:
        raise HTTPException(403, "Access denied")
    return run


async def _load_artifact_or_404(
    artifact_id: UUID, current_user: Optional[User], db: AsyncSession
) -> RunArtifact:
    artifact = await ArtifactRepository(db).get_by_id(artifact_id)
    if artifact is None:
        raise HTTPException(404, "Artifact not found")
    await _run_owned_or_403(artifact.run_id, current_user, db)
    return artifact


@router.get("/runs/{run_id}/artifacts")
async def list_run_artifacts(
    run_id: UUID,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List artifact descriptors for a run (metadata only; lazy binaries).

    Per-tree rendered images are intentionally excluded — they're already
    shown inline in the tree carousel via /artifacts/{id}/preview, and the
    Downloads UI should only list standalone outputs (bundle ZIP, log file).
    """
    await _run_owned_or_403(run_id, current_user, db)
    artifacts = await ArtifactRepository(db).list_for_run(
        run_id, exclude_tree_images=True
    )
    return {"artifacts": [_descriptor(a) for a in artifacts]}


def _stream(artifact: RunArtifact, *, disposition: str) -> StreamingResponse:
    filename = artifact.filename or "artifact"
    headers = {
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}",
    }
    if artifact.size_bytes:
        headers["Content-Length"] = str(artifact.size_bytes)
    return StreamingResponse(
        storage().stream_download(artifact.object_key),
        media_type=artifact.content_type or "application/octet-stream",
        headers=headers,
    )


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: UUID,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream an artifact as an attachment. 410 if the object was deleted."""
    artifact = await _load_artifact_or_404(artifact_id, current_user, db)
    if artifact.storage_state == StorageState.DELETED:
        raise HTTPException(410, "This artifact has been deleted.")
    return _stream(artifact, disposition="attachment")


@router.get("/artifacts/{artifact_id}/preview")
async def preview_artifact(
    artifact_id: UUID,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream a previewable artifact inline (images/pdf/text). 415 otherwise."""
    artifact = await _load_artifact_or_404(artifact_id, current_user, db)
    if artifact.storage_state == StorageState.DELETED:
        raise HTTPException(410, "This artifact has been deleted.")
    if not artifact.is_previewable:
        raise HTTPException(415, "This artifact is not previewable; use the download endpoint.")
    return _stream(artifact, disposition="inline")
