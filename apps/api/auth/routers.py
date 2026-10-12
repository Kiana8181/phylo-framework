from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.dependencies import get_current_user, get_current_user_required
from apps.api.auth.google_oauth import exchange_google_code, get_google_oauth_url
from apps.api.auth.jwt_handler import create_access_token, create_refresh_token, decode_token
from apps.api.auth.password import (
    hash_password,
    password_policy_error,
    unusable_password_hash,
    verify_password,
)
from apps.api.config import FRONTEND_URL, IS_PRODUCTION
from apps.api.database import get_db
from apps.api.database.models import User
from apps.api.repositories.user_repository import UserRepository
from apps.api.security.errors import internal_error
from apps.api.services import email_templates
from apps.api.services.email import EmailError, EmailNotConfigured, send_email

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = logging.getLogger("phylo.api.auth")

RESET_TOKEN_EXPIRE_HOURS = 1


# Request/Response Models
class UserRegister(BaseModel):
    email: EmailStr
    username: str
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    # Authorization-code flow only. A raw Google token is not accepted: the
    # userinfo endpoint cannot prove a token was issued to *this* application,
    # so a token obtained by any other app would sign its bearer in here.
    code: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    id: UUID
    email: str
    username: str
    is_active: bool
    is_admin: bool


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserRegister,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user with username/password."""
    policy_error = password_policy_error(user_data.password)
    if policy_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=policy_error)

    user_repo = UserRepository(db)
    
    # Check if user already exists
    existing_user = await user_repo.get_by_email(user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    existing_username = await user_repo.get_by_username(user_data.username)
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )
    
    # Create user
    password_hash = hash_password(user_data.password)
    user = await user_repo.create_user(
        email=user_data.email,
        username=user_data.username,
        password_hash=password_hash,
    )
    
    # Create tokens
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user={
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
        },
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: UserLogin,
    db: AsyncSession = Depends(get_db),
):
    """Login with username/password."""
    try:
        user_repo = UserRepository(db)
        user = await user_repo.get_by_email(credentials.email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )
        # verify_password rejects an empty password and accounts without a
        # usable password (Google sign-in) before any hash comparison.
        if not verify_password(credentials.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )
        access_token = create_access_token(data={"sub": str(user.id)})
        refresh_token = create_refresh_token(data={"sub": str(user.id)})
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user={
                "id": str(user.id),
                "email": user.email,
                "username": user.username,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("Login failed.", e)


@router.get("/google")
async def google_oauth_url():
    """Get Google OAuth authorization URL."""
    try:
        url = get_google_oauth_url()
        return {"auth_url": url}
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not available.",
        )
    except Exception as e:
        raise internal_error("Google sign-in is not available.", e)


@router.post("/google", response_model=TokenResponse)
async def google_oauth(
    auth_data: GoogleAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with Google OAuth."""
    user_repo = UserRepository(db)
    
    # Exchange the authorization code (issued to this application's client id)
    # for the user's identity.
    if not auth_data.code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An authorization 'code' must be provided",
        )
    user_info = await exchange_google_code(auth_data.code)
    
    if not user_info or not user_info.get("email"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to authenticate with Google",
        )
    
    email = user_info["email"]
    name = user_info.get("name", email.split("@")[0])
    google_id = user_info.get("google_id")
    
    # Find or create user
    user = await user_repo.get_by_email(email)
    if not user:
        # Create new user
        username = email.split("@")[0]
        # Ensure username is unique
        base_username = username
        counter = 1
        while await user_repo.get_by_username(username):
            username = f"{base_username}{counter}"
            counter += 1
        
        # Google-only account: no password exists, so store a marker that no
        # input can verify against (never a hash of the empty string).
        user = await user_repo.create_user(
            email=email,
            username=username,
            password_hash=unusable_password_hash(),
            is_active=True,
        )
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    
    # Create tokens
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user={
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
        },
    )


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


async def _send_password_reset(to: str, reset_link: str) -> None:
    """Send the reset email. Runs after the response has gone out, so neither a
    slow nor an unavailable mail server delays or changes the answer."""
    content = email_templates.password_reset(reset_link=reset_link, expires_hours=RESET_TOKEN_EXPIRE_HOURS)
    try:
        await send_email(to, content.subject, content.text, content.html)
    except EmailNotConfigured as exc:
        logger.warning("password reset email not sent to %s: %s", to, exc)
        if not IS_PRODUCTION:
            # Development without a mail server: the link is the only way to continue.
            logger.warning("password reset link (development only): %s", reset_link)
    except EmailError as exc:
        logger.warning("password reset email could not be sent to %s: %s", to, exc)
    except Exception:  # noqa: BLE001 - a background task must not fail loudly
        logger.exception("password reset email to %s failed unexpectedly", to)


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Request a password reset link. Always returns success to avoid email enumeration."""
    user_repo = UserRepository(db)
    user = await user_repo.get_by_email(body.email)
    if user:
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_EXPIRE_HOURS)
        await user_repo.set_password_reset_token(user.id, token, expires)
        reset_link = f"{FRONTEND_URL}/auth/reset-password?token={token}"
        background_tasks.add_task(_send_password_reset, user.email, reset_link)
    return {
        "message": "If an account exists with this email, you will receive password reset instructions.",
    }


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reset password using the token from forgot-password."""
    user_repo = UserRepository(db)
    user = await user_repo.get_by_reset_token(body.token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    policy_error = password_policy_error(body.new_password)
    if policy_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=policy_error)
    password_hash = hash_password(body.new_password)
    await user_repo.update_password(user.id, password_hash)
    await user_repo.clear_password_reset_token(user.id)
    return {"message": "Password has been reset. You can now log in."}


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Refresh access token using refresh token."""
    payload = decode_token(request.refresh_token)
    
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    
    try:
        parsed_user_id = UUID(user_id)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(parsed_user_id)
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    
    # Create new tokens
    new_access_token = create_access_token(data={"sub": str(user.id)})
    new_refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        user={
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
        },
    )


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user_required),
):
    """Get current authenticated user info."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        username=current_user.username,
        is_active=current_user.is_active,
        is_admin=current_user.is_admin,
    )


@router.post("/logout")
async def logout():
    """Logout (client should discard tokens)."""
    return {"message": "Logged out successfully"}
