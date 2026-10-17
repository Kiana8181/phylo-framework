from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.dependencies import get_current_user, get_current_user_required
from apps.api.auth.google_oauth import exchange_google_code, get_google_oauth_url
from apps.api.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    decode_token,
    issued_before,
)
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
from apps.api.auth.verification import is_verified, verification_expire_hours, verification_required
from apps.api.security import captcha, rate_limit
from apps.api.security.errors import internal_error
from apps.api.security.tokens import new_oauth_state, new_token, oauth_state_is_valid
from apps.api.services import email_templates
from apps.api.services.email import EmailError, EmailNotConfigured, send_email

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = logging.getLogger("phylo.api.auth")

RESET_TOKEN_EXPIRE_HOURS = 1


# Request/Response Models
class CaptchaSolution(BaseModel):
    """Answer to a challenge from GET /auth/challenge (see security/captcha.py)."""
    challenge: str
    counter: int


class UserRegister(BaseModel):
    email: EmailStr
    username: str
    password: str
    captcha: Optional[CaptchaSolution] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    captcha: Optional[CaptchaSolution] = None


class GoogleAuthRequest(BaseModel):
    # Authorization-code flow only. A raw Google token is not accepted: the
    # userinfo endpoint cannot prove a token was issued to *this* application,
    # so a token obtained by any other app would sign its bearer in here.
    code: Optional[str] = None
    # The value this API issued with the authorization URL, returned by Google.
    state: Optional[str] = None


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
    email_verified: bool = True
    # False while this deployment does not ask for confirmed addresses.
    verification_required: bool = False


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
REGISTRATION_ACCEPTED = (
    "If this email address can be registered, we have sent a confirmation link to it. "
    "Open the link to finish creating your account."
)
_timing_equalizer_hash: Optional[str] = None


def _spend_password_check_time(password: str) -> None:
    """Do the work of a password comparison when there is no account to compare
    with, so that "no such account" takes as long as "wrong password" and
    timing does not reveal which addresses have an account."""
    global _timing_equalizer_hash
    if _timing_equalizer_hash is None:
        _timing_equalizer_hash = hash_password("timing-equalizer-not-a-real-password")
    verify_password(password or "x", _timing_equalizer_hash)


def client_ip(request: Request) -> Optional[str]:
    """Address of the client as the web server reports it. Behind a reverse
    proxy this is the visitor's address only when FORWARDED_ALLOW_IPS names the
    proxy (docs/DEPLOYMENT.md); otherwise it is the proxy's."""
    return request.client.host if request.client else None


def _user_payload(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "email_verified": is_verified(user),
        "verification_required": verification_required(),
    }


def _session(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(data={"sub": str(user.id)}),
        refresh_token=create_refresh_token(data={"sub": str(user.id)}),
        user=_user_payload(user),
    )


def _too_many(exc: rate_limit.RateLimited) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": rate_limit.CODE_RATE_LIMITED,
            "message": "Too many attempts. Please wait and try again.",
            "retry_after_seconds": exc.retry_after_seconds,
        },
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


async def _limit(db: AsyncSession, name: str, key: Optional[str]) -> None:
    """Count one event against a limit; 429 when it is used up."""
    try:
        await rate_limit.hit(db, name, key)
    except rate_limit.RateLimited as exc:
        raise _too_many(exc) from None


async def _captcha(solution: Optional[CaptchaSolution], db: AsyncSession) -> None:
    try:
        await captcha.require_captcha(solution.model_dump() if solution else None, db)
    except captcha.CaptchaError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from None


async def _deliver(kind: str, to: str, content: email_templates.EmailContent, *, dev_link: Optional[str] = None) -> None:
    """Send one account email. Runs after the response has gone out, so neither
    a slow nor an unavailable mail server delays or changes the answer."""
    try:
        await send_email(to, content.subject, content.text, content.html)
    except EmailNotConfigured as exc:
        logger.warning("%s email not sent to %s: %s", kind, to, exc)
        if dev_link and not IS_PRODUCTION:
            # Development without a mail server: the link is the only way to continue.
            logger.warning("%s link (development only): %s", kind, dev_link)
    except EmailError as exc:
        logger.warning("%s email could not be sent to %s: %s", kind, to, exc)
    except Exception:  # noqa: BLE001 - a background task must not fail loudly
        logger.exception("%s email to %s failed unexpectedly", kind, to)


