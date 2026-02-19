from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

import httpx
from fastapi import HTTPException

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:3000/auth/callback")


async def verify_google_token(token: str) -> Optional[dict]:
    """
    Verify Google OAuth token and get user info.
    
    Args:
        token: Google OAuth token (ID token)
        
    Returns:
        User info dict with email, name, etc. or None if invalid
    """
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(500, "Google OAuth not configured")
    
    try:
        # Verify token with Google
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {token}"},
            )
            
            if response.status_code == 200:
                user_info = response.json()
                return {
                    "email": user_info.get("email"),
                    "name": user_info.get("name"),
                    "picture": user_info.get("picture"),
                    "google_id": user_info.get("sub"),
                }
            return None
    except Exception:
        return None


def get_google_oauth_url() -> str:
    """
    Get Google OAuth authorization URL.
    
    Returns:
        Google OAuth authorization URL
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
        raise HTTPException(500, "Google OAuth not configured")
    
    from urllib.parse import urlencode
    
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


async def exchange_google_code(code: str) -> Optional[dict]:
    """
    Exchange Google authorization code for tokens and user info.
    
    Args:
        code: Authorization code from Google
        
    Returns:
        User info dict or None if exchange failed
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        raise HTTPException(500, "Google OAuth not configured")
    
    try:
        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            
            if token_response.status_code != 200:
                return None
            
            tokens = token_response.json()
            access_token = tokens.get("access_token")
            if access_token:
                return await verify_google_token(access_token)
            id_token = tokens.get("id_token")
            if id_token:
                return await verify_google_token(id_token)
            return None
    except Exception:
        return None
