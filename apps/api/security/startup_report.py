"""One start-up summary of the sign-in protection, with warnings for settings
that leave a production deployment less protected than intended. Nothing here
blocks start-up: these are choices an operator may make on purpose.
"""
from __future__ import annotations

import logging
import os

from apps.api.auth.verification import verification_mode, verification_required
from apps.api.config import IS_PRODUCTION
from apps.api.security import captcha, rate_limit
from apps.api.services.email import email_enabled

logger = logging.getLogger("phylo.api.security")


def trusted_proxies() -> str:
    """What the web server was told to accept forwarded client addresses from."""
    return (os.getenv("FORWARDED_ALLOW_IPS") or "").strip()


def log_auth_protection() -> None:
    logger.info(
        "sign-in protection: captcha=%s, rate limits=%s, email verification=%s (%s)",
        f"on ({captcha.difficulty_bits()} bits)" if captcha.captcha_enabled() else "OFF",
        "on" if rate_limit.limits_enabled() else "OFF",
        "required" if verification_required() else "not required",
        verification_mode(),
    )
    if not IS_PRODUCTION:
        return
    if not captcha.captcha_enabled():
        logger.warning("CAPTCHA_ENABLED is off: sign-in, sign-up and password reset accept automated requests at no cost")
    if not rate_limit.limits_enabled():
        logger.warning("AUTH_RATE_LIMITS_ENABLED is off: password guessing and mass registration are not limited")
    if not verification_required():
        if verification_mode() == "auto" and not email_enabled():
            logger.warning("email verification is off because no mail server is configured (SMTP_HOST): "
                           "anyone can register any address")
        else:
            logger.warning("EMAIL_VERIFICATION is off: anyone can register any address")
    if trusted_proxies() in ("", "127.0.0.1"):
        logger.warning(
            "FORWARDED_ALLOW_IPS is not set: behind a reverse proxy every visitor appears to come from the "
            "proxy's address and shares one per-address rate limit. Set it to the proxy's address or network "
            "and check with GET /auth/client-ip (docs/DEPLOYMENT.md)"
        )
