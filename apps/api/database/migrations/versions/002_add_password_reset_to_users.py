"""Add password reset token to users

Revision ID: 002_password_reset
Revises: 001_initial_schema
Create Date: 2025-02-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002_password_reset"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_reset_token", sa.String(255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_expires", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "password_reset_expires")
    op.drop_column("users", "password_reset_token")
