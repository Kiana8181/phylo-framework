"""Whether accounts must confirm their email address before they may use the
service, and the dependency that enforces it.

EMAIL_VERIFICATION
    auto      (default) required when a mail server is configured, otherwise
              not: without one no confirmation link could ever be delivered,
              and nobody could sign up
    required  always required
    off       never required

While it is required, an account that has not confirmed its address can sign
in, see what it needs to do and ask for a new link, but cannot upload data or
create runs, and receives no run notifications.

An address counts as confirmed when a link sent to it was used (the
confirmation link, or a password-reset link) or when Google vouched for it at
sign-in. Accounts that existed before verification was introduced are
confirmed by the migration that introduced it.
"""
from __future__ import annotations

import os

from fastapi import Depends, HTTPException, status

from apps.api.auth.dependencies import get_current_user_required
from apps.api.database.models import User
from apps.api.services.email import email_enabled

CODE_EMAIL_NOT_VERIFIED = "EMAIL_NOT_VERIFIED"
DEFAULT_EXPIRE_HOURS = 24


def verification_mode() -> str:
    mode = (os.getenv("EMAIL_VERIFICATION") or "auto").strip().lower()
    return mode if mode in ("auto", "required", "off") else "auto"


def verification_required() -> bool:
    mode = verification_mode()
    if mode == "required":
        return True
    if mode == "off":
        return False
    return email_enabled()


def verification_expire_hours() -> int:
    try:
        hours = int((os.getenv("EMAIL_VERIFICATION_EXPIRE_HOURS") or "").strip() or DEFAULT_EXPIRE_HOURS)
    except ValueError:
        return DEFAULT_EXPIRE_HOURS
    return hours if hours > 0 else DEFAULT_EXPIRE_HOURS


def is_verified(user: User) -> bool:
    return user.email_verified_at is not None


def may_use_service(user: User) -> bool:
    return is_verified(user) or not verification_required()


async def require_verified_user(current_user: User = Depends(get_current_user_required)) -> User:
    """The signed-in user, provided the email address is confirmed (when that is required)."""
    if not may_use_service(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": CODE_EMAIL_NOT_VERIFIED,
                "message": "Please confirm your email address first. We sent you a link; "
                           "you can request a new one from your dashboard.",
            },
        )
    return current_user
