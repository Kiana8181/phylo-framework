from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.dependencies import get_current_user, get_current_user_required
from apps.api.auth.google_oauth import exchange_google_code, get_google_oauth_url, verify_google_token
from apps.api.auth.jwt_handler import create_access_token, create_refresh_token, decode_token
from apps.api.auth.password import hash_password, verify_password
from apps.api.config import FRONTEND_URL
from apps.api.database import get_db
from apps.api.database.models import User
from apps.api.repositories.user_repository import UserRepository
from apps.api.services.email import send_email

router = APIRouter(prefix="/auth", tags=["authentication"])

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
    code: Optional[str] = None
    token: Optional[str] = None


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
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {e!s}",
        )


@router.get("/google")
async def google_oauth_url():
    """Get Google OAuth authorization URL."""
    try:
        url = get_google_oauth_url()
        return {"auth_url": url}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Google OAuth not configured: {e}",
        )


@router.post("/google", response_model=TokenResponse)
async def google_oauth(
    auth_data: GoogleAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with Google OAuth."""
    user_repo = UserRepository(db)
    
    # Get user info from Google
    if auth_data.code:
        # Exchange code for user info
        user_info = await exchange_google_code(auth_data.code)
    elif auth_data.token:
        # Verify token directly
        user_info = await verify_google_token(auth_data.token)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'code' or 'token' must be provided",
        )
    
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
        
        # Create user without password (Google OAuth users)
        user = await user_repo.create_user(
            email=email,
            username=username,
            password_hash=hash_password(""),  # Empty password for OAuth users
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


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
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
        html = f"""
        <p>You requested a password reset for your Phylo Runner account.</p>
        <p><a href="{reset_link}">Reset your password</a></p>
        <p>This link expires in {RESET_TOKEN_EXPIRE_HOURS} hour(s). If you didn't request this, ignore this email.</p>
        """
        sent = await send_email(
            to=user.email,
            subject="Reset your password – Phylo Runner",
            html=html.strip(),
        )
        if not sent:
            import logging
            logging.getLogger(__name__).warning(
                "Password reset email could not be sent to %s (check RESEND_API_KEY and server logs)",
                user.email,
            )
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
    
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(UUID(user_id))
    
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
