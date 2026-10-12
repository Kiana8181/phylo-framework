"""Session tokens: standard HS256 JWTs, verified against an explicit allow-list."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta
from uuid import uuid4

import jwt as pyjwt

from apps.api.auth import jwt_handler as handler


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _hand_built_hs256(payload: dict, key: str) -> str:
    """A JWT assembled with the standard library only (RFC 7515/7519)."""
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(key.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(signature)}"


def test_access_and_refresh_round_trip():
    user_id = uuid4()
    access = handler.create_access_token({"sub": str(user_id)})
    refresh = handler.create_refresh_token({"sub": str(user_id)})
    assert handler.decode_token(access)["type"] == "access"
    assert handler.decode_token(refresh)["type"] == "refresh"
    assert handler.get_user_id_from_token(access) == user_id
    # Expiry is a future UTC timestamp close to the configured lifetime.
    exp = handler.decode_token(access)["exp"]
    expected = time.time() + handler.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert abs(exp - expected) < 30


def test_tokens_from_any_standard_hs256_implementation_are_accepted():
    """Sessions issued before the JWT library was replaced must stay valid: the
    wire format is plain HS256, independent of the library that produced it."""
    payload = {"sub": str(uuid4()), "type": "access", "exp": int(time.time()) + 600}
    token = _hand_built_hs256(payload, handler.JWT_SECRET_KEY)
    assert handler.decode_token(token) == payload


def test_expired_token_is_rejected():
    token = handler.create_access_token({"sub": str(uuid4())}, timedelta(seconds=-5))
    assert handler.decode_token(token) is None


def test_token_signed_with_another_key_is_rejected():
    payload = {"sub": str(uuid4()), "type": "access", "exp": int(time.time()) + 600}
    token = _hand_built_hs256(payload, "a-different-signing-key-of-sufficient-length")
    assert handler.decode_token(token) is None


def test_unsigned_alg_none_token_is_rejected():
    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = _b64(json.dumps({"sub": str(uuid4()), "type": "access", "exp": int(time.time()) + 600}).encode())
    for token in (f"{header}.{body}.", f"{header}.{body}"):
        assert handler.decode_token(token) is None


def test_other_algorithm_with_the_same_key_is_rejected():
    """Only the configured algorithm is allowed, even when the key matches."""
    assert handler.JWT_ALGORITHM == "HS256"
    token = pyjwt.encode(
        {"sub": str(uuid4()), "type": "access", "exp": int(time.time()) + 600},
        handler.JWT_SECRET_KEY,
        algorithm="HS384",
    )
    assert handler.decode_token(token) is None


def test_malformed_tokens_never_raise():
    for token in ("", "garbage", "a.b", "a.b.c", "....", "🙂"):
        assert handler.decode_token(token) is None
        assert handler.get_user_id_from_token(token) is None


def test_non_uuid_subject_yields_no_user():
    assert handler.get_user_id_from_token(handler.create_access_token({"sub": "not-a-uuid"})) is None
    assert handler.get_user_id_from_token(handler.create_access_token({})) is None
