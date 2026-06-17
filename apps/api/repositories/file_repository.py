from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import exists, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.models import (
    ACTIVE_RUN_STATUSES,
    File,
    Run,
    StorageState,
    StorageType,
)
from apps.api.repositories.base_repository import BaseRepository
from apps.api.utils.datetime_util import utc_now


class FileRepository(BaseRepository[File]):
    """Repository for File model."""

    def __init__(self, session: AsyncSession):
        super().__init__(File, session)

    async def create_file(
        self,
        user_id: Optional[UUID],
        original_filename: str,
        storage_type: StorageType,
        storage_path: str,
        storage_url: Optional[str],
        file_size: int,
        mime_type: Optional[str] = None,
        run_id: Optional[UUID] = None,
        storage_bucket: Optional[str] = None,
        checksum_sha256: Optional[str] = None,
    ) -> File:
        """Create a new file record."""
        return await self.create(
            user_id=user_id,
            run_id=run_id,
            original_filename=original_filename,
            storage_type=storage_type,
            storage_path=storage_path,
            storage_url=storage_url,
            file_size=file_size,
            mime_type=mime_type,
            storage_bucket=storage_bucket,
            checksum_sha256=checksum_sha256,
        )

    async def get_by_run(self, run_id: UUID) -> List[File]:
        """Get all files for a run."""
        result = await self.session.execute(
            select(File).where(File.run_id == run_id)
        )
        return list(result.scalars().all())

    async def get_by_user(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> List[File]:
        """Get all files for a user."""
        result = await self.session.execute(
            select(File)
            .where(File.user_id == user_id)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_storage_path(self, storage_path: str) -> Optional[File]:
        """Get file by storage path."""
        result = await self.session.execute(
            select(File).where(File.storage_path == storage_path)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_user(self, file_id: UUID, user_id: UUID) -> Optional[File]:
        """Get file by ID only if it belongs to the user."""
        result = await self.session.execute(
            select(File).where(File.id == file_id, File.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_total_size_by_user(self, user_id: UUID) -> int:
        """Total bytes used by the user across their *active* (non-deleted) files.

        Deleted datasets no longer occupy storage, so they are excluded from quota.
        """
        result = await self.session.execute(
            select(func.coalesce(func.sum(File.file_size), 0)).where(
                File.user_id == user_id,
                File.storage_state == StorageState.ACTIVE,
            )
        )
        return int(result.scalar() or 0)

    async def is_referenced_by_run(self, file_id: UUID) -> bool:
        """Return True if any run uses this file (as input or attached upload)."""
        input_ref = await self.session.execute(
            select(exists().where(Run.input_file_id == file_id))
        )
        if bool(input_ref.scalar()):
            return True
        file_row = await self.get_by_id(file_id)
        if file_row is not None and file_row.run_id is not None:
            run_ref = await self.session.execute(
                select(exists().where(Run.id == file_row.run_id))
            )
            return bool(run_ref.scalar())
        return False

    async def is_referenced_by_active_run(self, file_id: UUID) -> List[UUID]:
        """Return the IDs of any active (PENDING/QUEUED/RUNNING) runs using this file.

        Used to block dataset deletion while a run is in-flight (avoids a worker
        failing mid-stage on a missing object).
        """
        result = await self.session.execute(
            select(Run.id).where(
                Run.input_file_id == file_id,
                Run.status.in_(ACTIVE_RUN_STATUSES),
            )
        )
        return list(result.scalars().all())

    async def mark_deleted(self, file_id: UUID, deleted_by: Optional[UUID]) -> File:
        """Soft-delete the dataset metadata row (object is hard-deleted separately).

        Idempotent: safe to call on an already-deleted row.
        """
        now = utc_now()
        file = await self.get_by_id(file_id)
        if file is None:
            raise ValueError(f"File not found: {file_id}")
        file.storage_state = StorageState.DELETED
        file.deleted_at = file.deleted_at or now
        file.object_deleted_at = file.object_deleted_at or now
        if deleted_by is not None:
            file.deleted_by = deleted_by
        await self.session.commit()
        await self.session.refresh(file)
        return file

    async def delete_file(self, file_id: UUID, user_id: UUID) -> Optional[str]:
        """Hard-delete a file row if it belongs to the user. Returns storage_path or None.

        Retained for pre-finalization/temporary-upload cleanup paths. For
        user-facing dataset deletion use the soft-delete flow (mark_deleted)
        which preserves historical run metadata.
        """
        file = await self.get_by_id_and_user(file_id, user_id)
        if not file:
            return None
        storage_path = file.storage_path
        await self.delete(file_id)
        return storage_path
