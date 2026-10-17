"""Protection of the sign-in, sign-up and password-reset routes.

Real routes, real PostgreSQL, a real (local) SMTP server. Each control is
switched on by the test that needs it; the rest of the suite runs with them
off (conftest.py), as every test signs up from the same address.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from apps.api.auth import routers
from apps.api.auth import verification
from apps.api.auth.jwt_handler import create_access_token, create_refresh_token, issued_before
from apps.api.repositories.user_repository import UserRepository
from apps.api.security import captcha, rate_limit
from apps.api.security.tokens import hash_token, new_oauth_state, new_token, oauth_state_is_valid
from tests.support.smtp_sink import SmtpSink

PASSWORD = "a-good-password-1"


# --------------------------------------------------------------------------- #
# Proof of work (no database)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("digest,bits", [(b"\xff", 0), (b"\x7f", 1), (b"\x01", 7), (b"\x00\x80", 8), (b"\x00\x00\x10", 19), (b"\x00" * 4, 32)])
def test_leading_zero_bits(digest, bits):
    assert captcha.leading_zero_bits(digest) == bits


def test_a_solution_is_a_counter_whose_hash_starts_with_enough_zero_bits(monkeypatch):
    monkeypatch.setenv("CAPTCHA_DIFFICULTY_BITS", "10")
    challenge = captcha.ProofOfWorkCaptcha().issue()
    assert challenge.difficulty == 10
    counter = captcha.solve(challenge.challenge, challenge.difficulty)
    digest = hashlib.sha256(f"{challenge.challenge}:{counter}".encode()).digest()
    assert captcha.leading_zero_bits(digest) >= 10                    # the definition a client implements
    assert all(captcha.leading_zero_bits(captcha.solution_hash(challenge.challenge, c)) < 10 for c in range(counter))


def test_challenge_settings_have_safe_defaults_and_bounds(monkeypatch):
    for name in ("CAPTCHA_ENABLED", "CAPTCHA_DIFFICULTY_BITS", "CAPTCHA_TTL_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    assert captcha.captcha_enabled() is True and captcha.difficulty_bits() == 18 and captcha.ttl_seconds() == 300
    for junk in ("many", "0", "-4", "99"):                            # unusable values keep the default
        monkeypatch.setenv("CAPTCHA_DIFFICULTY_BITS", junk)
        assert captcha.difficulty_bits() == 18
    monkeypatch.setenv("CAPTCHA_ENABLED", "false")
    assert captcha.challenge_response() == {"enabled": False}
    monkeypatch.setenv("CAPTCHA_ENABLED", "true")
    body = captcha.challenge_response()
    assert body["enabled"] is True and body["algorithm"] == "sha256-leading-zero-bits" and body["difficulty"] == 18
    remaining = (datetime.fromisoformat(body["expires_at"]) - datetime.now(timezone.utc)).total_seconds()
    assert 290 <= remaining <= 300


def test_oauth_state_is_signed_and_expires(monkeypatch):
    state = new_oauth_state()
    assert oauth_state_is_valid(state)
    payload, signature = state.split(".")
    assert not oauth_state_is_valid(payload + "." + "0" * len(signature))      # forged signature
    assert not oauth_state_is_valid(payload[:-2] + "AA." + signature)          # altered content
    for junk in (None, "", "abc", "a.b", "." + signature):
        assert not oauth_state_is_valid(junk)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 601)                      # ten minutes later
    assert not oauth_state_is_valid(state)
    # A CAPTCHA challenge cannot be passed off as an OAuth state (keys are bound to their purpose).
    assert not oauth_state_is_valid(captcha.ProofOfWorkCaptcha().issue().challenge)


def test_emailed_tokens_are_stored_only_as_hashes():
    token, stored = new_token()
    assert stored == hash_token(token) == hashlib.sha256(token.encode()).hexdigest()
    assert token not in stored and len(token) >= 40 and new_token()[0] != token


def test_a_session_older_than_the_cut_off_is_recognised():
    now = datetime.now(timezone.utc)
    assert issued_before({"iat": int(now.timestamp()) - 10}, now) is True
    assert issued_before({"iat": int(now.timestamp())}, now) is False          # same second: not older
    assert issued_before({"iat": int(now.timestamp()) + 5}, now) is False
    assert issued_before({}, now) is True                                      # no issue time: treated as old
    assert issued_before({}, None) is False                                    # no cut-off: everything is valid


@pytest.mark.parametrize("raw,expected", [
    ("", (30, 900)), ("5/60", (5, 60)), ("0", (0, 900)), ("junk", (30, 900)), ("5", (30, 900)),
    ("-1/60", (30, 900)), ("5/0", (30, 900)), ("5/x", (30, 900)),
])
def test_limit_settings_parse_and_never_vanish_on_a_typo(monkeypatch, raw, expected):
    monkeypatch.setenv("AUTH_LIMIT_LOGIN_IP", raw)
    configured = rate_limit.limit("LOGIN_IP")
    assert (configured.count, configured.seconds) == expected
    assert configured.active is (expected[0] > 0)


def test_verification_mode(monkeypatch):
    monkeypatch.delenv("EMAIL_VERIFICATION", raising=False)
    monkeypatch.setenv("SMTP_HOST", "")
    assert verification.verification_required() is False                       # auto, no mail server
    monkeypatch.setenv("SMTP_HOST", "mail.example")
    assert verification.verification_required() is True                        # auto, mail server present
    monkeypatch.setenv("EMAIL_VERIFICATION", "off")
    assert verification.verification_required() is False
    monkeypatch.setenv("EMAIL_VERIFICATION", "required")
    monkeypatch.setenv("SMTP_HOST", "")
    assert verification.verification_required() is True
    monkeypatch.setenv("EMAIL_VERIFICATION", "sometimes")                     # unknown value behaves as auto
    assert verification.verification_required() is False


# --------------------------------------------------------------------------- #
# Routes (real PostgreSQL)
# --------------------------------------------------------------------------- #
db_test = pytest.mark.integration


@pytest.fixture
def captcha_on(monkeypatch):
    monkeypatch.setenv("CAPTCHA_ENABLED", "true")
    monkeypatch.setenv("CAPTCHA_DIFFICULTY_BITS", "8")                # quick to solve in a test


@pytest.fixture
def limits_on(monkeypatch):
    monkeypatch.setenv("AUTH_RATE_LIMITS_ENABLED", "true")
    for name in rate_limit.DEFAULTS:
        monkeypatch.delenv(f"AUTH_LIMIT_{name}", raising=False)
    # Windows are aligned to the clock, so a test running across a boundary
    # (19:59:59 -> 20:00:00) got a fresh window mid-test and one event too many.
    # Start the limiter's clock at the next 00:00 UTC, the start of a window for
    # every size used here; it still follows time.time, so tests that move the
    # clock on still reach later windows. Forward, so cleanup keeps live rows.
    offset = 86400 - time.time() % 86400
    window = rate_limit._window
    monkeypatch.setattr(rate_limit, "_window",
                        lambda seconds, now=None: window(seconds, time.time() + offset if now is None else now))


@pytest.fixture
async def mail(monkeypatch):
    """A mail server; with it configured, email verification is required (auto)."""
    async with SmtpSink() as sink:
        for name, value in {"SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(sink.port), "SMTP_SECURITY": "none",
                            "SMTP_FROM": "Phylo Runner <phylo@lab.example>", "SMTP_TIMEOUT_SECONDS": "3",
                            "EMAIL_VERIFICATION": "auto"}.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr(routers, "FRONTEND_URL", "https://phylo.lab.example")
        yield sink


@pytest.fixture
async def parallel_client(client, session):
    """A client whose requests each get their own database session, as in
    production, so that simultaneous requests are simultaneous transactions."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from apps.api.database import get_db
    from apps.api.main import app

    maker = async_sessionmaker(session.bind, expire_on_commit=False)

    async def own_session():
        async with maker() as request_session:
            yield request_session

    app.dependency_overrides[get_db] = own_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as parallel:
        yield parallel


