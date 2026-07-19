from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from apps.api.database.base import Base

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class RunStatus(str, enum.Enum):
    """Run status enumeration."""
    PENDING = "PENDING"   # Created, not yet picked by worker
    QUEUED = "QUEUED"    # In queue, waiting to run
    RUNNING = "RUNNING"  # Currently executing
    DONE = "DONE"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


# Statuses that count as "active" (user cannot start another run)
ACTIVE_RUN_STATUSES = (RunStatus.PENDING, RunStatus.QUEUED, RunStatus.RUNNING)


class JobStatus(str, enum.Enum):
    """Job queue status enumeration."""
    QUEUED = "QUEUED"
    STARTED = "STARTED"
    FINISHED = "FINISHED"
    FAILED = "FAILED"


class StorageType(str, enum.Enum):
    """File storage type enumeration."""
    LOCAL = "local"
    S3 = "s3"
    MINIO = "minio"


class UploadSessionStatus(str, enum.Enum):
    """Upload session lifecycle status."""
    INITIATED = "INITIATED"
    UPLOADING = "UPLOADING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class StorageState(str, enum.Enum):
    """Lifecycle of a stored object referenced by a metadata row.

    ``active``  - object exists in storage and is downloadable.
    ``deleted`` - object has been hard-deleted from storage; the metadata row
                  is retained for history/reproducibility only.
    """
    ACTIVE = "active"
    DELETED = "deleted"


class ArtifactKind(str, enum.Enum):
    """Category of a generated run artifact (drives preview/handling)."""
    IMAGE = "image"
    NEWICK = "newick"
    TABLE = "table"
    FASTA = "fasta"
    JSON = "json"
    LOG = "log"
    ZIP = "zip"
    OTHER = "other"


