"""Notification outbox for run emails

Revision ID: 014_notification_outbox
Revises: 013_runs_user_created_index
Create Date: 2026-10-12

Creates ``notification_outbox``: one row per email owed to a user about a run.
Rows are written together with a run's final status and delivered later by the
worker, with bounded retries. ``UNIQUE (run_id, kind)`` prevents a second
notification for the same run.

Purely additive: a new table and its indexes. Runs that finished before this
migration get no row and therefore no email. Downgrade drops the table.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "014_notification_outbox"
down_revision: Union[str, None] = "013_runs_user_created_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_outbox (
            id UUID PRIMARY KEY,
            run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind VARCHAR(40) NOT NULL,
            outcome VARCHAR(20) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            locked_until TIMESTAMPTZ,
            last_error TEXT,
            recipient VARCHAR(320),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            sent_at TIMESTAMPTZ,
            CONSTRAINT uq_notification_outbox_run_kind UNIQUE (run_id, kind)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_outbox_due "
        "ON notification_outbox (status, next_attempt_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notification_outbox")