async def solved(client) -> dict:
    challenge = (await client.get("/auth/challenge")).json()
    return {"challenge": challenge["challenge"], "counter": captcha.solve(challenge["challenge"], challenge["difficulty"])}


def link_token(message: dict) -> str:
    return message["text"].split("token=")[1].split()[0]


async def register(client, email="ada@uni.example", username="ada", password=PASSWORD, **extra):
    return await client.post("/auth/register", json={"email": email, "username": username, "password": password, **extra})


async def login(client, email="ada@uni.example", password=PASSWORD, **extra):
    return await client.post("/auth/login", json={"email": email, "password": password, **extra})


def auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# ---- CAPTCHA ---------------------------------------------------------------- #
@db_test
@pytest.mark.parametrize("path,body", [
    ("/auth/register", {"email": "ada@uni.example", "username": "ada", "password": PASSWORD}),
    ("/auth/login", {"email": "ada@uni.example", "password": PASSWORD}),
    ("/auth/forgot-password", {"email": "ada@uni.example"}),
])
async def test_protected_forms_are_refused_without_a_solution(client, session, captcha_on, path, body):
    missing = await client.post(path, json=body)
    assert missing.status_code == 400 and missing.json()["data"]["code"] == "CAPTCHA_REQUIRED"
    challenge = (await client.get("/auth/challenge")).json()
    wrong = captcha.solve(challenge["challenge"], challenge["difficulty"]) + 1
    while captcha.leading_zero_bits(captcha.solution_hash(challenge["challenge"], wrong)) >= challenge["difficulty"]:
        wrong += 1
    refused = await client.post(path, json={**body, "captcha": {"challenge": challenge["challenge"], "counter": wrong}})
    assert refused.status_code == 400 and refused.json()["data"]["code"] == "CAPTCHA_INVALID"
    assert await UserRepository(session).get_by_email("ada@uni.example") is None      # nothing happened


