"""Per-user run queue: dispatch_seq column + sequence + dispatch/partial-unique indexes

Revision ID: 009_run_dispatch_queue
Revises: 008_object_storage_artifacts
Create Date: 2026-07-19

Adds the machinery for FCFS-over-per-user-sub-queues dispatch:

  * ``runs.dispatch_seq`` (BIGINT NULL) - assigned from the ``runs_dispatch_seq``
    sequence when a run is promoted to its owner's head-of-line. NULL = still in
    the personal queue; NOT NULL = promoted into the global dispatch order.
  * ``runs_dispatch_seq`` SEQUENCE - a strict monotonic total order independent of
    the clock (gaps on rollback are fine; only order matters).
  * ``idx_runs_status_dispatch_seq`` - composite index for the claim query.
  * ``uq_runs_user_active_turn`` - partial unique index backstop enforcing at most
    one active-turn run (RUNNING, or promoted QUEUED) per user.

Backfill: every currently RUNNING or QUEUED run gets a dispatch_seq ordered by
created_at so existing in-flight work stays dispatchable under the new claim query.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "009_run_dispatch_queue"
down_revision: Union[str, None] = "008_object_storage_artifacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Monotonic dispatch ticket source. Created before the column backfill uses it.
    op.execute("CREATE SEQUENCE IF NOT EXISTS runs_dispatch_seq")

    op.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS dispatch_seq BIGINT")

    op.create_index(
        "idx_runs_status_dispatch_seq", "runs", ["status", "dispatch_seq"], unique=False
    )

    # Backfill: keep existing in-flight work dispatchable, promoting exactly one
    # active turn per user so the partial-unique index below can be created even if
    # legacy data ever held more than one non-terminal run per user (the old model
    # only enforced that at the app level, never in the DB).
    #
    # 1) Every RUNNING run is its owner's active turn — give it a dispatch ticket.
    op.execute(
        """
        UPDATE runs
        SET dispatch_seq = nextval('runs_dispatch_seq')
        FROM (SELECT id FROM runs WHERE status = 'RUNNING' ORDER BY created_at ASC) AS s
        WHERE runs.id = s.id
        """
    )
    # 2) For users with NO running run, promote their oldest QUEUED run (one each).
    op.execute(
        """
        UPDATE runs
        SET dispatch_seq = nextval('runs_dispatch_seq')
        FROM (
            SELECT DISTINCT ON (user_id) id
            FROM runs
            WHERE status = 'QUEUED'
              AND user_id IS NOT NULL
              AND user_id NOT IN (
                  SELECT user_id FROM runs WHERE status = 'RUNNING' AND user_id IS NOT NULL
              )
            ORDER BY user_id, created_at ASC
        ) AS s
        WHERE runs.id = s.id
        """
    )
    # 3) Anonymous QUEUED runs (user_id NULL) have no per-user serial constraint —
    #    the partial-unique index excludes them, so promote all of them.
    op.execute(
        """
        UPDATE runs
        SET dispatch_seq = nextval('runs_dispatch_seq')
        FROM (
            SELECT id FROM runs
            WHERE status = 'QUEUED' AND user_id IS NULL
            ORDER BY created_at ASC
        ) AS s
        WHERE runs.id = s.id
        """
    )

    # Backstop for invariant #1: at most one active turn per user. A second
    # promotion for the same user violates this and is treated as a no-op by the
    # repository. Guard user_id IS NOT NULL so anonymous runs never collide.
    # status is stored as a string (Enum native_enum=False), so compare literally.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_runs_user_active_turn ON runs (user_id)
        WHERE user_id IS NOT NULL AND (
            status = 'RUNNING'
            OR (status = 'QUEUED' AND dispatch_seq IS NOT NULL)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_runs_user_active_turn")
    op.drop_index("idx_runs_status_dispatch_seq", table_name="runs")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS dispatch_seq")
    op.execute("DROP SEQUENCE IF EXISTS runs_dispatch_seq")
