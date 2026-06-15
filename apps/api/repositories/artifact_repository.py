from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.models import ArtifactKind, RunArtifact, StorageState
from apps.api.utils.datetime_util import utc_now


class ArtifactRepository:
    """Repository for the run_artifacts table (object-storage references)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def replace_for_run(self, run_id: UUID, artifacts: list[dict[str, Any]]) -> list[RunArtifact]:
        """Replace all artifact rows for a run with the provided list (idempotent).

        Each dict carries the storage reference + metadata produced by the
        ArtifactService after uploading the object. No binary/base64 is stored.
        """
        await self.session.execute(delete(RunArtifact).where(RunArtifact.run_id == run_id))
        rows: list[RunArtifact] = []
        for item in artifacts:
            kind = item.get("artifact_kind", ArtifactKind.OTHER)
            if isinstance(kind, str):
                kind = ArtifactKind(kind)
            row_kwargs: dict[str, Any] = {}
            if item.get("id") is not None:
                row_kwargs["id"] = item["id"]
            row = RunArtifact(
                **row_kwargs,
                run_id=run_id,
                tree_id=(str(item["tree_id"]) if item.get("tree_id") else None),
                storage_backend=str(item.get("storage_backend") or ""),
                storage_bucket=item.get("storage_bucket"),
                object_key=str(item["object_key"]),
                filename=str(item.get("filename") or "artifact"),
                content_type=item.get("content_type"),
                size_bytes=int(item.get("size_bytes") or 0),
                checksum_sha256=item.get("checksum_sha256"),
                artifact_kind=kind,
                artifact_role=item.get("artifact_role"),
                is_previewable=bool(item.get("is_previewable", False)),
            )
            self.session.add(row)
            rows.append(row)
        # Flush (not commit) so the caller can persist trees + artifacts atomically.
        await self.session.flush()
        return rows

    async def list_for_run(
        self,
        run_id: UUID,
        *,
        include_deleted: bool = False,
        exclude_tree_images: bool = False,
    ) -> list[RunArtifact]:
        stmt = select(RunArtifact).where(RunArtifact.run_id == run_id)
        if not include_deleted:
            stmt = stmt.where(RunArtifact.storage_state == StorageState.ACTIVE)
        if exclude_tree_images:
            # Per-tree rendered images are surfaced inline in the tree carousel
            # via the /artifacts/{id}/preview endpoint; hide them from the
            # Downloads list so users only see standalone artifacts (bundle ZIP,
            # full log file, etc.).
            stmt = stmt.where(
                RunArtifact.tree_id.is_(None),
                RunArtifact.artifact_role != "phylogeny",
            )
        stmt = stmt.order_by(RunArtifact.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, artifact_id: UUID) -> Optional[RunArtifact]:
        result = await self.session.execute(
            select(RunArtifact).where(RunArtifact.id == artifact_id)
        )
        return result.scalar_one_or_none()

    async def count_for_run(self, run_id: UUID) -> int:
        result = await self.session.execute(
            select(RunArtifact.id).where(
                RunArtifact.run_id == run_id,
                RunArtifact.storage_state == StorageState.ACTIVE,
            )
        )
        return len(list(result.scalars().all()))

    async def mark_deleted(self, artifact: RunArtifact) -> None:
        """Soft-delete an artifact row (object hard-deleted separately). Idempotent."""
        artifact.storage_state = StorageState.DELETED
        artifact.object_deleted_at = artifact.object_deleted_at or utc_now()
        await self.session.commit()
