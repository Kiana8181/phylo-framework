"""Add run_trees table for per-tree rendering payloads

Revision ID: 003_run_trees
Revises: 002_password_reset
Create Date: 2026-02-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003_run_trees"
down_revision: Union[str, None] = "002_password_reset"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "run_trees",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tree_index", sa.Integer(), nullable=False),
        sa.Column("tree_id", sa.String(length=120), nullable=False),
        sa.Column("newick", sa.Text(), nullable=False),
        sa.Column("original_newick", sa.Text(), nullable=True),
        sa.Column("service_image", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("node_attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("lineage_plot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("label_to_sequence_id", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "tree_index", name="uq_run_trees_run_tree_index"),
    )
    op.create_index("idx_run_trees_run_id", "run_trees", ["run_id"], unique=False)
    op.create_index("ix_run_trees_run_id", "run_trees", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_run_trees_run_id", table_name="run_trees")
    op.drop_index("idx_run_trees_run_id", table_name="run_trees")
    op.drop_table("run_trees")