@db_test
async def test_a_solved_challenge_lets_the_request_through_once(client, captcha_on):
    solution = await solved(client)
    first = await register(client, captcha=solution)
    assert first.status_code == 201, first.text
    # The same solution again (a replay): refused, for any protected form.
    replay = await login(client, captcha=solution)
    assert replay.status_code == 400 and replay.json()["data"]["code"] == "CAPTCHA_INVALID"
    assert (await login(client, captcha=await solved(client))).status_code == 200


@db_test
async def test_two_simultaneous_uses_of_one_solution_admit_one(account, parallel_client, captcha_on):
    solution = await solved(parallel_client)
    responses = await asyncio.gather(*(
        parallel_client.post("/auth/forgot-password", json={"email": "owner@example.org", "captcha": solution})
        for _ in range(6)))
    assert sorted(r.status_code for r in responses) == [200] + [400] * 5


@db_test
async def test_challenges_cannot_be_forged_altered_or_used_late(client, captcha_on, monkeypatch):
    challenge = (await client.get("/auth/challenge")).json()
    payload, signature = challenge["challenge"].split(".")
    counter = captcha.solve(challenge["challenge"], challenge["difficulty"])

    async def attempt(value, count=0):
        response = await login(client, captcha={"challenge": value, "counter": count})
        return response.json().get("data", {}).get("code")

    # A challenge the client made up, with a valid proof of work for it.
    homemade = "bm90LXNpZ25lZA." + "0" * 64
    assert await attempt(homemade, captcha.solve(homemade, 8)) == "CAPTCHA_INVALID"
    # An easier difficulty written into a real challenge: the signature no longer matches.
    assert await attempt(payload[:-3] + "AAA." + signature) == "CAPTCHA_INVALID"
    for junk in ("", "x", "a.b.c"):
        assert await attempt(junk) in ("CAPTCHA_INVALID", "CAPTCHA_REQUIRED")
    for bad_counter in (-1, 2**60):
        assert await attempt(challenge["challenge"], bad_counter) == "CAPTCHA_INVALID"
    # Correct, but after it expired.
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 301)
    assert await attempt(challenge["challenge"], counter) == "CAPTCHA_INVALID"


@db_test
async def test_raising_the_difficulty_does_not_break_challenges_already_issued(client, captcha_on, monkeypatch):
    easy = await solved(client)                                       # issued at 8 bits
    monkeypatch.setenv("CAPTCHA_DIFFICULTY_BITS", "12")
    assert (await register(client, captcha=easy)).status_code == 201  # judged by the difficulty signed into it
    assert (await client.get("/auth/challenge")).json()["difficulty"] == 12


@db_test
async def test_with_captcha_off_nothing_is_asked(client):
    assert (await client.get("/auth/challenge")).json() == {"enabled": False}
    assert (await register(client)).status_code == 201


# ---- rate limits -------------------------------------------------------------- #
@db_test
async def test_failed_sign_ins_lock_the_account_for_the_window_even_for_the_right_password(client, account, limits_on, monkeypatch):
    monkeypatch.setenv("AUTH_LIMIT_LOGIN_ACCOUNT", "3/900")
    for _ in range(3):
        assert (await login(client, "owner@example.org", "wrong")).status_code == 401
    locked = await login(client, "owner@example.org", "test-password-123")     # the correct password
    assert locked.status_code == 429
    body = locked.json()
    assert body["data"]["code"] == "RATE_LIMITED" and 1 <= body["data"]["retry_after_seconds"] <= 900
    assert locked.headers["Retry-After"] == str(body["data"]["retry_after_seconds"])
    # Another account is not affected, and neither is password reset for this one.
    assert (await login(client, "nobody@example.org", "x")).status_code == 401
    assert (await client.post("/auth/forgot-password", json={"email": "owner@example.org"})).status_code == 200


