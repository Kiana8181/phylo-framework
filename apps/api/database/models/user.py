from __future__ import annotations

from sqlalchemy import Column, String, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID, SQLAlchemyBaseOAuthAccountTableUUID
from apps.api.database.database import Base


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    """OAuth account model for FastAPI Users."""
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    """User model with OAuth support."""
    __tablename__ = "users"

    oauth_accounts: list[OAuthAccount] = relationship("OAuthAccount", lazy="joined")

