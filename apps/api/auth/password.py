from __future__ import annotations

from passlib.context import CryptContext
from passlib.exc import UnknownHashError

from apps.api.config import PASSWORD_MIN_LENGTH

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Upper bound on accepted password length. bcrypt only reads the first 72 bytes,
# and an unbounded input would let a caller make the server hash megabytes.
PASSWORD_MAX_LENGTH = 128

# Stored in ``users.password_hash`` for accounts that have no password (created
# through Google sign-in). It is not a bcrypt hash, so no input can ever verify
# against it; such a user signs in with Google or sets a password through the
# reset flow.
UNUSABLE_PASSWORD_HASH = "!unusable"


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.
    
    Args:
        password: Plain text password
        
    Returns:
        Hashed password
    """
    return pwd_context.hash(password)


def unusable_password_hash() -> str:
    """Hash value for an account that must not be able to log in with a password."""
    return UNUSABLE_PASSWORD_HASH


def is_usable_password_hash(hashed_password: str | None) -> bool:
    return bool(hashed_password) and not str(hashed_password).startswith("!")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hash.

    An empty or over-long password, an unusable hash, or a malformed hash is
    always a failed verification, never an error.
    
    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to verify against
        
    Returns:
        True if password matches, False otherwise
    """
    if not plain_password or len(plain_password) > PASSWORD_MAX_LENGTH:
        return False
    if not is_usable_password_hash(hashed_password):
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except (UnknownHashError, ValueError):
        return False


def password_policy_error(password: str) -> str | None:
    """Return why ``password`` may not be chosen, or None when it is acceptable."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters long."
    if len(password) > PASSWORD_MAX_LENGTH:
        return f"Password must be at most {PASSWORD_MAX_LENGTH} characters long."
    return None
