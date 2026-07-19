"""Add display_newick column to run_trees

Revision ID: 010_display_newick
Revises: 009_run_dispatch_queue
Create Date: 2026-07-19

Adds ``run_trees.display_newick`` (TEXT NULL): a download-only Newick relabeled
with the user's original sequence_ids (gctree only). NULL for other methods and
all pre-existing rows. Nullable, no backfill — old runs fall back to the
canonical newick on download.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "010_display_newick"
down_revision: Union[str, None] = "009_run_dispatch_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "run_trees",
        sa.Column("display_newick", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("run_trees", "display_newick")
