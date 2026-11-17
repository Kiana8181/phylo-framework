"""Dataset retention: expiry dates for uploaded datasets that have none

Revision ID: 018_dataset_retention
Revises: 017_runs_write_cost
Create Date: 2026-11-16

``files.expires_at`` already exists and was unused. Datasets that are still
stored and have no expiry date get one counted **from now**, not from
``uploaded_at``: nobody was told about dataset retention when those files were
uploaded, so none of them is removed the day this is deployed. The period is
DATASET_RETENTION_DAYS as set when the migration runs (default 60; 0 leaves
every date as it is). A date already stored on a row is never moved.

An index for the worker's "which datasets are due" query. Both the name and
the value of ``storage_state`` are matched: the column default written by an
earlier migration is ``active``, and the application enum persists ``ACTIVE``.

Additive. No dataset is removed by this migration. Downgrade drops the index
and leaves ``expires_at`` as it is.
"""
import os
from typing import Sequence, Union

from alembic import op

revision: str = "018_dataset_retention"
down_revision: Union[str, None] = "017_runs_write_cost"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Rows the application still serves. See the module docstring for both spellings.
_ACTIVE = "storage_state IN ('ACTIVE', 'active')"

INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_files_expiry_due ON files (expires_at) "
    f"WHERE {_ACTIVE} AND expires_at IS NOT NULL"
)


def retention_days() -> float:
    try:
        days = float((os.getenv("DATASET_RETENTION_DAYS") or "").strip() or 60)
    except ValueError:
        return 60.0
    return days if days >= 0 else 60.0


def backfill_sql(days: float) -> str:
    """Set a date only where there is none. Existing dates stay put."""
    return (
        "UPDATE files "
        f"SET expires_at = now() + interval '{days:.6f} days' "
        f"WHERE {_ACTIVE} AND expires_at IS NULL"
    )


def upgrade() -> None:
    days = retention_days()
    if days > 0:
        op.execute(backfill_sql(days))
    op.execute(INDEX_SQL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_files_expiry_due")
