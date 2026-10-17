"""Removal of results that are past their date.

A separate task of the worker (like notifications): it shares nothing with run
processing but the database and the object store, and it only ever looks at
runs that have ended.

For each run whose ``expires_at`` has passed and whose results are still there:
  1. delete its files from the artifact store — everything under the run's own
     prefix, which also catches files of a failed run that were uploaded but
     never registered;
  2. only when that succeeded: mark its artifact rows deleted, remove its
     trees, stored result and settled notification, and mark the run expired.

The order makes the operation safe to repeat and safe to interrupt. If the
store cannot be reached, nothing in the database changes and the run is tried
again at the next sweep; if the process dies between the two steps, the next
sweep finds no files left and completes the second step. A run is never marked
expired while any of its files might still exist, and a run that is waiting or
running is never touched.
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Optional
from uuid import UUID

from apps.api.database.base import AsyncSessionLocal
from apps.api.repositories.artifact_repository import ArtifactRepository
from apps.api.repositories.run_repository import RunRepository
from apps.api.services import retention
from apps.api.storage import get_artifact_storage

logger = logging.getLogger("phylo.api.retention")

BATCH_SIZE = 50
_storage = None


def _artifact_storage():
    global _storage
    if _storage is None:
        _storage = get_artifact_storage()
    return _storage


def run_prefix(run_id: UUID) -> str:
    """Where a run's files live in the artifact store (see the method services'
    object_storage: ``artifacts/<run_id>/<job_id>/<file>``)."""
    return f"artifacts/{run_id}/"


async def expire_run(run_id: UUID) -> bool:
    """Remove one run's results. True when the run is now marked expired.

    Does nothing unless the run has ended and is past its date: the check is
    made here, immediately before the files are deleted, and not only when the
    list of due runs was drawn up."""
    async with AsyncSessionLocal() as db:
        if not await RunRepository(db).is_due_for_expiry(run_id):
            return False
    try:
        deleted = await _artifact_storage().delete_prefix(run_prefix(run_id))
    except Exception as exc:  # noqa: BLE001 - the store is away or refuses
        logger.warning("results of run %s not removed yet, will retry: %s", run_id, type(exc).__name__)
        return False
    async with AsyncSessionLocal() as db:
        # One transaction: the artifact rows and the run change together.
        await ArtifactRepository(db).mark_all_deleted_for_run(run_id)
        marked = await RunRepository(db).mark_results_expired(run_id)
    if marked:
        logger.info("results expired run=%s files_removed=%d", run_id, deleted)
    return marked


async def sweep(limit: int = BATCH_SIZE) -> dict[str, int]:
    """One pass: expire every run that is due (up to ``limit``)."""
    if retention.retention_period() is None:
        return {}
    async with AsyncSessionLocal() as db:
        due = await RunRepository(db).runs_due_for_expiry(limit)
    counts = {"expired": 0, "retry": 0}
    for run_id in due:
        try:
            counts["expired" if await expire_run(run_id) else "retry"] += 1
        except Exception:  # noqa: BLE001 - one run must not stop the others
            logger.exception("could not expire run %s", run_id)
            counts["retry"] += 1
    return {k: v for k, v in counts.items() if v}


async def retention_loop(stop: Optional[asyncio.Event] = None) -> None:
    """Sweep until cancelled. Never raises: this must not take the worker down."""
    days = retention.result_retention_days()
    if days > 0:
        logger.info("result retention: %g days after a run ends", days)
    else:
        logger.warning("result retention is off (RESULT_RETENTION_DAYS=0): results are never removed")
    while stop is None or not stop.is_set():
        try:
            await sweep()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        await asyncio.sleep(retention.sweep_seconds())
