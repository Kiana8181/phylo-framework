"""CAPTCHA for the sign-in, sign-up and password-reset forms.

The check is a self-hosted proof of work: no third-party service sees the
visitor, nothing has to be reachable from the server or from the visitor's
network, and there is no image or puzzle to solve by hand.

How it works
    1. The client asks for a challenge (GET /auth/challenge). The server hands
       out a random value, a difficulty and an expiry, signed so that the
       client cannot alter any of them. Nothing is stored for it.
    2. The client searches for a number ``counter`` such that
       SHA-256("<challenge>:<counter>") starts with ``difficulty`` zero bits.
       On average that takes 2^difficulty hash computations: a fraction of a
       second in a browser at the default, once per form submission.
    3. The client sends challenge and counter with the form. The server checks
       the signature, the expiry and the hash (one hash computation), and
       records the challenge as used so that one solution cannot be replayed.

What it is and is not
    It makes every attempt cost computing time, which is negligible for a
    person and adds up for a script that tries thousands of passwords or
    registrations. It does not tell a person from a program, and someone
    willing to spend the computing time can pay it. The limits in
    rate_limit.py are what bounds the number of attempts; this raises their
    price.

Settings
    CAPTCHA_ENABLED            true (default) | false
    CAPTCHA_DIFFICULTY_BITS    leading zero bits required (default 18, i.e.
                               about 262 000 hash computations on average)
    CAPTCHA_TTL_SECONDS        how long a challenge may be used (default 300)

The provider is behind a small interface (issue / verify), so a different
mechanism can replace it without touching the routes.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.security.keys import sign, signature_matches

DEFAULT_DIFFICULTY_BITS = 18
MIN_DIFFICULTY_BITS = 1
MAX_DIFFICULTY_BITS = 30
DEFAULT_TTL_SECONDS = 300
ALGORITHM = "sha256-leading-zero-bits"
_PURPOSE = "captcha"
MAX_COUNTER = 2**53  # largest integer a JavaScript client can count to exactly

CODE_REQUIRED = "CAPTCHA_REQUIRED"
CODE_INVALID = "CAPTCHA_INVALID"


def captcha_enabled() -> bool:
    return (os.getenv("CAPTCHA_ENABLED") or "true").strip().lower() not in ("0", "false", "no", "off")


def difficulty_bits() -> int:
    try:
        value = int((os.getenv("CAPTCHA_DIFFICULTY_BITS") or "").strip() or DEFAULT_DIFFICULTY_BITS)
    except ValueError:
        return DEFAULT_DIFFICULTY_BITS
    return value if MIN_DIFFICULTY_BITS <= value <= MAX_DIFFICULTY_BITS else DEFAULT_DIFFICULTY_BITS


def ttl_seconds() -> int:
    try:
        value = int((os.getenv("CAPTCHA_TTL_SECONDS") or "").strip() or DEFAULT_TTL_SECONDS)
    except ValueError:
        return DEFAULT_TTL_SECONDS
    return value if value > 0 else DEFAULT_TTL_SECONDS


class CaptchaError(Exception):
    """The request carries no acceptable solution."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Challenge:
    challenge: str
    difficulty: int
    expires_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "algorithm": ALGORITHM,
            "challenge": self.challenge,
            "difficulty": self.difficulty,
            "expires_at": self.expires_at.isoformat(),
        }


class CaptchaProvider(Protocol):
    def issue(self) -> Challenge: ...

    async def verify(self, solution: Optional[dict[str, Any]], db: AsyncSession) -> None:
        """Return normally when the solution is acceptable; raise CaptchaError otherwise."""


def leading_zero_bits(digest: bytes) -> int:
    bits = 0
    for byte in digest:
        if byte == 0:
            bits += 8
            continue
        bits += 8 - byte.bit_length()
        break
    return bits


def solution_hash(challenge: str, counter: int) -> bytes:
    return hashlib.sha256(f"{challenge}:{counter}".encode("utf-8")).digest()


def solve(challenge: str, difficulty: int) -> int:
    """Find a counter for a challenge. For tests and non-browser clients; the
    web client has its own implementation of the same search."""
    counter = 0
    while leading_zero_bits(solution_hash(challenge, counter)) < difficulty:
        counter += 1
    return counter


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


class ProofOfWorkCaptcha:
    """Self-hosted proof-of-work challenges (see the module documentation)."""

    def issue(self) -> Challenge:
        expires = int(time.time()) + ttl_seconds()
        payload = _b64(json.dumps(
            {"n": secrets.token_urlsafe(16), "d": difficulty_bits(), "e": expires},
            separators=(",", ":"), sort_keys=True,
        ).encode("utf-8"))
        return Challenge(
            challenge=f"{payload}.{sign(_PURPOSE, payload.encode('ascii'))}",
            difficulty=difficulty_bits(),
            expires_at=datetime.fromtimestamp(expires, tz=timezone.utc),
        )

    async def verify(self, solution: Optional[dict[str, Any]], db: AsyncSession) -> None:
        if not isinstance(solution, dict) or not solution.get("challenge"):
            raise CaptchaError(CODE_REQUIRED, "A security check is required. Please try again.")
        challenge = str(solution.get("challenge"))
        invalid = CaptchaError(CODE_INVALID, "The security check failed or expired. Please try again.")
        try:
            counter = int(solution.get("counter"))
        except (TypeError, ValueError):
            raise invalid from None
        if isinstance(solution.get("counter"), bool) or not 0 <= counter < MAX_COUNTER:
            raise invalid

        payload, _, signature = challenge.partition(".")
        if not payload or not signature_matches(_PURPOSE, payload.encode("ascii", "ignore"), signature):
            raise invalid                                   # not issued by this server, or altered
        try:
            fields = json.loads(_unb64(payload))
            nonce, difficulty, expires = str(fields["n"]), int(fields["d"]), int(fields["e"])
        except (ValueError, KeyError, TypeError):
            raise invalid from None
        if expires < time.time():
            raise invalid
        # The difficulty is the one signed into the challenge: a client cannot
        # choose an easier one, and raising the setting does not break
        # challenges that are already out.
        if leading_zero_bits(solution_hash(challenge, counter)) < difficulty:
            raise invalid

        # One use only. The first request to record the challenge wins; a
        # replay (or a second concurrent request) finds it already there.
        result = await db.execute(
            text(
                "INSERT INTO captcha_used (nonce, expires_at) VALUES (:nonce, :expires) "
                "ON CONFLICT (nonce) DO NOTHING"
            ),
            {"nonce": nonce, "expires": datetime.fromtimestamp(expires, tz=timezone.utc)},
        )
        if (result.rowcount or 0) != 1:
            await db.rollback()
            raise invalid
        if secrets.randbelow(50) == 0:                      # keep the table small
            await db.execute(text("DELETE FROM captcha_used WHERE expires_at < now() - interval '1 hour'"))
        await db.commit()


_provider: CaptchaProvider = ProofOfWorkCaptcha()


def provider() -> CaptchaProvider:
    return _provider


def challenge_response() -> dict[str, Any]:
    """Body of GET /auth/challenge."""
    if not captcha_enabled():
        return {"enabled": False}
    return provider().issue().as_dict()


async def require_captcha(solution: Optional[dict[str, Any]], db: AsyncSession) -> None:
    """Gate for a protected route. Does nothing when CAPTCHA is switched off."""
    if captcha_enabled():
        await provider().verify(solution, db)