class User(Base):
    """User model."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    password_reset_token = Column(String(255), nullable=True)
    password_reset_expires = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    runs = relationship("Run", back_populates="user", cascade="all, delete-orphan")
    files = relationship(
        "File",
        back_populates="user",
        foreign_keys="File.user_id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("username", name="uq_users_username"),
    )


class Run(Base):
    """Run model - represents a single method execution."""
    __tablename__ = "runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,  # Nullable for backward compatibility
        index=True
    )
    input_file_id = Column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    method_id = Column(String(50), nullable=False, index=True)
    status = Column(
        Enum(RunStatus, native_enum=False),
        default=RunStatus.PENDING,
        nullable=False,
        index=True
    )
    progress = Column(
        Integer,
        default=0,
        nullable=False,
    )
    message = Column(Text, nullable=True)
    # High-level stage identifier (e.g. QUEUED, STAGING_INPUT, BUILDING_TREES).
    stage = Column(String(50), nullable=True)
    # User-facing message tied to the current stage.
    stage_message = Column(Text, nullable=True)
    # ID returned by the method service async job endpoint.
    method_job_id = Column(String(255), nullable=True)
    params = Column(JSONB, nullable=False, default={})
    dataset_name = Column(String(255), nullable=True)
    result = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    # Set by the cancel endpoint; observed by the worker to terminate the job.
    cancel_requested_at = Column(DateTime(timezone=True), nullable=True)
    # DB-backed worker locking: a claimed run is leased until this time.
    worker_lease_until = Column(DateTime(timezone=True), nullable=True, index=True)
    # Optional, useful for debugging which worker owns the run.
    worker_id = Column(String(255), nullable=True)
    # Global dispatch ticket, assigned from the `runs_dispatch_seq` sequence when
    # the run is promoted to its owner's head-of-line (readiness). NULL = still in
    # the owner's personal queue (not yet dispatch-ready); NOT NULL = promoted into
    # the global dispatch order. This single column is BOTH the "promoted?" marker
    # and the FCFS sort key (readiness order, independent of created_at).
    dispatch_seq = Column(BigInteger, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="runs")
    # Use run_id on File (not input_file_id) for "files attached to this run"
    files = relationship(
        "File",
        back_populates="run",
        foreign_keys="File.run_id",
        cascade="all, delete-orphan",
    )
    jobs = relationship("JobQueue", back_populates="run", cascade="all, delete-orphan")
    trees = relationship("RunTree", back_populates="run", cascade="all, delete-orphan")
    artifacts = relationship("RunArtifact", back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_runs_progress"),
        Index("idx_runs_user_id", "user_id"),
        Index("idx_runs_status", "status"),
        Index("idx_runs_created_at", "created_at"),
        Index("idx_runs_method_id", "method_id"),
        # Drives the dispatcher claim query (ORDER BY dispatch_seq over promoted rows).
        Index("idx_runs_status_dispatch_seq", "status", "dispatch_seq"),
    )


class File(Base):
    """File model - represents uploaded files."""
    __tablename__ = "files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,  # Nullable for backward compatibility
        index=True
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    original_filename = Column(String(255), nullable=False)
    storage_type = Column(
        Enum(StorageType, native_enum=False),
        default=StorageType.LOCAL,
        nullable=False
    )
    # Bucket/container holding the object (object stores); null for local fs.
    storage_bucket = Column(String(255), nullable=True)
    storage_path = Column(Text, nullable=False)
    storage_url = Column(Text, nullable=True)
    file_size = Column(BigInteger, nullable=False)
    mime_type = Column(String(100), nullable=True)
    checksum_sha256 = Column(String(64), nullable=True)
    uploaded_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    expires_at = Column(DateTime(timezone=True), nullable=True)
    # Soft-delete: the stored object is hard-deleted but this metadata row is
    # retained so historical runs still show dataset name/id/size/checksum.
    storage_state = Column(
        Enum(StorageState, native_enum=False),
        default=StorageState.ACTIVE,
        nullable=False,
        index=True,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    object_deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="files", foreign_keys="File.user_id")
    run = relationship("Run", back_populates="files", foreign_keys="File.run_id")

    __table_args__ = (
        Index("idx_files_run_id", "run_id"),
        Index("idx_files_user_id", "user_id"),
    )


class RunTree(Base):
    """Per-tree visualization payload persisted separately from the run JSON result."""

    __tablename__ = "run_trees"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    tree_index = Column(Integer, nullable=False)
    tree_id = Column(String(120), nullable=False)
    newick = Column(Text, nullable=False)
    original_newick = Column(Text, nullable=True)
    display_newick = Column(Text, nullable=True)
    # NOTE: the former `service_image` (base64 JSONB) column has been removed.
    # Tree images are now RunArtifact rows (artifact_role="phylogeny") served
    # via the artifact preview endpoint — no base64 is stored in the DB.
    node_attributes = Column(JSONB, nullable=True)
    lineage_plot = Column(JSONB, nullable=True)
    label_to_sequence_id = Column(JSONB, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    run = relationship("Run", back_populates="trees")

    __table_args__ = (
        UniqueConstraint("run_id", "tree_index", name="uq_run_trees_run_tree_index"),
        UniqueConstraint("run_id", "tree_id", name="uq_run_trees_run_tree_id"),
        Index("idx_run_trees_run_tree_index", "run_id", "tree_index"),
        Index("idx_run_trees_run_tree_id", "run_id", "tree_id"),
    )


class RunArtifact(Base):
    """A generated run output stored as an object in the artifact bucket.

    The DB holds only metadata + a storage reference (bucket/object_key); the
    binary lives in object storage and is streamed lazily through the API.
    No base64 is ever persisted here.
    """

    __tablename__ = "run_artifacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Links an artifact to a specific tree (e.g. a phylogeny image), when applicable.
    tree_id = Column(String(120), nullable=True)

    storage_backend = Column(String(20), nullable=False)
    storage_bucket = Column(String(255), nullable=True)
    object_key = Column(Text, nullable=False)

    filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=True)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    checksum_sha256 = Column(String(64), nullable=True)

    artifact_kind = Column(
        Enum(ArtifactKind, native_enum=False),
        default=ArtifactKind.OTHER,
        nullable=False,
        index=True,
    )
    # Free-form display role, e.g. "phylogeny", "tree_stats", "abundance_rank", "bundle".
    artifact_role = Column(String(50), nullable=True)
    is_previewable = Column(Boolean, default=False, nullable=False)

    storage_state = Column(
        Enum(StorageState, native_enum=False),
        default=StorageState.ACTIVE,
        nullable=False,
        index=True,
    )
    object_deleted_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    run = relationship("Run", back_populates="artifacts")

    __table_args__ = (
        Index("idx_run_artifacts_run_id", "run_id"),
        Index("idx_run_artifacts_run_tree", "run_id", "tree_id"),
        Index("idx_run_artifacts_run_role", "run_id", "artifact_role"),
    )


class JobQueue(Base):
    """Job queue model - tracks RQ jobs."""
    __tablename__ = "job_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    job_id = Column(String(255), unique=True, nullable=False, index=True)
    status = Column(
        Enum(JobStatus, native_enum=False),
        default=JobStatus.QUEUED,
        nullable=False,
        index=True
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)

    # Relationships
    run = relationship("Run", back_populates="jobs")

    __table_args__ = (
        UniqueConstraint("job_id", name="uq_job_queue_job_id"),
        Index("idx_job_queue_run_id", "run_id"),
        Index("idx_job_queue_status", "status"),
    )


class UploadSession(Base):
    """Upload session - decouples file upload from run creation.

    Allows reliable cancellation and cleanup of partial/temporary uploads
    independent of run lifecycle.
    """
    __tablename__ = "upload_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(
        Enum(UploadSessionStatus, native_enum=False),
        default=UploadSessionStatus.INITIATED,
        nullable=False,
        index=True,
    )
    original_filename = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=True)
    expected_size = Column(BigInteger, nullable=True)
    bytes_received = Column(BigInteger, default=0, nullable=False)
    temp_storage_path = Column(Text, nullable=True)
    final_file_id = Column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
    )
    error = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_upload_sessions_user_status", "user_id", "status"),
    )
