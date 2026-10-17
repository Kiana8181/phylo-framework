"""Index for the per-user rolling run quota

Revision ID: 013_runs_user_created_index
Revises: 012_run_dispatch_ready_at
Create Date: 2026-10-12

Every run creation and every quota request asks for "this user's runs of the
last hour". The composite index answers that from the index instead of scanning
the user's whole history. Additive; no data changes. Downgrade drops the index.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "013_runs_user_created_index"
down_revision: Union[str, None] = "012_run_dispatch_ready_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_runs_user_created_at ON runs (user_id, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_runs_user_created_at")
