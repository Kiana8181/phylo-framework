"""Record when a run became ready to start

Revision ID: 012_run_dispatch_ready_at
Revises: 011_empty_password_hashes
Create Date: 2026-10-12

Adds ``runs.dispatch_ready_at``: the moment a run was promoted into the global
dispatch order (the same moment ``dispatch_seq`` is assigned). The worker uses it
to bound how long a ready run may wait for a free method slot
(RUN_QUEUE_WAIT_TIMEOUT_SECONDS).

Purely additive. Runs that are already waiting when this migration runs get the
migration time, so their waiting period starts now rather than in the past and no
run is failed because of time spent waiting before the limit existed. No other
column or row changes. Downgrade drops the column.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "012_run_dispatch_ready_at"
down_revision: Union[str, None] = "011_empty_password_hashes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS dispatch_ready_at TIMESTAMPTZ")
    op.execute(
        """
        UPDATE runs
        SET dispatch_ready_at = now()
        WHERE status = 'QUEUED' AND dispatch_seq IS NOT NULL AND dispatch_ready_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS dispatch_ready_at")