@db_test
async def test_successful_sign_ins_do_not_use_up_the_account_limit(client, account, limits_on, monkeypatch):
    monkeypatch.setenv("AUTH_LIMIT_LOGIN_ACCOUNT", "2/900")
    for _ in range(6):
        assert (await login(client, "owner@example.org", "test-password-123")).status_code == 200


@db_test
async def test_the_account_limit_applies_to_addresses_without_an_account_too(client, limits_on, monkeypatch):
    """Otherwise 401-then-429 would reveal which addresses have accounts."""
    monkeypatch.setenv("AUTH_LIMIT_LOGIN_ACCOUNT", "2/900")
    codes = [(await login(client, "ghost@example.org", "x")).status_code for _ in range(4)]
    assert codes == [401, 401, 429, 429]
    assert (await login(client, "GHOST@Example.org", "x")).status_code == 429   # letter case is not a way around


@db_test
async def test_sign_in_attempts_are_limited_per_address(client, account, limits_on, monkeypatch):
    monkeypatch.setenv("AUTH_LIMIT_LOGIN_IP", "4/900")
    monkeypatch.setenv("AUTH_LIMIT_LOGIN_ACCOUNT", "0")
    codes = [(await login(client, f"user{i}@example.org", "x")).status_code for i in range(6)]
    assert codes == [401, 401, 401, 401, 429, 429]
    assert (await login(client, "owner@example.org", "test-password-123")).status_code == 429


@db_test
async def test_registrations_and_reset_requests_are_limited(client, limits_on, monkeypatch):
    monkeypatch.setenv("AUTH_LIMIT_REGISTER_IP", "2/3600")
    codes = [(await register(client, f"u{i}@example.org", f"user{i}")).status_code for i in range(4)]
    assert codes == [201, 201, 429, 429]

    monkeypatch.setenv("AUTH_LIMIT_FORGOT_ACCOUNT", "2/3600")
    sent = AsyncMock()
    monkeypatch.setattr(routers, "send_email", sent)
    codes = [(await client.post("/auth/forgot-password", json={"email": "u0@example.org"})).status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429] and sent.await_count == 2      # at most two emails to that mailbox
    # The same limit, the same answers, for an address that has no account.
    codes = [(await client.post("/auth/forgot-password", json={"email": "ghost@example.org"})).status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429]
    monkeypatch.setenv("AUTH_LIMIT_FORGOT_IP", "1/3600")
    assert (await client.post("/auth/forgot-password", json={"email": "other@example.org"})).status_code == 429


@db_test
async def test_a_limit_resets_with_its_window_and_refused_attempts_still_count(session, limits_on, monkeypatch):
    monkeypatch.setenv("AUTH_LIMIT_LOGIN_IP", "2/100")
    now = 1_000_000.0
    await rate_limit.hit(session, "LOGIN_IP", "10.0.0.1", now=now)
    await rate_limit.hit(session, "LOGIN_IP", "10.0.0.1", now=now + 1)
    with pytest.raises(rate_limit.RateLimited) as refused:
        await rate_limit.hit(session, "LOGIN_IP", "10.0.0.1", now=now + 40)
    assert refused.value.retry_after_seconds == 60                    # until the window ends
    await rate_limit.hit(session, "LOGIN_IP", "10.0.0.2", now=now + 40)        # another address is separate
    await rate_limit.hit(session, "LOGIN_IP", "10.0.0.1", now=now + 100)       # next window
    counts = (await session.execute(text("SELECT count FROM rate_limits ORDER BY window_start, count"))).scalars().all()
    assert sorted(counts) == [1, 1, 3]
    # Nothing readable is stored about who was counted.
    buckets = (await session.execute(text("SELECT bucket FROM rate_limits"))).scalars().all()
    assert all("10.0.0" not in b for b in buckets)


@db_test
async def test_simultaneous_attempts_cannot_slip_past_a_limit(account, parallel_client, limits_on, monkeypatch):
    monkeypatch.setenv("AUTH_LIMIT_LOGIN_IP", "5/900")
    monkeypatch.setenv("AUTH_LIMIT_LOGIN_ACCOUNT", "0")
    responses = await asyncio.gather(*(login(parallel_client, "owner@example.org", "wrong") for _ in range(20)))
    assert sorted(r.status_code for r in responses) == [401] * 5 + [429] * 15


@db_test
async def test_with_limits_off_nothing_is_counted(client, account, session):
    for _ in range(40):
        assert (await login(client, "owner@example.org", "wrong")).status_code == 401
    assert (await session.execute(text("SELECT count(*) FROM rate_limits"))).scalar_one() == 0


