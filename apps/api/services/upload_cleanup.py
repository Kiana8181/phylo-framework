"""Cleanup of uploads that were started and never finished.

Runs inside the API process, because that is where partial uploads are written
(a temporary file per upload, see routers/uploads.py). An upload that has not
completed within UPLOAD_SESSION_GRACE_HOURS is given up: its temporary file is
removed and its session is marked cancelled. Temporary files that belong to no
session any more (for example after the API was restarted mid-upload) are
removed after the same time.

Completed uploads, i.e. the user's datasets, are never touched here: they stay
until their owner deletes them.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
import time
import traceback
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from apps.api.database.base import AsyncSessionLocal
from apps.api.database.models import UploadSession, UploadSessionStatus
from apps.api.repositories.upload_session_repository import UploadSessionRepository
from apps.api.services import retention
from apps.api.utils.datetime_util import utc_now

logger = logging.getLogger("phylo.api.retention")

UNFINISHED = (UploadSessionStatus.INITIATED, UploadSessionStatus.UPLOADING, UploadSessionStatus.ERROR)
BATCH_SIZE = 200


def temp_roots() -> list[Path]:
    """Directories partial uploads are written to (see uploads._temp_local_path)."""
    roots = [Path(tempfile.gettempdir()) / "phylo-uploads"]
    try:
        from apps.api.routers import uploads

        if uploads._is_local():
            roots.append(Path(uploads.storage().base_path) / "uploads" / "tmp")
    except Exception:  # noqa: BLE001 - storage not reachable right now
        pass
    return roots


def _unlink(path: Optional[str]) -> bool:
    if not path:
        return False
    try:
        Path(path).unlink()
        return True
    except OSError:
        return False


def remove_stray_temp_files(max_age_seconds: float, now: Optional[float] = None) -> int:
    """Delete partial-upload files older than ``max_age_seconds``. Returns how
    many files were removed.

    The per-user directories are left in place even when empty: an upload
    creates its directory first and opens its file a moment later, and a
    directory removed in between would make that upload fail. An empty
    directory costs nothing worth that."""
    now = time.time() if now is None else now
    removed = 0
    for root in temp_roots():
        if not root.is_dir():
            continue
        for part in root.glob("*/*.part"):
            try:
                if now - part.stat().st_mtime > max_age_seconds:
                    part.unlink()
                    removed += 1
            except OSError:
                continue
    return removed


async def sweep() -> dict[str, int]:
    """One pass. Returns what was cleaned up."""
    grace = retention.upload_session_grace()
    cutoff = utc_now() - grace
    async with AsyncSessionLocal() as db:
        stale = (
            await db.execute(
                select(UploadSession)
                .where(UploadSession.status.in_(UNFINISHED), UploadSession.created_at < cutoff)
                .order_by(UploadSession.created_at.asc())
                .limit(BATCH_SIZE)
            )
        ).scalars().all()
        repo = UploadSessionRepository(db)
        for session in stale:
            _unlink(session.temp_storage_path)
            await repo.mark_cancelled(session.id)
    files = await asyncio.to_thread(remove_stray_temp_files, grace.total_seconds())
    counts = {"sessions": len(stale), "files": files}
    if any(counts.values()):
        logger.info("abandoned uploads cleaned up: %d session(s), %d stray file(s)", len(stale), files)
    return {k: v for k, v in counts.items() if v}


async def upload_cleanup_loop(stop: Optional[asyncio.Event] = None) -> None:
    """Sweep until cancelled. Never raises: this must not take the API down."""
    while stop is None or not stop.is_set():
        try:
            await sweep()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        await asyncio.sleep(retention.sweep_seconds())
