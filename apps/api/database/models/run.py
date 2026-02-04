from __future__ import annotations

from sqlalchemy import Column, String, Integer, Text, ForeignKey, Enum as SQLEnum, JSON, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from apps.api.database.base import BaseModel


class RunStatus(str, enum.Enum):
    """Run status enumeration."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    ERROR = "ERROR"


class Run(BaseModel):
    """Run model for tracking method executions."""
    __tablename__ = "runs"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    method_id = Column(String, nullable=False, index=True)
    status = Column(SQLEnum(RunStatus), default=RunStatus.PENDING, nullable=False, index=True)
    progress = Column(Integer, default=0, nullable=False)
    message = Column(String, nullable=True)
    file_path = Column(String, nullable=True)
    params = Column(JSON, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", backref="runs")
    result = relationship("Result", back_populates="run", uselist=False)

