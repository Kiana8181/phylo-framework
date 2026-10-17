"""Fixtures of the system tests. The stack itself is started and removed by
scripts/test-system.mjs (``npm run test:system``); these tests only use it,
change it for the length of one test, and put it back."""
from __future__ import annotations

import httpx
import pytest

from tests.system.helpers import API, METHOD_PORTS, Stack, User


@pytest.fixture(scope="session")
def _stack(tmp_path_factory) -> Stack:
    try:
        httpx.get(f"{API}/health", timeout=5, trust_env=False).raise_for_status()
    except httpx.HTTPError as exc:
        pytest.exit(f"the system-test stack is not running ({type(exc).__name__}); start it with: npm run test:system", returncode=2)
    return Stack(tmp_path_factory.mktemp("stack"))


@pytest.fixture
async def stack(_stack) -> Stack:
    """The stack; whatever the test reconfigures is restored afterwards, and
    every service answers again before the next test starts."""
    yield _stack
    changed = sorted(_stack.changed)
    _stack.restore()
    for service in ("postgres", "minio", "mail", "api", "worker", *METHOD_PORTS):
        if _stack.state(service)["status"] != "running":
            _stack.start(service)
    await _stack.ready("api", "worker", *METHOD_PORTS)
    if changed:
        await _stack.ready(*changed)


@pytest.fixture
async def users():
    """``await users(n)`` -> n fresh accounts, each with the sample dataset."""
    created: list[User] = []

    async def make(count: int = 1):
        new = [await User.create() for _ in range(count)]
        created.extend(new)
        return new if count != 1 else new[0]

    yield make
    for user in created:
        await user.close()
