from __future__ import annotations

from sqlalchemy import Column, String, DateTime, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from apps.api.database.base import BaseModel


class MethodSpec(BaseModel):
    """MethodSpec model for caching method specifications."""
    __tablename__ = "method_specs"
    __table_args__ = (
        UniqueConstraint("method_id", name="uq_method_specs_method_id"),
    )

    method_id = Column(String, nullable=False, unique=True, index=True)
    spec_data = Column(JSON, nullable=False)
    cached_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)

