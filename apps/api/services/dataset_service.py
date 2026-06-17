"""Dataset deletion: hard-delete the stored object, soft-delete the metadata row.

Shared by the /files and /datasets routers so both expose identical, idempotent
behavior:
  - object is physically removed from storage,
  - the File row is retained (soft-deleted) so historical runs keep dataset
    metadata (name/id/size/checksum) without the binary,
  - deletion is blocked while an active run still needs the dataset,
  - repeated deletes are safe.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.models import StorageState, User
from apps.api.repositories.file_repository import FileRepository


class DeleteOutcome(str, Enum):
    DELETED = "deleted"
    ALREADY_DELETED = "already_deleted"
    NOT_FOUND = "not_found"
    IN_USE = "in_use"


@dataclass
class DeleteResult:
    outcome: DeleteOutcome
    file_id: UUID | None = None
    active_run_ids: list[UUID] | None = None


async def delete_dataset(
    *,
    db: AsyncSession,
    storage,
    file_id: UUID,
    user: User,
) -> DeleteResult:
    """Delete a dataset for ``user``. Idempotent; preserves run history.

    Order: (1) verify ownership, (2) short-circuit if already deleted,
    (3) refuse if an active run needs it, (4) hard-delete the object,
    (5) soft-delete the row. Never touches run artifacts.
    """
    file_repo = FileRepository(db)
    f = await file_repo.get_by_id_and_user(file_id, user.id)
    if f is None:
        return DeleteResult(DeleteOutcome.NOT_FOUND)

    if f.storage_state == StorageState.DELETED:
        return DeleteResult(DeleteOutcome.ALREADY_DELETED, file_id=f.id)

    active_runs = await file_repo.is_referenced_by_active_run(file_id)
    if active_runs:
        return DeleteResult(
            DeleteOutcome.IN_USE, file_id=f.id, active_run_ids=active_runs
        )

    # Hard-delete the stored object (best-effort; tolerate already-missing).
    try:
        await storage.delete(f.storage_path)
    except Exception:
        pass

    await file_repo.mark_deleted(file_id, deleted_by=user.id)
    return DeleteResult(DeleteOutcome.DELETED, file_id=f.id)
