"""Dataset deletion and renewal.

Shared by the /files and /datasets routers so both expose identical behavior.

Deletion:
  - object is physically removed from storage,
  - the File row is retained (soft-deleted) so historical runs keep dataset
    metadata (name/id/size/checksum) without the binary,
  - deletion is blocked while an active run still needs the dataset,
  - repeated deletes are safe.

Renewal:
  - only the owner, only while the dataset is still stored and inside the
    configured warning window,
  - the new date is ``now + DATASET_RETENTION_DAYS``, not the old date plus
    that period,
  - an expired or deleted dataset is not brought back.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.models import File, StorageState, User
from apps.api.repositories.file_repository import FileRepository
from apps.api.services import retention
from apps.api.utils.datetime_util import utc_now


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


APPROACHING_LIMIT = 50


def file_public_summary(f: File, now: Optional[datetime] = None) -> dict:
    """Dataset fields the file panel and the renewal response may show.

    ``renewal_eligible`` is decided here from configuration. Callers display it;
    they do not recompute the warning window.
    """
    state = f.storage_state.value if hasattr(f.storage_state, "value") else str(f.storage_state)
    moment = now or utc_now()
    expires = f.expires_at
    return {
        "id": str(f.id),
        "original_filename": f.original_filename,
        "file_size": f.file_size,
        "mime_type": f.mime_type,
        "checksum_sha256": f.checksum_sha256,
        "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None,
        "run_id": str(f.run_id) if f.run_id else None,
        "storage_state": state,
        "expires_at": expires.isoformat() if expires else None,
        "renewal_eligible": retention.renewal_eligible(expires, moment),
    }


class RenewOutcome(str, Enum):
    RENEWED = "renewed"
    NOT_FOUND = "not_found"
    DELETED = "deleted"
    EXPIRED = "expired"
    NOT_ELIGIBLE = "not_eligible"
    RETENTION_OFF = "retention_off"


@dataclass
class RenewResult:
    outcome: RenewOutcome
    file: File | None = None


async def renew_dataset(
    *,
    db: AsyncSession,
    file_id: UUID,
    user: User,
    now: Optional[datetime] = None,
) -> RenewResult:
    """Give ``user``'s dataset a fresh retention period, starting at ``now``.

    The row is locked so a cleanup that already decided the old date is due
    either finishes first (this then sees a deleted row) or waits and then
    sees the new date.
    """
    moment = now or utc_now()
    file = await FileRepository(db).lock_owned(file_id, user.id)
    if file is None:
        return RenewResult(RenewOutcome.NOT_FOUND)
    if file.storage_state == StorageState.DELETED:
        return RenewResult(RenewOutcome.DELETED, file=file)
    period = retention.dataset_retention_period()
    if period is None:
        return RenewResult(RenewOutcome.RETENTION_OFF, file=file)
    expires = file.expires_at
    if expires is not None and retention._aware(expires) <= retention._aware(moment):
        return RenewResult(RenewOutcome.EXPIRED, file=file)
    if not retention.renewal_eligible(expires, moment):
        return RenewResult(RenewOutcome.NOT_ELIGIBLE, file=file)
    file.expires_at = moment + period
    await db.commit()
    await db.refresh(file)
    return RenewResult(RenewOutcome.RENEWED, file=file)
