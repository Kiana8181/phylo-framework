"""Removal of uploaded datasets that are past their date.

A sibling of result retention: the worker calls it from the same loop, on the
same cadence, and it never touches run results. For each dataset whose
``expires_at`` has passed and whose file is still stored:

  1. lock the row and read the date again, so a renewal that landed after this
     sweep listed the dataset is not acted on;
  2. leave it alone when a run that is still queued or running needs it;
  3. delete the object from the dataset store;
  4. only when that object is gone: soft-delete the row (``deleted_by`` stays
     empty, so this is distinguishable from a deletion the owner performed).

The lock is held across the object delete. Renewal takes the same row lock, so
the two cannot interleave: renewal either commits a new date before the lock,
or it observes the soft-deleted row afterwards and is rejected.

If the store cannot be reached, or the object is still there after the delete
call, the row stays active and the next sweep tries again. A dataset with no
``expires_at`` (retention off, or not yet backfilled) is never selected.
"""
from __future__ import annotations

import logging
from uuid import UUID

from apps.api.database.base import AsyncSessionLocal
from apps.api.repositories.file_repository import FileRepository
from apps.api.services import retention
from apps.api.storage import get_dataset_storage

logger = logging.getLogger("phylo.api.dataset_retention")

BATCH_SIZE = 50
_storage = None


def _dataset_storage():
    global _storage
    if _storage is None:
        _storage = get_dataset_storage()
    return _storage


async def _object_removed(path: str) -> bool:
    """True when the object is gone. False when a delete left it in place."""
    store = _dataset_storage()
    existed = await store.exists(path)
    await store.delete(path)
    if existed and await store.exists(path):
        return False
    return True


async def expire_dataset(file_id: UUID) -> str:
    """Remove one expired dataset. ``expired``, ``deferred``, ``retry`` or ``skipped``."""
    async with AsyncSessionLocal() as db:
        repo = FileRepository(db)
        row = await repo.lock_due_for_expiry(file_id)
        if row is None:
            return "skipped"
        if await repo.is_referenced_by_active_run(file_id):
            logger.info("dataset %s is past its date but a run still needs it; left in place", file_id)
            return "deferred"
        path = row.storage_path
        try:
            removed = await _object_removed(path)
        except Exception as exc:  # noqa: BLE001 - the store is away or refuses
            logger.warning("dataset %s not removed yet, will retry: %s", file_id, type(exc).__name__)
            return "retry"
        if not removed:
            logger.warning("dataset %s still in storage after delete, will retry", file_id)
            return "retry"
        await repo.mark_deleted(file_id, deleted_by=None)
    logger.info("dataset expired file=%s", file_id)
    return "expired"


async def sweep(limit: int = BATCH_SIZE) -> dict[str, int]:
    """One pass: expire every dataset that is due (up to ``limit``)."""
    if retention.dataset_retention_period() is None:
        return {}
    async with AsyncSessionLocal() as db:
        due = await FileRepository(db).datasets_due_for_expiry(limit)
    counts = {"expired": 0, "retry": 0, "deferred": 0}
    for file_id in due:
        try:
            outcome = await expire_dataset(file_id)
        except Exception:  # noqa: BLE001 - one dataset must not stop the others
            logger.exception("could not expire dataset %s", file_id)
            outcome = "retry"
        if outcome in counts:
            counts[outcome] += 1
    return {k: v for k, v in counts.items() if v}
