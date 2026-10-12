from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import jwt

from apps.api.config import IS_PRODUCTION

logger = logging.getLogger(__name__)


def _load_signing_key() -> str:
    """Return the JWT signing key; there is deliberately no built-in default.

    A hard-coded fallback would let anyone who has read this repository forge
    tokens for any deployment that forgot to set the variable. Production
    refuses to start without a key (see security/production_config.py). Outside
    production an unset key becomes a random per-process key: everything works,
    but tokens stop being valid when the process restarts.
    """
    key = (os.getenv("JWT_SECRET_KEY") or "").strip()
    if key:
        return key
    if IS_PRODUCTION:
        raise RuntimeError("JWT_SECRET_KEY must be set in production")
    logger.warning(
        "JWT_SECRET_KEY is not set; using a random key for this process only. "
        "Set it in .env to keep sessions valid across restarts."
    )
    return secrets.token_urlsafe(48)


# JWT Configuration
JWT_SECRET_KEY = _load_signing_key()
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
JWT_REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Data to encode in token (typically {"sub": user_id})
        expires_delta: Optional expiration time delta
        
    Returns:
        Encoded JWT token
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """
    Create a JWT refresh token.
    
    Args:
        data: Data to encode in token
        
    Returns:
        Encoded JWT refresh token
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """
    Decode and verify a JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded token payload or None if invalid
    """
    try:
        # `algorithms` is an explicit allow-list: a token signed with any other
        # algorithm (including "none") is rejected.
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None


def get_user_id_from_token(token: str) -> Optional[UUID]:
    """
    Extract user ID from JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        User ID (UUID) or None if invalid
    """
    payload = decode_token(token)
    if payload and "sub" in payload:
        try:
            return UUID(payload["sub"])
        except (ValueError, TypeError):
            return None
    return None
