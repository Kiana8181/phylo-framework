from __future__ import annotations

import uuid
from fastapi import APIRouter
from fastapi_users import FastAPIUsers

from apps.api.database.models.user import User
from apps.api.auth.dependencies import get_user_manager
from apps.api.auth.config import SECRET, GOOGLE_CLIENT_ID_VALUE, GOOGLE_CLIENT_SECRET_VALUE
from apps.api.auth.google_oauth import auth_backend

# Create FastAPI Users instance
fastapi_users = FastAPIUsers[User, uuid.UUID](
    get_user_manager,
    [auth_backend],
)

# Create auth router
router = APIRouter()

# Include FastAPI Users routes
router.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth",
    tags=["auth"],
)

router.include_router(
    fastapi_users.get_register_router(),
    prefix="/auth",
    tags=["auth"],
)

router.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="/auth",
    tags=["auth"],
)

router.include_router(
    fastapi_users.get_verify_router(),
    prefix="/auth",
    tags=["auth"],
)

# Google OAuth (if configured)
if GOOGLE_CLIENT_ID_VALUE and GOOGLE_CLIENT_SECRET_VALUE:
    from fastapi_users_db_sqlalchemy import SQLAlchemyOAuthAccount
    from httpx_oauth import GoogleOAuth2
    
    google_oauth_client = GoogleOAuth2(
        GOOGLE_CLIENT_ID_VALUE,
        GOOGLE_CLIENT_SECRET_VALUE,
    )
    
    router.include_router(
        fastapi_users.get_oauth_router(
            google_oauth_client,
            auth_backend,
            SECRET,
            is_verified_by_default=True,
        ),
        prefix="/auth/google",
        tags=["auth"],
    )