# ---- client address ------------------------------------------------------------ #
@db_test
async def test_the_client_address_is_taken_from_a_trusted_proxy_only(session):
    """The setting that makes per-address limits mean something behind a proxy."""
    from httpx import ASGITransport, AsyncClient
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    from apps.api.main import app

    async def seen(trusted, peer, forwarded):
        wrapped = ProxyHeadersMiddleware(app, trusted_hosts=trusted)
        async with AsyncClient(transport=ASGITransport(app=wrapped, client=(peer, 40000)), base_url="http://test") as c:
            headers = {"X-Forwarded-For": forwarded} if forwarded else {}
            return (await c.get("/auth/client-ip", headers=headers)).json()["client_ip"]

    # The proxy is trusted: its report of the visitor's address is used.
    assert await seen("172.18.0.0/16", "172.18.0.5", "203.0.113.9") == "203.0.113.9"
    # A visitor cannot pass off another address: the proxy appends the real one last.
    assert await seen("172.18.0.0/16", "172.18.0.5", "10.9.9.9, 203.0.113.9") == "203.0.113.9"
    # The peer is not the proxy: whatever header it sends is ignored.
    assert await seen("172.18.0.0/16", "198.51.100.7", "203.0.113.9") == "198.51.100.7"
    # Nothing trusted (the default): the peer's address, header or not.
    assert await seen("127.0.0.1", "172.18.0.5", "203.0.113.9") == "172.18.0.5"


# ---- email verification ---------------------------------------------------------- #
@db_test
async def test_sign_up_sends_a_link_and_the_account_works_once_it_is_opened(client, session, mail):
    response = await register(client)
    assert response.status_code == 202
    assert response.json() == {"verification_required": True, "message": routers.REGISTRATION_ACCEPTED}
    assert "access_token" not in response.text                        # not signed in by registering
    (message,) = mail.messages
    assert message["recipients"] == ["ada@uni.example"] and message["subject"] == "Confirm your Phylo Runner email address"
    token = link_token(message)
    assert f"https://phylo.lab.example/auth/verify-email?token={token}" in message["text"]
    user = await UserRepository(session).get_by_email("ada@uni.example")
    assert user.email_verified_at is None and user.email_verification_token == hash_token(token)

    # Before confirming: can sign in and see what to do, but not upload or run.
    tokens = (await login(client)).json()
    assert tokens["user"]["email_verified"] is False and tokens["user"]["verification_required"] is True
    me = (await client.get("/auth/me", headers=auth(tokens))).json()
    assert me["email_verified"] is False
    for method, path, body in (("post", "/uploads/init", {"original_filename": "a.fa"}),
                               ("post", "/runs?method=gctree", {"params": {}})):
        refused = await getattr(client, method)(path, json=body, headers=auth(tokens))
        assert refused.status_code == 403 and refused.json()["data"]["code"] == "EMAIL_NOT_VERIFIED", refused.text
    assert (await client.get("/runs", headers=auth(tokens))).status_code == 200     # reading is allowed

    # Opening the link confirms the address and signs in.
    verified = await client.post("/auth/verify-email", json={"token": token})
    assert verified.status_code == 200 and verified.json()["user"]["email_verified"] is True
    assert (await client.post("/uploads/init", json={"original_filename": "a.fa"}, headers=auth(verified.json()))).status_code == 200
    # The link works once.
    again = await client.post("/auth/verify-email", json={"token": token})
    assert again.status_code == 400 and again.json()["data"]["code"] == "VERIFICATION_LINK_INVALID"


@db_test
async def test_registering_an_existing_address_looks_the_same_and_tells_only_the_mailbox(client, session, mail):
    first = await register(client)
    await client.post("/auth/verify-email", json={"token": link_token(mail.messages[0])})
    before = (await UserRepository(session).get_by_email("ada@uni.example")).password_hash

    second = await register(client, username="someone-else", password="another-password-9")
    fresh = await register(client, email="new@uni.example", username="newperson")
    assert second.status_code == fresh.status_code == first.status_code == 202
    assert second.json() == fresh.json() == first.json()              # indistinguishable to the caller
    notice = mail.messages[1]
    assert notice["recipients"] == ["ada@uni.example"] and notice["subject"] == "You already have a Phylo Runner account"
    assert "it already has one" in notice["text"] and "token=" not in notice["text"]
    user = await UserRepository(session).get_by_email("ada@uni.example")
    assert user.password_hash == before and user.username == "ada"    # the existing account is untouched
    assert (await login(client, password="another-password-9")).status_code == 401
    # Letter case does not make it a different address.
    await register(client, email="ADA@Uni.Example", username="third")
    count = (await session.execute(text("SELECT count(*) FROM users WHERE lower(email) = 'ada@uni.example'"))).scalar_one()
    assert count == 1


