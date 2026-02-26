"""Add runs.dataset_name for durable dataset labeling

Revision ID: 006_run_dataset_name
Revises: 005_run_input_file_id
Create Date: 2026-02-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "006_run_dataset_name"
down_revision: Union[str, None] = "005_run_input_file_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("dataset_name", sa.String(length=255), nullable=True))

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE runs AS r
            SET dataset_name = f.original_filename
            FROM files AS f
            WHERE r.dataset_name IS NULL
              AND r.input_file_id = f.id
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE runs AS r
            SET dataset_name = latest.original_filename
            FROM (
                SELECT DISTINCT ON (run_id) run_id, original_filename
                FROM files
                WHERE run_id IS NOT NULL
                ORDER BY run_id, uploaded_at ASC
            ) AS latest
            WHERE r.dataset_name IS NULL
              AND r.id = latest.run_id
            """
        )
    )


def downgrade() -> None:
    op.drop_column("runs", "dataset_name")
