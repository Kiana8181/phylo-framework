"""Add run_trees (run_id, tree_id) uniqueness for lazy tree lookups

Revision ID: 004_run_trees_tree_id
Revises: 003_run_trees
Create Date: 2026-02-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "004_run_trees_tree_id"
down_revision: Union[str, None] = "003_run_trees"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicate = bind.execute(
        sa.text(
            """
            SELECT
              run_id::text AS run_id,
              tree_id,
              COUNT(*) AS duplicate_count
            FROM run_trees
            GROUP BY run_id, tree_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).mappings().first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot apply uq_run_trees_run_tree_id: duplicate rows exist for "
            f"(run_id={duplicate['run_id']}, tree_id={duplicate['tree_id']}, "
            f"count={duplicate['duplicate_count']})."
        )

    op.create_unique_constraint(
        "uq_run_trees_run_tree_id",
        "run_trees",
        ["run_id", "tree_id"],
    )
    op.create_index(
        "idx_run_trees_run_tree_index",
        "run_trees",
        ["run_id", "tree_index"],
        unique=False,
    )
    op.create_index(
        "idx_run_trees_run_tree_id",
        "run_trees",
        ["run_id", "tree_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_run_trees_run_tree_id", table_name="run_trees")
    op.drop_index("idx_run_trees_run_tree_index", table_name="run_trees")
    op.drop_constraint("uq_run_trees_run_tree_id", "run_trees", type_="unique")
