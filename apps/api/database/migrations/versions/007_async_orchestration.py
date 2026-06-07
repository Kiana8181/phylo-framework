"""Async run orchestration: run stage/lease/cancel fields + upload_sessions

Revision ID: 007_async_orchestration
Revises: 006_run_dataset_name
Create Date: 2026-05-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "007_async_orchestration"
down_revision: Union[str, None] = "006_run_dataset_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- runs: stage-based status + DB-backed worker locking + cancellation ---
    op.add_column("runs", sa.Column("stage", sa.String(length=50), nullable=True))
    op.add_column("runs", sa.Column("stage_message", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("method_job_id", sa.String(length=255), nullable=True))
    op.add_column("runs", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("worker_lease_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("worker_id", sa.String(length=255), nullable=True))
    op.create_index("idx_runs_worker_lease_until", "runs", ["worker_lease_until"], unique=False)

    # --- upload_sessions ---
    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="INITIATED"),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("expected_size", sa.BigInteger(), nullable=True),
        sa.Column("bytes_received", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("temp_storage_path", sa.Text(), nullable=True),
        sa.Column("final_file_id", sa.UUID(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["final_file_id"], ["files.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_upload_sessions_user_id", "upload_sessions", ["user_id"], unique=False)
    op.create_index("idx_upload_sessions_status", "upload_sessions", ["status"], unique=False)
    op.create_index("idx_upload_sessions_created_at", "upload_sessions", ["created_at"], unique=False)
    op.create_index(
        "idx_upload_sessions_user_status", "upload_sessions", ["user_id", "status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_upload_sessions_user_status", table_name="upload_sessions")
    op.drop_index("idx_upload_sessions_created_at", table_name="upload_sessions")
    op.drop_index("idx_upload_sessions_status", table_name="upload_sessions")
    op.drop_index("idx_upload_sessions_user_id", table_name="upload_sessions")
    op.drop_table("upload_sessions")

    op.drop_index("idx_runs_worker_lease_until", table_name="runs")
    op.drop_column("runs", "worker_id")
    op.drop_column("runs", "worker_lease_until")
    op.drop_column("runs", "cancel_requested_at")
    op.drop_column("runs", "method_job_id")
    op.drop_column("runs", "stage_message")
    op.drop_column("runs", "stage")
