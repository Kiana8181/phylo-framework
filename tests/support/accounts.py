"""Creating a usable account against a running stack, the way a person does:
solve the sign-up check, sign up, open the emailed confirmation link.

For end-to-end tests and scratch scripts. Works whether or not the stack asks
for a CAPTCHA or for email verification.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Optional

import httpx

MAIL = "http://127.0.0.1:58025"
VERIFICATION_SUBJECT = "Confirm your"


def unwrap(response: httpx.Response) -> Any:
    response.raise_for_status()
    value = response.json()
    return value["data"] if isinstance(value, dict) and value.get("status") == "success" and "data" in value else value


def _zero_bits(digest: bytes) -> int:
    bits = 0
    for byte in digest:
        if byte == 0:
            bits += 8
            continue
        return bits + 8 - byte.bit_length()
    return bits


async def solve_captcha(api: httpx.AsyncClient) -> Optional[dict]:
    """Answer to a fresh challenge, or None when the stack does not ask for one."""
    challenge = unwrap(await api.get("/auth/challenge"))
    if not challenge.get("enabled"):
        return None
    counter = 0
    while _zero_bits(hashlib.sha256(f"{challenge['challenge']}:{counter}".encode()).digest()) < challenge["difficulty"]:
        counter += 1
    return {"challenge": challenge["challenge"], "counter": counter}


async def messages_for(address: str, mail_url: str = MAIL) -> list[dict]:
    async with httpx.AsyncClient(base_url=mail_url, timeout=10, trust_env=False) as mail:
        messages = (await mail.get("/messages")).json()["messages"]
    return [m for m in messages if address in m["recipients"]]


async def verification_token(address: str, timeout: float = 30, mail_url: str = MAIL) -> str:
    """The token in the newest confirmation email sent to ``address``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        confirmations = [m for m in await messages_for(address, mail_url) if m["subject"].startswith(VERIFICATION_SUBJECT)]
        if confirmations:
            return confirmations[-1]["text"].split("token=")[1].split()[0]
        await asyncio.sleep(0.2)
    raise AssertionError(f"no confirmation email arrived for {address}")


async def register_verified(api: httpx.AsyncClient, email: str, username: str, password: str) -> dict:
    """Sign up and, where required, confirm the address. Returns the session
    ({access_token, refresh_token, user}) and sets the Authorization header."""
    body = {"email": email, "username": username, "password": password}
    captcha = await solve_captcha(api)
    if captcha:
        body["captcha"] = captcha
    response = await api.post("/auth/register", json=body)
    session = unwrap(response)
    if response.status_code == 202:
        token = await verification_token(email)
        session = unwrap(await api.post("/auth/verify-email", json={"token": token}))
    api.headers["Authorization"] = f"Bearer {session['access_token']}"
    return session
