from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.models import User
from apps.api.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User model."""

    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        result = await self.session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_by_reset_token(self, token: str) -> Optional[User]:
        """Get user by valid password reset token (not expired)."""
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(User).where(
                User.password_reset_token == token,
                User.password_reset_expires != None,
                User.password_reset_expires > now,
            )
        )
        return result.scalar_one_or_none()

    async def create_user(
        self,
        email: str,
        username: str,
        password_hash: str,
        is_active: bool = True,
        is_admin: bool = False,
    ) -> User:
        """Create a new user."""
        return await self.create(
            email=email,
            username=username,
            password_hash=password_hash,
            is_active=is_active,
            is_admin=is_admin,
        )

    async def update_password(self, user_id: UUID, password_hash: str) -> Optional[User]:
        """Update user password."""
        return await self.update(user_id, password_hash=password_hash)

    async def set_password_reset_token(
        self, user_id: UUID, token: str, expires: datetime
    ) -> Optional[User]:
        """Set password reset token and expiry."""
        return await self.update(
            user_id,
            password_reset_token=token,
            password_reset_expires=expires,
        )

    async def clear_password_reset_token(self, user_id: UUID) -> Optional[User]:
        """Clear password reset token after use."""
        return await self.update(
            user_id,
            password_reset_token=None,
            password_reset_expires=None,
        )
