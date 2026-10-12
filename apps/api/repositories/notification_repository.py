"""Persistence of the notification outbox (see NotificationOutbox).

Writing rows belongs to RunRepository, because a row must be written in the
transaction that ends the run. This repository is the delivery side: taking due
rows without two senders taking the same one, and recording what happened.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.models import NotificationOutbox, NotificationStatus
from apps.api.utils.datetime_util import utc_now

MAX_ERROR_CHARS = 500


class NotificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def claim_due(self, *, limit: int, lease_seconds: float, now: Optional[datetime] = None) -> list[NotificationOutbox]:
        """Take up to ``limit`` notifications that are due and not in another
        sender's hands, and hold them for ``lease_seconds``.

        ``FOR UPDATE SKIP LOCKED`` keeps two senders from selecting the same row;
        the lease keeps a row from being taken again while its email is being
        sent, and lets another sender take over if this one dies meanwhile.
        """
        now = now or utc_now()
        due = (
            select(NotificationOutbox.id)
            .where(
                NotificationOutbox.status == NotificationStatus.PENDING.value,
                NotificationOutbox.next_attempt_at <= now,
                or_(NotificationOutbox.locked_until.is_(None), NotificationOutbox.locked_until < now),
            )
            .order_by(NotificationOutbox.next_attempt_at.asc(), NotificationOutbox.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        ids = [row[0] for row in (await self.session.execute(due)).all()]
        if not ids:
            await self.session.commit()
            return []
        claimed = (
            await self.session.execute(
                update(NotificationOutbox)
                .where(NotificationOutbox.id.in_(ids))
                .values(locked_until=now + timedelta(seconds=lease_seconds))
                .returning(NotificationOutbox)
            )
        ).scalars().all()
        await self.session.commit()
        return list(claimed)

    async def _finish(self, notification_id: UUID, **values) -> None:
        # Only a row still PENDING is changed: an answer that arrives after
        # another sender has settled the row is ignored.
        await self.session.execute(
            update(NotificationOutbox)
            .where(
                NotificationOutbox.id == notification_id,
                NotificationOutbox.status == NotificationStatus.PENDING.value,
            )
            .values(locked_until=None, **values)
        )
        await self.session.commit()

    async def mark_sent(self, notification_id: UUID, *, recipient: str, attempts: int) -> None:
        await self._finish(
            notification_id,
            status=NotificationStatus.SENT.value,
            attempts=attempts,
            recipient=recipient[:320],
            sent_at=utc_now(),
            last_error=None,
        )

    async def mark_retry(self, notification_id: UUID, *, attempts: int, next_attempt_at: datetime, error: str) -> None:
        await self._finish(
            notification_id,
            attempts=attempts,
            next_attempt_at=next_attempt_at,
            last_error=error[:MAX_ERROR_CHARS],
        )

    async def mark_failed(self, notification_id: UUID, *, attempts: int, error: str) -> None:
        await self._finish(
            notification_id,
            status=NotificationStatus.FAILED.value,
            attempts=attempts,
            last_error=error[:MAX_ERROR_CHARS],
        )

    async def mark_skipped(self, notification_id: UUID, *, reason: str) -> None:
        await self._finish(
            notification_id,
            status=NotificationStatus.SKIPPED.value,
            last_error=reason[:MAX_ERROR_CHARS],
        )

    async def get_for_run(self, run_id: UUID) -> list[NotificationOutbox]:
        result = await self.session.execute(
            select(NotificationOutbox)
            .where(NotificationOutbox.run_id == run_id)
            .order_by(NotificationOutbox.created_at.asc())
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())
