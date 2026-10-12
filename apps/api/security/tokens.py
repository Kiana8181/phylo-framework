"""One-time tokens sent by email, and the OAuth ``state`` value.

Email tokens (password reset, email verification) are random and long, travel
only in the emailed link, and are stored only as a SHA-256 hash: someone who
can read the database cannot use what is stored there to reset a password or
confirm an address. A plain hash is enough because the token has 256 bits of
randomness; there is nothing to brute-force.

The OAuth state is a signed, short-lived value issued when the sign-in with
Google starts and required back when it completes, so a callback that this
application did not start is refused.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Optional

from apps.api.security.keys import sign, signature_matches

OAUTH_STATE_TTL_SECONDS = 600
_STATE_PURPOSE = "oauth-state"


def new_token() -> tuple[str, str]:
    """(token to email, hash to store)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def new_oauth_state() -> str:
    payload = base64.urlsafe_b64encode(json.dumps(
        {"n": secrets.token_urlsafe(16), "e": int(time.time()) + OAUTH_STATE_TTL_SECONDS},
        separators=(",", ":"),
    ).encode("utf-8")).rstrip(b"=").decode("ascii")
    return f"{payload}.{sign(_STATE_PURPOSE, payload.encode('ascii'))}"


def oauth_state_is_valid(state: Optional[str]) -> bool:
    payload, _, signature = (state or "").partition(".")
    if not payload or not signature_matches(_STATE_PURPOSE, payload.encode("ascii", "ignore"), signature):
        return False
    try:
        fields = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return int(fields["e"]) >= time.time()
    except (ValueError, KeyError, TypeError):
        return False
