from __future__ import annotations

from typing import Optional, List
from uuid import UUID
from datetime import datetime

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.models import Run, RunStatus, ACTIVE_RUN_STATUSES
from apps.api.repositories.base_repository import BaseRepository


class RunRepository(BaseRepository[Run]):
    """Repository for Run model with specific methods."""

    def __init__(self, session: AsyncSession):
        super().__init__(Run, session)

    async def create_run(
        self,
        method_id: str,
        params: dict,
        user_id: Optional[UUID] = None,
    ) -> Run:
        """Create a new run."""
        return await self.create(
            method_id=method_id,
            params=params,
            user_id=user_id,
            status=RunStatus.PENDING,
            progress=0,
            message="Queued",
        )

    async def get_active_run_for_user(self, user_id: UUID) -> Optional[Run]:
        """Get the current active run for a user (PENDING, QUEUED, or RUNNING). At most one."""
        result = await self.session.execute(
            select(Run)
            .where(Run.user_id == user_id)
            .where(Run.status.in_(ACTIVE_RUN_STATUSES))
            .order_by(Run.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_by_user(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Run]:
        """Get all runs for a user."""
        result = await self.session.execute(
            select(Run)
            .where(Run.user_id == user_id)
            .order_by(Run.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_status(
        self,
        status: RunStatus,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Run]:
        """Get all runs with a specific status."""
        result = await self.session.execute(
            select(Run)
            .where(Run.status == status)
            .order_by(Run.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_method(
        self,
        method_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Run]:
        """Get all runs for a specific method."""
        result = await self.session.execute(
            select(Run)
            .where(Run.method_id == method_id)
            .order_by(Run.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        run_id: UUID,
        status: RunStatus,
        message: Optional[str] = None,
    ) -> Optional[Run]:
        """Update run status."""
        update_data = {"status": status}
        if message is not None:
            update_data["message"] = message

        if status == RunStatus.RUNNING:
            update_data["started_at"] = datetime.utcnow()
        elif status in (RunStatus.DONE, RunStatus.ERROR, RunStatus.CANCELLED):
            update_data["finished_at"] = datetime.utcnow()

        return await self.update(run_id, **update_data)

    async def transition_to_running_once(
        self,
        run_id: UUID,
        message: Optional[str] = None,
    ) -> bool:
        """Atomically claim a run for execution.

        Returns True only for the first worker that moves a run from
        PENDING/QUEUED -> RUNNING. Concurrent workers for the same run_id
        will observe zero updated rows and must exit.
        """
        update_data = {
            "status": RunStatus.RUNNING,
            "started_at": datetime.utcnow(),
            "progress": case(
                (Run.progress < 5, 5),
                else_=Run.progress,
            ),
        }
        if message is not None:
            update_data["message"] = message

        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.status.in_((RunStatus.PENDING, RunStatus.QUEUED)))
            .values(**update_data)
            .returning(Run.id)
        )
        claimed = (await self.session.execute(stmt)).scalar_one_or_none()
        return claimed is not None

    async def update_progress(
        self,
        run_id: UUID,
        progress: int,
        message: Optional[str] = None,
    ) -> Optional[Run]:
        """Update run progress without allowing regressions.

        Progress updates are applied only to active runs and never decrease.
        """
        bounded_progress = max(0, min(100, progress))
        values: dict[str, object] = {
            "progress": case(
                (Run.progress < bounded_progress, bounded_progress),
                else_=Run.progress,
            ),
        }
        if message is not None:
            # Keep the previous message when progress would not advance.
            values["message"] = case(
                (Run.progress < bounded_progress, message),
                else_=Run.message,
            )

        stmt = (
            update(Run)
            .where(Run.id == run_id)
            .where(Run.status.in_(ACTIVE_RUN_STATUSES))
            .values(**values)
            .returning(Run)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_result(
        self,
        run_id: UUID,
        result: dict,
        status: RunStatus = RunStatus.DONE,
    ) -> Optional[Run]:
        """Set run result and mark as done."""
        return await self.update(
            run_id,
            result=result,
            status=status,
            progress=100,
            message="Completed",
            finished_at=datetime.utcnow(),
        )

    async def set_error(
        self,
        run_id: UUID,
        error: str,
    ) -> Optional[Run]:
        """Set run error and mark as error."""
        return await self.update(
            run_id,
            status=RunStatus.ERROR,
            error=error,
            progress=100,
            message=error,
            finished_at=datetime.utcnow(),
        )

    async def get_expired_runs(self) -> List[Run]:
        """Get all runs that have expired."""
        result = await self.session.execute(
            select(Run)
            .where(Run.expires_at.isnot(None))
            .where(Run.expires_at < datetime.utcnow())
        )
        return list(result.scalars().all())
