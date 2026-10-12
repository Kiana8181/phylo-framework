"""Result retention: expiry dates for finished runs

Revision ID: 016_result_retention
Revises: 015_auth_abuse_prevention
Create Date: 2026-10-12

  * ``runs.results_expired_at``: when a run's results were removed (NULL =
    still there).
  * Runs that have already ended get an expiry date counted **from now**, not
    from when they ended: nobody was told about retention when those runs were
    made, so none of them loses its results the day this is deployed. The
    period is RESULT_RETENTION_DAYS as set when the migration runs (default 60;
    0 leaves them as they are). A date that some earlier version or an
    administrator had already put on a run is only ever moved later by this,
    never earlier.
  * An index for the worker's "which results are due" query.

Additive. No result is removed by this migration. Downgrade drops the column
and the index and leaves expires_at as it is.
"""
import os
from typing import Sequence, Union

from alembic import op

revision: str = "016_result_retention"
down_revision: Union[str, None] = "015_auth_abuse_prevention"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _retention_days() -> float:
    try:
        days = float((os.getenv("RESULT_RETENTION_DAYS") or "").strip() or 60)
    except ValueError:
        return 60.0
    return days if days >= 0 else 60.0


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS results_expired_at TIMESTAMPTZ")
    days = _retention_days()
    if days > 0:
        op.execute(
            f"""
            UPDATE runs
            SET expires_at = now() + interval '{days:.6f} days'
            WHERE status IN ('DONE', 'ERROR', 'CANCELLED')
              AND (expires_at IS NULL OR expires_at < now() + interval '{days:.6f} days')
            """
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_runs_expiry_due ON runs (expires_at) "
        "WHERE results_expired_at IS NULL AND expires_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_runs_expiry_due")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS results_expired_at")