@db_test
async def test_registering_again_before_confirming_sends_a_fresh_link_and_keeps_the_first_password(client, session, mail):
    await register(client)
    await register(client, username="ada-again", password="a-different-password-2")
    assert [m["subject"] for m in mail.messages] == ["Confirm your Phylo Runner email address"] * 2
    first, second = (link_token(m) for m in mail.messages)
    assert first != second
    assert (await client.post("/auth/verify-email", json={"token": first})).status_code == 400    # replaced
    assert (await client.post("/auth/verify-email", json={"token": second})).status_code == 200
    assert (await login(client)).status_code == 200                   # the password of the first registration
    assert (await login(client, password="a-different-password-2")).status_code == 401


@db_test
async def test_a_taken_username_is_reported_without_revealing_anything_about_the_address(client, mail):
    await register(client)
    taken_new_address = await register(client, email="other@uni.example", username="ada")
    taken_same_address = await register(client, email="ada@uni.example", username="ada")
    assert taken_new_address.status_code == taken_same_address.status_code == 400
    assert taken_new_address.json() == taken_same_address.json()
    assert len(mail.messages) == 1


@db_test
async def test_a_confirmation_link_expires(client, session, mail):
    await register(client)
    await session.execute(text("UPDATE users SET email_verification_expires = now() - interval '1 minute'"))
    await session.commit()
    expired = await client.post("/auth/verify-email", json={"token": link_token(mail.messages[0])})
    assert expired.status_code == 400
    for junk in ("", "not-a-token"):
        assert (await client.post("/auth/verify-email", json={"token": junk})).status_code == 400


@db_test
async def test_a_new_link_can_be_requested_a_limited_number_of_times(client, mail, limits_on, monkeypatch):
    monkeypatch.setenv("AUTH_LIMIT_VERIFY_ACCOUNT", "3/3600")         # the sign-up email counts as the first
    await register(client)
    tokens = (await login(client)).json()
    codes = [(await client.post("/auth/resend-verification", headers=auth(tokens))).status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429] and len(mail.messages) == 3
    assert (await client.post("/auth/resend-verification")).status_code == 401          # signed-in users only
    newest = link_token(mail.messages[-1])
    assert (await client.post("/auth/verify-email", json={"token": link_token(mail.messages[0])})).status_code == 400
    session_ = (await client.post("/auth/verify-email", json={"token": newest})).json()
    done = await client.post("/auth/resend-verification", headers=auth(session_))
    assert done.status_code == 200 and done.json()["email_verified"] is True and len(mail.messages) == 3


@db_test
async def test_repeated_sign_ups_cannot_be_used_to_flood_a_mailbox(client, mail, limits_on, monkeypatch):
    monkeypatch.setenv("AUTH_LIMIT_VERIFY_ACCOUNT", "2/3600")
    monkeypatch.setenv("AUTH_LIMIT_REGISTER_IP", "0")
    answers = [await register(client, username=f"name{i}") for i in range(6)]
    assert {r.status_code for r in answers} == {202} and len({r.text for r in answers}) == 1   # still uniform
    assert len(mail.messages) == 2


@db_test
async def test_a_mail_outage_does_not_change_the_sign_up_answer(client, session, mail):
    mail.mode = "refuse"
    response = await register(client)
    assert response.status_code == 202 and response.json()["message"] == routers.REGISTRATION_ACCEPTED
    assert (await UserRepository(session).get_by_email("ada@uni.example")) is not None
    mail.mode = "ok"
    tokens = (await login(client)).json()
    assert (await client.post("/auth/resend-verification", headers=auth(tokens))).status_code == 200
    assert (await client.post("/auth/verify-email", json={"token": link_token(mail.messages[0])})).status_code == 200


@db_test
async def test_without_a_mail_server_sign_up_works_as_before(client, session, monkeypatch):
    monkeypatch.setenv("EMAIL_VERIFICATION", "auto")
    monkeypatch.setenv("SMTP_HOST", "")
    created = await register(client)
    assert created.status_code == 201 and created.json()["user"]["verification_required"] is False
    assert (await client.post("/uploads/init", json={"original_filename": "a.fa"}, headers=auth(created.json()))).status_code == 200
    duplicate = await register(client, username="other")
    assert duplicate.status_code == 400 and duplicate.json()["message"] == "Email already registered"


