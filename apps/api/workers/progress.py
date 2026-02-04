from __future__ import annotations

from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from apps.api.database.models.run import Run, RunStatus


async def update_run_progress(
    session: AsyncSession,
    run_id: str,
    progress: int,
    message: str | None = None,
    floor: int = 10,
    ceiling: int = 95
) -> None:
    """Update run progress in database."""
    result = await session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    
    if run and run.status == RunStatus.RUNNING:
        current_progress = run.progress or floor
        new_progress = min(max(current_progress, progress), ceiling)
        run.progress = new_progress
        if message:
            run.message = message
        await session.commit()