async def _send_password_reset(to: str, reset_link: str) -> None:
    content = email_templates.password_reset(reset_link=reset_link, expires_hours=RESET_TOKEN_EXPIRE_HOURS)
    await _deliver("password reset", to, content, dev_link=reset_link)


async def _send_verification(to: str, link: str) -> None:
    content = email_templates.email_verification(verification_link=link, expires_hours=verification_expire_hours())
    await _deliver("email verification", to, content, dev_link=link)


async def _send_account_exists(to: str) -> None:
    content = email_templates.account_already_exists(
        login_link=f"{FRONTEND_URL}/auth", reset_link=f"{FRONTEND_URL}/auth/forgot-password"
    )
    await _deliver("account exists", to, content)


async def _start_verification(user: User, user_repo: UserRepository, background_tasks: BackgroundTasks) -> None:
    """Issue a new confirmation link for the account and email it."""
    token, token_hash = new_token()
    expires = datetime.now(timezone.utc) + timedelta(hours=verification_expire_hours())
    await user_repo.set_verification_token(user.id, token_hash, expires)
    background_tasks.add_task(_send_verification, user.email, f"{FRONTEND_URL}/auth/verify-email?token={token}")


async def _verification_mail_allowed(db: AsyncSession, email: str) -> bool:
    """Whether another account email may go to this address now (per-account
    limit). Never raises: the registration answer must not depend on it."""
    try:
        await rate_limit.hit(db, "VERIFY_ACCOUNT", email)
        return True
    except rate_limit.RateLimited:
        return False


@router.get("/challenge")
async def captcha_challenge():
    """A CAPTCHA challenge for the sign-in, sign-up and password-reset forms,
    or ``{"enabled": false}`` when the check is switched off."""
    return captcha.challenge_response()


@router.get("/client-ip")
async def whoami_ip(request: Request):
    """The address this API sees the caller coming from. For checking the
    reverse-proxy configuration: behind a proxy it must be your own address,
    not the proxy's (docs/DEPLOYMENT.md)."""
    return {"client_ip": client_ip(request)}


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserRegister,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user with username/password.

    While email verification is required the answer is the same whether or not
    the address already has an account (202 and a neutral message): what
    happened is told to the mailbox, not to the caller. The account can be used
    once the emailed link has been opened.
    """
    await _limit(db, "REGISTER_IP", client_ip(request))
    await _captcha(user_data.captcha, db)

    policy_error = password_policy_error(user_data.password)
    if policy_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=policy_error)

    user_repo = UserRepository(db)
    # Checked before the address so that this answer says nothing about it.
    if await user_repo.get_by_username(user_data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )

    # Hashed in every case, so the response time does not depend on whether
    # the address is already registered.
    password_hash = hash_password(user_data.password)
    existing_user = await user_repo.get_by_email(user_data.email)

    if not verification_required():
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )
        user = await user_repo.create_user(
            email=user_data.email, username=user_data.username, password_hash=password_hash,
        )
        return _session(user)

    if existing_user is None:
        user = await user_repo.create_user(
            email=user_data.email, username=user_data.username, password_hash=password_hash,
        )
        if await _verification_mail_allowed(db, user.email):
            await _start_verification(user, user_repo, background_tasks)
    elif await _verification_mail_allowed(db, existing_user.email):
        if is_verified(existing_user):
            background_tasks.add_task(_send_account_exists, existing_user.email)
        else:
            # Probably the same person trying again: send a fresh link. The
            # password of the existing account is not changed.
            await _start_verification(existing_user, user_repo, background_tasks)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"verification_required": True, "message": REGISTRATION_ACCEPTED},
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: UserLogin,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Login with username/password."""
    await _limit(db, "LOGIN_IP", client_ip(request))
    # Failed attempts are counted per account; once the limit is reached the
    # account accepts no attempt, right or wrong, until the window ends.
    try:
        await rate_limit.check(db, "LOGIN_ACCOUNT", credentials.email)
    except rate_limit.RateLimited as exc:
        raise _too_many(exc) from None
    await _captcha(credentials.captcha, db)
    try:
        user_repo = UserRepository(db)
        user = await user_repo.get_by_email(credentials.email)
        # verify_password rejects an empty password and accounts without a
        # usable password (Google sign-in) before any hash comparison.
        if user is None:
            _spend_password_check_time(credentials.password)
            password_ok = False
        else:
            password_ok = verify_password(credentials.password, user.password_hash)
        if not password_ok:
            await rate_limit.record(db, "LOGIN_ACCOUNT", credentials.email)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )
        return _session(user)
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("Login failed.", e)


