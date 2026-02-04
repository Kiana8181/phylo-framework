from __future__ import annotations

from sqlalchemy import Column, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from apps.api.database.base import BaseModel


class Result(BaseModel):
    """Result model for storing run results."""
    __tablename__ = "results"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_results_run_id"),
    )

    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False, unique=True, index=True)
    result_data = Column(JSON, nullable=False)

    # Relationships
    run = relationship("Run", back_populates="result")