@db_test
async def test_accounts_that_existed_before_verification_stay_usable(session):
    """What migration 015 does for existing rows."""
    await session.execute(text(
        "INSERT INTO users (id, email, username, password_hash, is_active, is_admin, password_reset_token, password_reset_expires) "
        "VALUES (gen_random_uuid(), 'old@uni.example', 'old', 'x', true, false, 'plain-old-token', now() + interval '1 hour')"))
    await session.commit()
    await session.execute(text("UPDATE users SET email_verified_at = now() WHERE email_verified_at IS NULL"))
    await session.execute(text("UPDATE users SET password_reset_token = NULL, password_reset_expires = NULL WHERE password_reset_token IS NOT NULL"))
    await session.commit()
    user = await UserRepository(session).get_by_email("old@uni.example")
    assert user.email_verified_at is not None and user.password_reset_token is None
    assert await UserRepository(session).get_by_reset_token("plain-old-token") is None


# ---- sessions, reset, ownership -------------------------------------------------- #
@db_test
async def test_a_password_reset_ends_every_earlier_session_and_proves_the_address(client, session, mail):
    await register(client)
    old = (await login(client)).json()                                # e.g. whoever registered this address
    assert (await client.get("/auth/me", headers=auth(old))).status_code == 200
    await asyncio.sleep(1.1)                                           # token times are whole seconds

    await client.post("/auth/forgot-password", json={"email": "ada@uni.example"})
    reset_token = link_token(mail.messages[-1])
    stored = (await UserRepository(session).get_by_email("ada@uni.example")).password_reset_token
    assert stored == hash_token(reset_token) and stored != reset_token
    assert (await client.post("/auth/reset-password", json={"token": reset_token, "new_password": "the-owners-password-3"})).status_code == 200

    assert (await client.get("/auth/me", headers=auth(old))).status_code == 401
    assert (await client.post("/auth/refresh", json={"refresh_token": old["refresh_token"]})).status_code == 401
    assert (await login(client)).status_code == 401                    # the earlier password is gone
    fresh = (await login(client, password="the-owners-password-3")).json()
    assert fresh["user"]["email_verified"] is True                     # the link reached the mailbox
    assert (await client.get("/auth/me", headers=auth(fresh))).status_code == 200
    assert (await client.post("/auth/refresh", json={"refresh_token": fresh["refresh_token"]})).status_code == 200


@db_test
async def test_google_sign_in_requires_this_apps_state_and_a_confirmed_google_address(client, session, monkeypatch):
    exchange = AsyncMock(return_value={"email": "g@uni.example", "email_verified": True})
    monkeypatch.setattr(routers, "exchange_google_code", exchange)
    for state in (None, "", "made-up", new_oauth_state()[:-4] + "0000"):
        body = {"code": "c"} if state is None else {"code": "c", "state": state}
        refused = await client.post("/auth/google", json=body)
        assert refused.status_code == 400 and refused.json()["data"]["code"] == "OAUTH_STATE_INVALID"
    exchange.assert_not_awaited()                                      # the code is not even exchanged

    exchange.return_value = {"email": "g@uni.example", "email_verified": False}
    unconfirmed = await client.post("/auth/google", json={"code": "c", "state": new_oauth_state()})
    assert unconfirmed.status_code == 401 and "not verified" in unconfirmed.json()["message"]
    assert await UserRepository(session).get_by_email("g@uni.example") is None

    exchange.return_value = {"email": "g@uni.example", "email_verified": True}
    ok = await client.post("/auth/google", json={"code": "c", "state": new_oauth_state()})
    assert ok.status_code == 200 and ok.json()["user"]["email_verified"] is True


@db_test
async def test_the_authorization_url_comes_with_a_state_to_send_back(client, monkeypatch):
    from apps.api.auth import google_oauth
    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_ID", "client-id")
    body = (await client.get("/auth/google")).json()
    assert oauth_state_is_valid(body["state"]) and f"state={body['state']}" in body["auth_url"]


@db_test
async def test_an_unproven_password_account_passes_to_the_owner_who_signs_in_with_google(client, session, mail, monkeypatch):
    """Someone registered another person's address and never confirmed it. When
    the real owner arrives through Google, the squatter's password and sessions
    must stop working."""
    await register(client, email="victim@uni.example", username="squatter", password="squatters-password-1")
    squatter = (await login(client, "victim@uni.example", "squatters-password-1")).json()
    await asyncio.sleep(1.1)
    monkeypatch.setattr(routers, "exchange_google_code", AsyncMock(return_value={"email": "victim@uni.example", "email_verified": True}))
    owner = await client.post("/auth/google", json={"code": "c", "state": new_oauth_state()})
    assert owner.status_code == 200 and owner.json()["user"]["email_verified"] is True
    assert (await login(client, "victim@uni.example", "squatters-password-1")).status_code == 401
    assert (await client.get("/auth/me", headers=auth(squatter))).status_code == 401
    assert (await client.post("/auth/refresh", json={"refresh_token": squatter["refresh_token"]})).status_code == 401
    assert (await client.get("/auth/me", headers=auth(owner.json()))).status_code == 200


