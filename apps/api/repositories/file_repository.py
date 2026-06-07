from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import exists, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.models import File, Run, StorageType
from apps.api.repositories.base_repository import BaseRepository


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
        """Total bytes used by the user across all their files."""
        result = await self.session.execute(
            select(func.coalesce(func.sum(File.file_size), 0)).where(File.user_id == user_id)
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

    async def delete_file(self, file_id: UUID, user_id: UUID) -> Optional[str]:
        """Delete file by ID if it belongs to the user. Returns storage_path (for storage delete) or None."""
        file = await self.get_by_id_and_user(file_id, user_id)
        if not file:
            return None
        storage_path = file.storage_path
        await self.delete(file_id)
        return storage_path
