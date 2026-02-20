"""Add runs.input_file_id for same-dataset comparison

Revision ID: 005_run_input_file_id
Revises: 004_run_trees_tree_id
Create Date: 2026-02-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "005_run_input_file_id"
down_revision: Union[str, None] = "004_run_trees_tree_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("input_file_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_runs_input_file_id_files",
        "runs",
        "files",
        ["input_file_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_runs_input_file_id",
        "runs",
        ["input_file_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_runs_input_file_id", table_name="runs")
    op.drop_constraint("fk_runs_input_file_id_files", "runs", type_="foreignkey")
    op.drop_column("runs", "input_file_id")