@db_test
async def test_a_confirmed_password_account_keeps_its_password_when_its_owner_also_uses_google(client, session, mail, monkeypatch):
    await register(client)
    await client.post("/auth/verify-email", json={"token": link_token(mail.messages[0])})
    monkeypatch.setattr(routers, "exchange_google_code", AsyncMock(return_value={"email": "ada@uni.example", "email_verified": True}))
    assert (await client.post("/auth/google", json={"code": "c", "state": new_oauth_state()})).status_code == 200
    assert (await login(client)).status_code == 200


@db_test
async def test_sign_in_takes_as_long_for_an_unknown_address_as_for_a_wrong_password(client, account, monkeypatch):
    """No account: the password work is done anyway, so timing tells nothing."""
    calls = []
    real = routers.verify_password
    monkeypatch.setattr(routers, "verify_password", lambda password, stored: calls.append(stored) or real(password, stored))
    known = await login(client, "owner@example.org", "wrong-password")
    unknown = await login(client, "nobody@example.org", "wrong-password")
    assert known.status_code == unknown.status_code == 401 and known.json() == unknown.json()
    assert len(calls) == 2 and all(stored.startswith("$2") for stored in calls)   # one real bcrypt comparison each


# ---- notifications ---------------------------------------------------------------- #
@db_test
async def test_run_emails_go_only_to_confirmed_addresses(session, mail, monkeypatch, tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from apps.api.repositories.run_repository import RunRepository
    from apps.api.workers import notifier
    monkeypatch.setattr(notifier, "AsyncSessionLocal", async_sessionmaker(session.bind, expire_on_commit=False))
    users = UserRepository(session)
    confirmed = await users.create_user(email="yes@uni.example", username="yes", password_hash="x", email_verified=True)
    unconfirmed = await users.create_user(email="no@uni.example", username="no", password_hash="x")
    runs = RunRepository(session)
    for owner in (confirmed, unconfirmed):
        run = await runs.create_run(method_id="gctree", params={}, user_id=owner.id)
        await runs.fail_run(run.id, error="x", message="failed")
    assert await notifier.deliver_due() == {"sent": 1, "skipped": 1}
    assert [m["recipients"] for m in mail.messages] == [["yes@uni.example"]]
    reason = (await session.execute(text("SELECT last_error FROM notification_outbox WHERE status = 'SKIPPED'"))).scalar_one()
    assert "not confirmed" in reason


# ---- start-up report ------------------------------------------------------------- #
def test_start_up_reports_what_is_active_and_warns_in_production_about_what_is_not(monkeypatch, caplog):
    import logging
    from apps.api.security import startup_report

    for name, value in {"CAPTCHA_ENABLED": "true", "AUTH_RATE_LIMITS_ENABLED": "true", "EMAIL_VERIFICATION": "auto",
                        "SMTP_HOST": "mail.example", "FORWARDED_ALLOW_IPS": "172.18.0.0/16",
                        "CAPTCHA_DIFFICULTY_BITS": "18"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(startup_report, "IS_PRODUCTION", True)
    with caplog.at_level(logging.INFO, logger="phylo.api.security"):
        startup_report.log_auth_protection()
    assert [r.levelname for r in caplog.records] == ["INFO"]
    assert "captcha=on (18 bits), rate limits=on, email verification=required (auto)" in caplog.text

    caplog.clear()
    for name, value in {"CAPTCHA_ENABLED": "false", "AUTH_RATE_LIMITS_ENABLED": "false", "SMTP_HOST": "",
                        "FORWARDED_ALLOW_IPS": ""}.items():
        monkeypatch.setenv(name, value)
    with caplog.at_level(logging.INFO, logger="phylo.api.security"):
        startup_report.log_auth_protection()
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 4
    assert any("CAPTCHA_ENABLED is off" in w for w in warnings)
    assert any("AUTH_RATE_LIMITS_ENABLED is off" in w for w in warnings)
    assert any("no mail server is configured" in w for w in warnings)
    assert any("FORWARDED_ALLOW_IPS is not set" in w and "/auth/client-ip" in w for w in warnings)

    # Outside production the same settings are a choice, not a warning.
    caplog.clear()
    monkeypatch.setattr(startup_report, "IS_PRODUCTION", False)
    with caplog.at_level(logging.INFO, logger="phylo.api.security"):
        startup_report.log_auth_protection()
    assert [r.levelname for r in caplog.records] == ["INFO"]
