"""Purpose-bound keys derived from the application's one configured secret.

Signing CAPTCHA challenges, OAuth state and rate-limit bucket names each needs
a secret. They are derived from JWT_SECRET_KEY rather than configured
separately, so there is nothing more to set, and bound to their purpose, so a
value signed for one use is meaningless for another.
"""
from __future__ import annotations

import hashlib
import hmac


def derive_key(purpose: str) -> bytes:
    # Imported here: jwt_handler decides how the secret is loaded (and refuses
    # to run without one in production).
    from apps.api.auth.jwt_handler import JWT_SECRET_KEY

    return hmac.new(JWT_SECRET_KEY.encode("utf-8"), f"phylo/{purpose}/v1".encode("utf-8"), hashlib.sha256).digest()


def sign(purpose: str, message: bytes) -> str:
    return hmac.new(derive_key(purpose), message, hashlib.sha256).hexdigest()


def signature_matches(purpose: str, message: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign(purpose, message), signature or "")