@router.get("/google")
async def google_oauth_url():
    """Get Google OAuth authorization URL, with the ``state`` value the caller
    must keep and send back with the authorization code."""
    try:
        state = new_oauth_state()
        return {"auth_url": get_google_oauth_url(state), "state": state}
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
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with Google OAuth."""
    await _limit(db, "LOGIN_IP", client_ip(request))
    user_repo = UserRepository(db)
    
    # Exchange the authorization code (issued to this application's client id)
    # for the user's identity.
    if not auth_data.code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An authorization 'code' must be provided",
        )
    # Only a sign-in that this application started may be completed.
    if not oauth_state_is_valid(auth_data.state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "OAUTH_STATE_INVALID",
                    "message": "This sign-in attempt is not valid or has expired. Please start again."},
        )
    user_info = await exchange_google_code(auth_data.code)
    
    if not user_info or not user_info.get("email"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to authenticate with Google",
        )
    # Google must itself have confirmed the address: otherwise anyone could
    # sign in as the owner of an address they merely typed into a Google form.
    if not user_info.get("email_verified"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google has not verified this email address.",
        )
    
    email = user_info["email"]
    
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
            email_verified=True,
        )
    elif not is_verified(user):
        # The account was created with a password by someone who never proved
        # they own this address; Google now vouches for the person signing in.
        # The account passes to them: the unproven password and every session
        # made with it stop working.
        await user_repo.update_password(user.id, unusable_password_hash())
        await user_repo.invalidate_sessions(user.id)
        user = await user_repo.mark_email_verified(user.id) or user
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    
    return _session(user)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    captcha: Optional[CaptchaSolution] = None


class VerifyEmailRequest(BaseModel):
    token: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Request a password reset link. Always returns success to avoid email enumeration."""
    await _limit(db, "FORGOT_IP", client_ip(request))
    await _captcha(body.captcha, db)
    # Per address typed in, whether or not it has an account: bounds how many
    # reset emails one mailbox can be sent, without revealing anything.
    await _limit(db, "FORGOT_ACCOUNT", body.email)
    user_repo = UserRepository(db)
    user = await user_repo.get_by_email(body.email)
    if user:
        token, token_hash = new_token()
        expires = datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_EXPIRE_HOURS)
        await user_repo.set_password_reset_token(user.id, token_hash, expires)
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
    # Every session made with the old password ends here.
    await user_repo.invalidate_sessions(user.id)
    # The link arrived in this mailbox and was used: the address is proven.
    if not is_verified(user):
        await user_repo.mark_email_verified(user.id)
    return {"message": "Password has been reset. You can now log in."}


@router.post("/verify-email", response_model=TokenResponse)
async def verify_email(
    body: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Confirm an email address with the token from the emailed link, and sign
    the account in. A link works once and until it expires."""
    user_repo = UserRepository(db)
    user = await user_repo.get_by_verification_token(body.token)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VERIFICATION_LINK_INVALID",
                    "message": "This confirmation link is not valid or has expired. "
                               "Log in to request a new one."},
        )
    user = await user_repo.mark_email_verified(user.id) or user
    return _session(user)


@router.post("/resend-verification")
async def resend_verification(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Send the signed-in account a new confirmation link."""
    if is_verified(current_user):
        return {"email_verified": True, "message": "Your email address is already confirmed."}
    await _limit(db, "VERIFY_IP", client_ip(request))
    await _limit(db, "VERIFY_ACCOUNT", current_user.email)
    await _start_verification(current_user, UserRepository(db), background_tasks)
    return {"email_verified": False, "message": f"We sent a new confirmation link to {current_user.email}."}


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
    # A refresh token from before a password reset cannot renew the session.
    if issued_before(payload, user.tokens_valid_after):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )
    
    return _session(user)


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
        email_verified=is_verified(current_user),
        verification_required=verification_required(),
    )


@router.post("/logout")
async def logout():
    """Logout (client should discard tokens)."""
    return {"message": "Logged out successfully"}
