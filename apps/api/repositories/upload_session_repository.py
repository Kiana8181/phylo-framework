from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.models import UploadSession, UploadSessionStatus
from apps.api.repositories.base_repository import BaseRepository


class UploadSessionRepository(BaseRepository[UploadSession]):
    """Repository for UploadSession model."""

    def __init__(self, session: AsyncSession):
        super().__init__(UploadSession, session)

    async def create_session(
        self,
        user_id: UUID,
        original_filename: str,
        mime_type: Optional[str] = None,
        expected_size: Optional[int] = None,
    ) -> UploadSession:
        return await self.create(
            user_id=user_id,
            original_filename=original_filename,
            mime_type=mime_type,
            expected_size=expected_size,
            status=UploadSessionStatus.INITIATED,
            bytes_received=0,
        )

    async def get_by_id_and_user(
        self, upload_id: UUID, user_id: UUID
    ) -> Optional[UploadSession]:
        result = await self.session.execute(
            select(UploadSession).where(
                UploadSession.id == upload_id,
                UploadSession.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def mark_uploading(
        self, upload_id: UUID, temp_storage_path: str
    ) -> Optional[UploadSession]:
        return await self.update(
            upload_id,
            status=UploadSessionStatus.UPLOADING,
            temp_storage_path=temp_storage_path,
        )

    async def mark_completed(
        self,
        upload_id: UUID,
        *,
        final_file_id: UUID,
        bytes_received: int,
    ) -> Optional[UploadSession]:
        return await self.update(
            upload_id,
            status=UploadSessionStatus.COMPLETED,
            final_file_id=final_file_id,
            bytes_received=bytes_received,
            temp_storage_path=None,
            completed_at=datetime.utcnow(),
        )

    async def mark_cancelled(self, upload_id: UUID) -> Optional[UploadSession]:
        return await self.update(
            upload_id,
            status=UploadSessionStatus.CANCELLED,
            temp_storage_path=None,
            cancelled_at=datetime.utcnow(),
        )

    async def mark_error(self, upload_id: UUID, error: str) -> Optional[UploadSession]:
        return await self.update(
            upload_id,
            status=UploadSessionStatus.ERROR,
            error=error,
        )

    async def detach_final_file(self, upload_id: UUID) -> Optional[UploadSession]:
        """Clear final_file_id link (used when the completed file is deleted on cancel)."""
        return await self.update(upload_id, final_file_id=None)
