"""Hermetic test configuration: never read credentials or services from .env."""
import os
from pathlib import Path
import tempfile

_runtime = tempfile.TemporaryDirectory(prefix="phylo-tests-")
os.environ.update({
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://phylo_test:phylo_test@127.0.0.1:55432/phylo_test"),
    "TEST_DB_NAME": "phylo_test",
    "STORAGE_BACKEND": "local",
    "STORAGE_LOCAL_PATH": _runtime.name,
    "HOST_RUNTIME_SHARED_ROOT": _runtime.name,
    "METHOD_SERVICE_FILE_PREFIX": _runtime.name,
    "CONTRACTS_DIR": str(Path(__file__).parent / "packages/contracts"),
    "JWT_SECRET_KEY": "test-only-key-not-for-deployment",
    # Email stays switched off unless a test configures SMTP itself.
    "SMTP_HOST": "",
    # Abuse controls are exercised by their own tests; everywhere else they
    # would only get in the way (every test signs up from the same address).
    "CAPTCHA_ENABLED": "false",
    "AUTH_RATE_LIMITS_ENABLED": "false",
    "EMAIL_VERIFICATION": "off",
    "GOOGLE_CLIENT_ID": "",
    "GOOGLE_CLIENT_SECRET": "",
    "ENV": "test",
    **{f"METHOD_{m.upper()}_URL": f"http://127.0.0.1:{p}" for m, p in
       [("dowser", 58001), ("gctree", 58002), ("brepphylo", 58003), ("clonaltree", 58004)]},
})


def pytest_collection_modifyitems(items):
    import pytest
    # Older database tests predate explicit markers. Mark by fixture dependency
    # so `-m 'not integration'` genuinely runs without external services.
    for item in items:
        if "_setup_test_db" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.integration)
