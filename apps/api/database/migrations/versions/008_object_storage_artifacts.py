"""Object-storage file management: dataset soft-delete + checksum, run_artifacts table, drop run_trees.service_image

Revision ID: 008_object_storage_artifacts
Revises: 007_async_orchestration
Create Date: 2026-06-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "008_object_storage_artifacts"
down_revision: Union[str, None] = "007_async_orchestration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- files: object-store metadata + soft-delete / retention fields ---
    op.add_column("files", sa.Column("storage_bucket", sa.String(length=255), nullable=True))
    op.add_column("files", sa.Column("checksum_sha256", sa.String(length=64), nullable=True))
    op.add_column(
        "files",
        sa.Column("storage_state", sa.String(length=20), nullable=False, server_default="active"),
    )
    op.add_column("files", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("files", sa.Column("deleted_by", sa.UUID(), nullable=True))
    op.add_column("files", sa.Column("object_deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_files_deleted_by_users",
        "files",
        "users",
        ["deleted_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_files_storage_state", "files", ["storage_state"], unique=False)

    # --- run_artifacts: generated outputs stored as objects (metadata only) ---
    op.create_table(
        "run_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("tree_id", sa.String(length=120), nullable=True),
        sa.Column("storage_backend", sa.String(length=20), nullable=False),
        sa.Column("storage_bucket", sa.String(length=255), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("artifact_kind", sa.String(length=20), nullable=False, server_default="other"),
        sa.Column("artifact_role", sa.String(length=50), nullable=True),
        sa.Column("is_previewable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_state", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("object_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_run_artifacts_run_id", "run_artifacts", ["run_id"], unique=False)
    op.create_index("idx_run_artifacts_run_tree", "run_artifacts", ["run_id", "tree_id"], unique=False)
    op.create_index("idx_run_artifacts_run_role", "run_artifacts", ["run_id", "artifact_role"], unique=False)
    op.create_index("idx_run_artifacts_kind", "run_artifacts", ["artifact_kind"], unique=False)
    op.create_index("idx_run_artifacts_storage_state", "run_artifacts", ["storage_state"], unique=False)

    # --- run_trees: drop the base64 image column (now a RunArtifact) ---
    op.drop_column("run_trees", "service_image")


def downgrade() -> None:
    op.add_column("run_trees", sa.Column("service_image", postgresql.JSONB(), nullable=True))

    op.drop_index("idx_run_artifacts_storage_state", table_name="run_artifacts")
    op.drop_index("idx_run_artifacts_kind", table_name="run_artifacts")
    op.drop_index("idx_run_artifacts_run_role", table_name="run_artifacts")
    op.drop_index("idx_run_artifacts_run_tree", table_name="run_artifacts")
    op.drop_index("idx_run_artifacts_run_id", table_name="run_artifacts")
    op.drop_table("run_artifacts")

    op.drop_index("idx_files_storage_state", table_name="files")
    op.drop_constraint("fk_files_deleted_by_users", "files", type_="foreignkey")
    op.drop_column("files", "object_deleted_at")
    op.drop_column("files", "deleted_by")
    op.drop_column("files", "deleted_at")
    op.drop_column("files", "storage_state")
    op.drop_column("files", "checksum_sha256")
    op.drop_column("files", "storage_bucket")
