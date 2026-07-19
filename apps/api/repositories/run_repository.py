from __future__ import annotations

from typing import Optional, List
from uuid import UUID
from datetime import date, datetime, timezone, timedelta

from sqlalchemy import String, and_, case, cast, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.models import Run, RunStatus, ACTIVE_RUN_STATUSES
from apps.api.repositories.base_repository import BaseRepository
from apps.api.utils.datetime_util import utc_now

TERMINAL_RUN_STATUSES = (RunStatus.DONE, RunStatus.ERROR, RunStatus.CANCELLED)

# Postgres sequence backing the global dispatch order (see migration 009).
DISPATCH_SEQ = "runs_dispatch_seq"


class RunRepository(BaseRepository[Run]):
    """Repository for Run model with specific methods."""

    def __init__(self, session: AsyncSession):
        super().__init__(Run, session)

    async def create_run(
        self,
        method_id: str,
        params: dict,
        user_id: Optional[UUID] = None,
        input_file_id: Optional[UUID] = None,
        dataset_name: Optional[str] = None,
    ) -> Run:
        """Create a new run."""
        return await self.create(
            method_id=method_id,
            params=params,
            user_id=user_id,
            input_file_id=input_file_id,
            dataset_name=dataset_name,
            status=RunStatus.QUEUED,
            stage="QUEUED",
            stage_message="Queued",
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

    # --------------------------------------------------------------------- #
    # Per-user run queue (FCFS over per-user sub-queues)
    # --------------------------------------------------------------------- #
    @staticmethod
    def _active_turn_predicate():
        """A run is the user's active turn when it is RUNNING or a promoted QUEUED."""
        return or_(
            Run.status == RunStatus.RUNNING,
            and_(Run.status == RunStatus.QUEUED, Run.dispatch_seq.isnot(None)),
        )

    async def count_nonterminal_for_user(self, user_id: UUID) -> int:
        """Count a user's non-terminal runs (PENDING/QUEUED/RUNNING). Drives the quota."""
        result = await self.session.execute(
            select(func.count())
            .select_from(Run)
            .where(Run.user_id == user_id)
            .where(Run.status.in_(ACTIVE_RUN_STATUSES))
        )
        return int(result.scalar() or 0)

    async def get_active_turn_run_for_user(self, user_id: UUID) -> Optional[Run]:
        """The user's active-turn run: RUNNING, or QUEUED with dispatch_seq assigned."""
        result = await self.session.execute(
            select(Run)
            .where(Run.user_id == user_id)
            .where(self._active_turn_predicate())
            .order_by(Run.dispatch_seq.asc().nulls_last(), Run.created_at.asc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_personal_queue_for_user(self, user_id: UUID) -> List[Run]:
        """The user's waiting-behind list: QUEUED with no dispatch_seq, FIFO by creation."""
        result = await self.session.execute(
            select(Run)
            .where(Run.user_id == user_id)
            .where(Run.status == RunStatus.QUEUED)
            .where(Run.dispatch_seq.is_(None))
            .order_by(Run.created_at.asc())
        )
        return list(result.scalars().all())

    async def _promote_next_locked(self, user_id: Optional[UUID]) -> Optional[Run]:
        """Promote the user's head-of-line into the global dispatch order.

        Does NOT commit — the caller owns the transaction. No-op (returns None) if
        the user already holds an active turn or has an empty personal queue. Selects
        the oldest personal-queue run FOR UPDATE SKIP LOCKED so concurrent promoters
        never grab the same candidate.
        """
        if user_id is None:
            return None

        already = await self.session.execute(
            select(Run.id)
            .where(Run.user_id == user_id)
            .where(self._active_turn_predicate())
            .limit(1)
        )
        if already.scalar_one_or_none() is not None:
            return None

        candidate = await self.session.execute(
            select(Run.id)
            .where(Run.user_id == user_id)
            .where(Run.status == RunStatus.QUEUED)
            .where(Run.dispatch_seq.is_(None))
            .order_by(Run.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        candidate_id = candidate.scalar_one_or_none()
        if candidate_id is None:
            return None

        stmt = (
            update(Run)
            .where(Run.id == candidate_id)
            .values(dispatch_seq=func.nextval(DISPATCH_SEQ))
            .returning(Run)
        )
        run = (await self.session.execute(stmt)).scalar_one_or_none()
        return run

    async def promote_next_for_user(self, user_id: Optional[UUID]) -> Optional[Run]:
        """Promote a user's head-of-line, committing the result.

        Catches the partial-unique-index violation (a racing second promotion) and
        treats it as a no-op. Safe to call opportunistically.
        """
        if user_id is None:
            return None
        try:
            run = await self._promote_next_locked(user_id)
            await self.session.commit()
            return run
        except IntegrityError:
            await self.session.rollback()
            return None

    async def promote_run(self, run_id: UUID) -> Optional[Run]:
        """Unconditionally promote a specific QUEUED, unpromoted run into the dispatch
        order. Used for anonymous runs (user_id NULL), which have no per-user serial
        constraint — each is independently dispatch-ready. Commits.
        """
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status == RunStatus.QUEUED,
                Run.dispatch_seq.is_(None),
            )
            .values(dispatch_seq=func.nextval(DISPATCH_SEQ))
            .returning(Run)
        )
        run = (await self.session.execute(stmt)).scalar_one_or_none()
        await self.session.commit()
        return run

    async def promote_all_eligible(self) -> int:
        """Promote the head-of-line for every user who has no active turn but a
        non-empty personal queue. Idempotent; used by the worker sweep and as a
        self-healing backstop. Returns the number of runs promoted.
        """
        # Users with at least one waiting (unpromoted) QUEUED run.
        waiting = await self.session.execute(
            select(Run.user_id)
            .where(Run.user_id.isnot(None))
            .where(Run.status == RunStatus.QUEUED)
            .where(Run.dispatch_seq.is_(None))
            .group_by(Run.user_id)
        )
        user_ids = [row[0] for row in waiting.all()]

        promoted = 0
        for uid in user_ids:
            run = await self.promote_next_for_user(uid)
            if run is not None:
                promoted += 1

        # Anonymous runs (user_id NULL) have no serial constraint — promote each
        # independently, oldest first, as a backstop for any missed at creation.
        anon = await self.session.execute(
            select(Run.id)
            .where(Run.user_id.is_(None))
            .where(Run.status == RunStatus.QUEUED)
            .where(Run.dispatch_seq.is_(None))
            .order_by(Run.created_at.asc())
        )
        for (run_id,) in anon.all():
            run = await self.promote_run(run_id)
            if run is not None:
                promoted += 1
        return promoted

    async def _terminal_update_and_promote(
        self, run_id: UUID, **values
    ) -> Optional[Run]:
        """Apply a terminal status update to a run and, atomically, promote the
        owner's next queued run. The promotion runs in a SAVEPOINT so a racing
        partial-unique violation rolls back only the promotion, never the terminal
        flip (durability of the terminal state is the priority).
        """
        owner_id = await self.session.scalar(
            select(Run.user_id).where(Run.id == run_id)
        )
        stmt = update(Run).where(Run.id == run_id).values(**values).returning(Run)
        result = (await self.session.execute(stmt)).scalar_one_or_none()

        if owner_id is not None:
            try:
                async with self.session.begin_nested():
                    await self._promote_next_locked(owner_id)
            except IntegrityError:
                pass  # already promoted / raced; worker sweep is the backstop

        await self.session.commit()
        return result

    async def get_by_user(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 100,
        *,
        run_id: Optional[str] = None,
        dataset: Optional[str] = None,
        status: Optional[RunStatus] = None,
        method_id: Optional[str] = None,
        created_on: Optional[date] = None,
    ) -> List[Run]:
        """Get a user's runs, optionally filtered (all filters ANDed with the
        per-user scope). `run_id`/`dataset` are case-insensitive substring
        matches; `created_on` matches runs created on that calendar day."""
        stmt = select(Run).where(Run.user_id == user_id)

        if run_id:
            stmt = stmt.where(cast(Run.id, String).ilike(f"%{run_id.strip()}%"))
        if dataset:
            stmt = stmt.where(Run.dataset_name.ilike(f"%{dataset.strip()}%"))
        if status is not None:
            stmt = stmt.where(Run.status == status)
        if method_id:
            stmt = stmt.where(Run.method_id == method_id)
        if created_on is not None:
            stmt = stmt.where(func.date(Run.created_at) == created_on)

        result = await self.session.execute(
            stmt.order_by(Run.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def get_stale_pending_runs(
        self,
        age_seconds: int = 20,
        limit: int = 5,
    ) -> List[Run]:
        """Return PENDING runs older than age_seconds (e.g. missed by background task after reload)."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        result = await self.session.execute(
            select(Run)
            .where(Run.status == RunStatus.PENDING)
            .where(Run.created_at < cutoff)
            .order_by(Run.created_at.asc())
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
        """Update run status. Terminal transitions also promote the owner's next run."""
        update_data = {"status": status}
        if message is not None:
            update_data["message"] = message

        if status == RunStatus.RUNNING:
            update_data["started_at"] = utc_now()
            return await self.update(run_id, **update_data)

        if status in TERMINAL_RUN_STATUSES:
            update_data["finished_at"] = func.now()
            return await self._terminal_update_and_promote(run_id, **update_data)

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
            "started_at": utc_now(),
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

    async def claim_next_run(
        self,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> Optional[Run]:
        """Atomically claim the next runnable run for this worker.

        Picks either a promoted QUEUED run (dispatch_seq assigned = dispatch-ready),
        or a RUNNING run whose lease has expired (worker crashed/restarted). Ordered
        by ``dispatch_seq`` — the global readiness (promotion) order, NOT creation
        order — so the FCFS-over-per-user-sub-queues discipline holds. Uses
        SELECT ... FOR UPDATE SKIP LOCKED so two workers never claim the same run.

        Commits the claim and returns the leased Run, or None when idle.
        """
        now = utc_now()
        lease_until = now + timedelta(seconds=lease_seconds)

        candidate_stmt = (
            select(Run.id)
            .where(
                or_(
                    and_(
                        Run.status == RunStatus.QUEUED,
                        Run.dispatch_seq.isnot(None),
                    ),
                    and_(
                        Run.status == RunStatus.RUNNING,
                        Run.worker_lease_until.isnot(None),
                        Run.worker_lease_until < now,
                    ),
                )
            )
            .order_by(Run.dispatch_seq.asc(), Run.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        candidate_id = (await self.session.execute(candidate_stmt)).scalar_one_or_none()
        if candidate_id is None:
            await self.session.commit()
            return None

        stmt = (
            update(Run)
            .where(Run.id == candidate_id)
            .values(
                status=RunStatus.RUNNING,
                worker_id=worker_id,
                worker_lease_until=lease_until,
                started_at=case((Run.started_at.is_(None), func.now()), else_=Run.started_at),
            )
            .returning(Run)
        )
        run = (await self.session.execute(stmt)).scalar_one_or_none()
        await self.session.commit()
        return run

    async def renew_lease(
        self,
        run_id: UUID,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> bool:
        """Extend the worker lease for a run still owned by this worker."""
        lease_until = utc_now() + timedelta(seconds=lease_seconds)
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.worker_id == worker_id, Run.status == RunStatus.RUNNING)
            .values(worker_lease_until=lease_until)
            .returning(Run.id)
        )
        renewed = (await self.session.execute(stmt)).scalar_one_or_none()
        await self.session.commit()
        return renewed is not None

    async def set_method_job_id(self, run_id: UUID, method_job_id: str) -> Optional[Run]:
        """Persist the method service job id for a run (for resume/cancel)."""
        return await self.update(run_id, method_job_id=method_job_id)

    async def update_stage(
        self,
        run_id: UUID,
        stage: Optional[str] = None,
        *,
        message: Optional[str] = None,
        progress: Optional[int] = None,
    ) -> Optional[Run]:
        """Update the high-level stage (and optional progress/message).

        Progress is only set on stage transitions and never decreases.
        """
        values: dict[str, object] = {}
        if stage is not None:
            values["stage"] = stage
        if message is not None:
            values["stage_message"] = message
            values["message"] = message
        if progress is not None:
            bounded = max(0, min(100, progress))
            values["progress"] = case(
                (Run.progress < bounded, bounded),
                else_=Run.progress,
            )
        if not values:
            return await self.get_by_id(run_id)

        stmt = (
            update(Run)
            .where(Run.id == run_id)
            .where(Run.status.in_(ACTIVE_RUN_STATUSES))
            .values(**values)
            .returning(Run)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    async def cancel_if_queued(self, run_id: UUID, message: Optional[str] = None) -> bool:
        """Immediately cancel a run that is still QUEUED and unclaimed.

        Used when a user cancels before the worker picks up the run. If the cancelled
        run was the owner's active turn, promotes their next queued run; the
        active-turn guard makes the promotion a safe no-op when a plain
        personal-queue item is cancelled instead.
        """
        now = utc_now()
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status == RunStatus.QUEUED,
                Run.worker_lease_until.is_(None),
            )
            .values(
                status=RunStatus.CANCELLED,
                stage="CANCELLED",
                stage_message=message or "Cancelled before execution",
                message=message or "Cancelled before execution",
                cancel_requested_at=now,
                finished_at=func.now(),
                worker_lease_until=None,
            )
            .returning(Run.id, Run.user_id)
        )
        row = (await self.session.execute(stmt)).first()
        if row is None:
            await self.session.commit()
            return False

        owner_id = row[1]
        if owner_id is not None:
            try:
                async with self.session.begin_nested():
                    await self._promote_next_locked(owner_id)
            except IntegrityError:
                pass
        await self.session.commit()
        return True

    async def cancel_queued_run(
        self, run_id: UUID, user_id: UUID, message: Optional[str] = None
    ) -> Optional[Run]:
        """Cancel a QUEUED run owned by ``user_id`` — whether it is the promoted turn
        or a plain personal-queue item.

        If the cancelled run was the owner's active turn, promotes their next queued
        run. If it was a personal-queue item, the active-turn guard makes the
        promotion a no-op, so no other user's dispatch ordering is disturbed. Returns
        the cancelled run, or None if nothing matched (wrong owner / not QUEUED).
        """
        now = utc_now()
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.user_id == user_id,
                Run.status == RunStatus.QUEUED,
            )
            .values(
                status=RunStatus.CANCELLED,
                stage="CANCELLED",
                stage_message=message or "Cancelled by user",
                message=message or "Cancelled by user",
                cancel_requested_at=now,
                finished_at=func.now(),
                worker_lease_until=None,
            )
            .returning(Run)
        )
        cancelled = (await self.session.execute(stmt)).scalar_one_or_none()
        if cancelled is None:
            await self.session.commit()
            return None

        try:
            async with self.session.begin_nested():
                await self._promote_next_locked(user_id)
        except IntegrityError:
            pass
        await self.session.commit()
        return cancelled

    async def request_cancel(self, run_id: UUID, message: Optional[str] = None) -> Optional[Run]:
        """Mark a RUNNING run as cancel-requested so the worker terminates it."""
        now = utc_now()
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.status.in_(ACTIVE_RUN_STATUSES))
            .values(
                cancel_requested_at=case(
                    (Run.cancel_requested_at.is_(None), now),
                    else_=Run.cancel_requested_at,
                ),
                stage="CANCELLING",
                stage_message=message or "Cancelling...",
                message=message or "Cancelling...",
            )
            .returning(Run)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    async def mark_cancelled(self, run_id: UUID, message: Optional[str] = None) -> Optional[Run]:
        """Finalize a run as CANCELLED, release the lease, and promote the owner's next run."""
        return await self._terminal_update_and_promote(
            run_id,
            status=RunStatus.CANCELLED,
            stage="CANCELLED",
            stage_message=message or "Run cancelled",
            message=message or "Run cancelled",
            finished_at=func.now(),
            worker_lease_until=None,
        )

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
        """Set run result, mark as done, and promote the owner's next queued run."""
        return await self._terminal_update_and_promote(
            run_id,
            result=result,
            status=status,
            stage="COMPLETED" if status == RunStatus.DONE else None,
            stage_message="Completed" if status == RunStatus.DONE else None,
            progress=100,
            message="Completed",
            finished_at=func.now(),
            worker_lease_until=None,
        )

    async def set_error(
        self,
        run_id: UUID,
        error: str,
    ) -> Optional[Run]:
        """Set run error, mark as error, and promote the owner's next queued run."""
        return await self._terminal_update_and_promote(
            run_id,
            status=RunStatus.ERROR,
            stage="ERROR",
            error=error,
            progress=100,
            message=error,
            finished_at=func.now(),
            worker_lease_until=None,
        )

    async def get_expired_runs(self) -> List[Run]:
        """Get all runs that have expired."""
        result = await self.session.execute(
            select(Run)
            .where(Run.expires_at.isnot(None))
            .where(Run.expires_at < utc_now())
        )
        return list(result.scalars().all())

    async def get_by_same_input_file(
        self,
        input_file_id: UUID,
        exclude_run_id: UUID,
        current_user_id: Optional[UUID],
        is_admin: bool = False,
        limit: int = 100,
    ) -> List[Run]:
        """Get DONE runs that used the same input file, excluding one run, visible to user."""
        return await self.get_by_input_file_ids(
            [input_file_id],
            exclude_run_id=exclude_run_id,
            current_user_id=current_user_id,
            is_admin=is_admin,
            limit=limit,
        )

    async def get_by_input_file_ids(
        self,
        input_file_ids: List[UUID],
        exclude_run_id: UUID,
        current_user_id: Optional[UUID],
        is_admin: bool = False,
        limit: int = 100,
    ) -> List[Run]:
        """Get DONE runs that used any of the given input files, excluding one run, visible to user."""
        if not input_file_ids:
            return []
        stmt = (
            select(Run)
            .where(Run.input_file_id.in_(input_file_ids))
            .where(Run.id != exclude_run_id)
            .where(Run.status == RunStatus.DONE)
            .order_by(Run.created_at.desc())
            .limit(limit)
        )
        if not is_admin and current_user_id is not None:
            stmt = stmt.where(or_(Run.user_id.is_(None), Run.user_id == current_user_id))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_same_dataset_file_ids(
        self,
        file_ids: List[UUID],
        exclude_run_id: UUID,
        current_user_id: Optional[UUID],
        is_admin: bool = False,
        limit: int = 100,
    ) -> List[Run]:
        """Get DONE runs that share the same dataset: either input_file_id in file_ids, or a file (run_id) in file_ids.
        Two-way: run A (file by run_id) and run B (input_file_id) both see each other."""
        if not file_ids:
            return []
        from apps.api.database.models import File

        # Runs that have input_file_id in file_ids OR have a file (File.run_id = Run.id) whose id is in file_ids
        has_input = Run.input_file_id.in_(file_ids)
        has_file_for_run = exists(
            select(1).where(File.run_id == Run.id, File.id.in_(file_ids))
        )
        stmt = (
            select(Run)
            .where(or_(has_input, has_file_for_run))
            .where(Run.id != exclude_run_id)
            .where(Run.status == RunStatus.DONE)
            .order_by(Run.created_at.desc())
            .limit(limit)
        )
        if not is_admin and current_user_id is not None:
            stmt = stmt.where(or_(Run.user_id.is_(None), Run.user_id == current_user_id))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
