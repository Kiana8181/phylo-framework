"""Rate limits for the authentication routes, counted in PostgreSQL.

Every limit is "at most N events per S seconds for one key", where the key is a
client address or an account (an email address, whether or not an account
exists for it). Counting uses fixed windows aligned to the clock: simple, one
row per key and window, and atomic (INSERT ... ON CONFLICT DO UPDATE). At a
window boundary a client can spend two windows' worth in quick succession; the
limits are chosen with that in mind.

No Redis or other service is needed, and the limits hold across API restarts
and across several API processes.

Settings: one variable per limit, written "N/SECONDS" ("0" switches that limit
off). Defaults:

    AUTH_LIMIT_LOGIN_IP=30/900            sign-in attempts per address
    AUTH_LIMIT_LOGIN_ACCOUNT=10/900       FAILED sign-in attempts per account
    AUTH_LIMIT_REGISTER_IP=10/3600        registrations per address
    AUTH_LIMIT_FORGOT_IP=10/3600          password-reset requests per address
    AUTH_LIMIT_FORGOT_ACCOUNT=3/3600      password-reset emails per account
    AUTH_LIMIT_VERIFY_IP=10/3600          verification-email requests per address
    AUTH_LIMIT_VERIFY_ACCOUNT=3/3600      verification emails per account
    AUTH_RATE_LIMITS_ENABLED=true         master switch

Keys are stored as keyed hashes, so the table holds neither addresses nor
email addresses in readable form.

Client addresses come from the connection, corrected by the web server for the
reverse proxy in front of it (FORWARDED_ALLOW_IPS, see docs/DEPLOYMENT.md). If
that is not configured, every visitor appears to come from the proxy's address
and shares one per-address allowance.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.security.keys import derive_key

CODE_RATE_LIMITED = "RATE_LIMITED"

DEFAULTS: dict[str, tuple[int, int]] = {
    "LOGIN_IP": (30, 900),
    "LOGIN_ACCOUNT": (10, 900),
    "REGISTER_IP": (10, 3600),
    "FORGOT_IP": (10, 3600),
    "FORGOT_ACCOUNT": (3, 3600),
    "VERIFY_IP": (10, 3600),
    "VERIFY_ACCOUNT": (3, 3600),
}


@dataclass(frozen=True)
class Limit:
    name: str
    count: int        # 0 = no limit
    seconds: int

    @property
    def active(self) -> bool:
        return self.count > 0 and self.seconds > 0


class RateLimited(Exception):
    """The caller has used up a limit; ``retry_after_seconds`` until it resets."""

    def __init__(self, limit: Limit, retry_after_seconds: int):
        super().__init__(f"{limit.name} exceeded")
        self.limit = limit
        self.retry_after_seconds = max(1, retry_after_seconds)


def limits_enabled() -> bool:
    return (os.getenv("AUTH_RATE_LIMITS_ENABLED") or "true").strip().lower() not in ("0", "false", "no", "off")


def limit(name: str) -> Limit:
    """The configured limit; an unreadable value falls back to the default
    rather than removing the limit."""
    default_count, default_seconds = DEFAULTS[name]
    raw = (os.getenv(f"AUTH_LIMIT_{name}") or "").strip()
    if not raw:
        return Limit(name, default_count, default_seconds)
    if raw == "0":
        return Limit(name, 0, default_seconds)
    count, _, seconds = raw.partition("/")
    try:
        parsed = Limit(name, int(count), int(seconds))
    except ValueError:
        return Limit(name, default_count, default_seconds)
    if parsed.count < 0 or parsed.seconds <= 0:
        return Limit(name, default_count, default_seconds)
    return parsed


def _bucket(name: str, key: str) -> str:
    digest = hmac.new(derive_key("rate-limit"), f"{name}:{key.strip().lower()}".encode("utf-8"), hashlib.sha256)
    return f"{name}:{digest.hexdigest()[:40]}"


def _window(seconds: int, now: Optional[float] = None) -> tuple[int, int]:
    """(start of the current window, seconds until it ends)."""
    now = time.time() if now is None else now
    start = int(now // seconds) * seconds
    return start, max(1, math.ceil(start + seconds - now))


async def _cleanup(db: AsyncSession) -> None:
    await db.execute(text("DELETE FROM rate_limits WHERE expires_at < now()"))


async def hit(db: AsyncSession, name: str, key: Optional[str], *, now: Optional[float] = None) -> None:
    """Count one event against a limit and raise RateLimited once it is over.

    The event is counted even when it is refused, so hammering a limit does not
    reset it. Commits its own small transaction.
    """
    configured = limit(name)
    if not limits_enabled() or not configured.active or not key:
        return
    start, remaining = _window(configured.seconds, now)
    result = await db.execute(
        text(
            "INSERT INTO rate_limits (bucket, window_start, count, expires_at) "
            "VALUES (:bucket, :start, 1, to_timestamp(:expires)) "
            "ON CONFLICT (bucket, window_start) DO UPDATE SET count = rate_limits.count + 1 "
            "RETURNING count"
        ),
        {"bucket": _bucket(name, key), "start": start, "expires": start + configured.seconds + 60},
    )
    count = int(result.scalar_one())
    if secrets.randbelow(200) == 0:
        await _cleanup(db)
    await db.commit()
    if count > configured.count:
        raise RateLimited(configured, remaining)


async def check(db: AsyncSession, name: str, key: Optional[str], *, now: Optional[float] = None) -> None:
    """Raise RateLimited when the limit is already used up, without counting
    an event. Used with :func:`hit` for limits that count failures only."""
    configured = limit(name)
    if not limits_enabled() or not configured.active or not key:
        return
    start, remaining = _window(configured.seconds, now)
    result = await db.execute(
        text("SELECT count FROM rate_limits WHERE bucket = :bucket AND window_start = :start"),
        {"bucket": _bucket(name, key), "start": start},
    )
    count = result.scalar_one_or_none()
    if count is not None and int(count) >= configured.count:
        raise RateLimited(configured, remaining)


async def record(db: AsyncSession, name: str, key: Optional[str], *, now: Optional[float] = None) -> None:
    """Count one event without judging it (e.g. a failed sign-in)."""
    try:
        await hit(db, name, key, now=now)
    except RateLimited:
        pass
