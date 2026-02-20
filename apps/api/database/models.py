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
    files = relationship("File", back_populates="user", cascade="all, delete-orphan")

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
    params = Column(JSONB, nullable=False, default={})
    result = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
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

    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_runs_progress"),
        Index("idx_runs_user_id", "user_id"),
        Index("idx_runs_status", "status"),
        Index("idx_runs_created_at", "created_at"),
        Index("idx_runs_method_id", "method_id"),
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
    storage_path = Column(Text, nullable=False)
    storage_url = Column(Text, nullable=True)
    file_size = Column(BigInteger, nullable=False)
    mime_type = Column(String(100), nullable=True)
    uploaded_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="files")
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
    service_image = Column(JSONB, nullable=True)
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
