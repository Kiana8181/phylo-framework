from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.models import User
from apps.api.security.tokens import hash_token
from apps.api.repositories.base_repository import BaseRepository
from apps.api.utils.datetime_util import utc_now


class UserRepository(BaseRepository[User]):
    """Repository for User model."""

    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email. Addresses are compared without regard to case:
        "Ada@Example.org" and "ada@example.org" are one mailbox and must be one
        account (and one rate-limit key)."""
        result = await self.session.execute(
            select(User).where(func.lower(User.email) == (email or "").strip().lower())
        )
        return result.scalars().first()

    async def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        result = await self.session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def create_user(
        self,
        email: str,
        username: str,
        password_hash: str,
        is_active: bool = True,
        is_admin: bool = False,
        email_verified: bool = False,
    ) -> User:
        """Create a new user."""
        return await self.create(
            email=(email or "").strip().lower(),
            username=username,
            password_hash=password_hash,
            is_active=is_active,
            is_admin=is_admin,
            email_verified_at=utc_now() if email_verified else None,
        )

    async def update_password(self, user_id: UUID, password_hash: str) -> Optional[User]:
        """Update user password."""
        return await self.update(user_id, password_hash=password_hash)

    # ------------------------------------------------------------------ #
    # One-time tokens. Only the SHA-256 of a token is stored (security/tokens.py).
    # ------------------------------------------------------------------ #
    async def set_password_reset_token(
        self, user_id: UUID, token_hash: str, expires: datetime
    ) -> Optional[User]:
        """Store the hash of a reset token and its expiry."""
        return await self.update(
            user_id,
            password_reset_token=token_hash,
            password_reset_expires=expires,
        )

    async def get_by_reset_token(self, token: str) -> Optional[User]:
        """The user a reset token belongs to, if it is still valid."""
        if not token:
            return None
        result = await self.session.execute(
            select(User).where(
                User.password_reset_token == hash_token(token),
                User.password_reset_expires.isnot(None),
                User.password_reset_expires > utc_now(),
            )
        )
        return result.scalar_one_or_none()

    async def clear_password_reset_token(self, user_id: UUID) -> Optional[User]:
        """Clear password reset token after use."""
        return await self.update(
            user_id,
            password_reset_token=None,
            password_reset_expires=None,
        )

    async def set_verification_token(
        self, user_id: UUID, token_hash: str, expires: datetime
    ) -> Optional[User]:
        return await self.update(
            user_id,
            email_verification_token=token_hash,
            email_verification_expires=expires,
        )

    async def get_by_verification_token(self, token: str) -> Optional[User]:
        """The user a verification token belongs to, if it is still valid."""
        if not token:
            return None
        result = await self.session.execute(
            select(User).where(
                User.email_verification_token == hash_token(token),
                User.email_verification_expires.isnot(None),
                User.email_verification_expires > utc_now(),
            )
        )
        return result.scalar_one_or_none()

    async def mark_email_verified(self, user_id: UUID) -> Optional[User]:
        """Record that the address is confirmed; the link cannot be used again."""
        return await self.update(
            user_id,
            email_verified_at=utc_now(),
            email_verification_token=None,
            email_verification_expires=None,
        )

    async def invalidate_sessions(self, user_id: UUID) -> Optional[User]:
        """Refuse every session issued up to now (see User.tokens_valid_after)."""
        return await self.update(user_id, tokens_valid_after=utc_now())
