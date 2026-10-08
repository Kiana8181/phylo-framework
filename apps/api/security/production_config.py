"""Start-up checks that stop a production deployment from running on weak secrets.

Outside production these checks do nothing, so local development and the test
suite keep working with the placeholder values from ``.env.example``.

Every message names the offending *variable*. No message ever contains a
secret's value, so the output is safe to print and to ship to a log collector.
"""
from __future__ import annotations

import os
from typing import Mapping
from urllib.parse import unquote, urlsplit

JWT_SECRET_MIN_LENGTH = 32
ALLOWED_JWT_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})

# Values that have appeared in this repository (code defaults, .env.example,
# compose fallbacks, test fixtures, documentation) or are common vendor
# defaults. Anyone can read them, so none may protect a production deployment.
KNOWN_INSECURE_VALUES = frozenset(
    {
        "phylo_pass",
        "phylo_minio_secret",
        "phylo_methods_secret",
        "phylo_test",
        "phylo_test_secret",
        "your-secret-key-change-in-production",
        "change-this-secret-key-in-production-use-long-random-string",
        "test-only-key-not-for-deployment",
        "change-me-strong",
        "minioadmin",
        "postgres",
        "password",
        "secret",
        "admin",
    }
)
_PLACEHOLDER_MARKERS = ("changeme", "change-me", "change_me", "change-this", "replace-me", "replace_me")


class InsecureConfigurationError(RuntimeError):
    """Raised at start-up when production configuration is missing or unsafe."""


def _value(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def is_insecure_secret(value: str) -> bool:
    """True for a known default or an unfilled placeholder."""
    lowered = value.strip().lower()
    if not lowered:
        return False
    return lowered in KNOWN_INSECURE_VALUES or any(m in lowered for m in _PLACEHOLDER_MARKERS)


def _database_password(env: Mapping[str, str]) -> tuple[str, str]:
    """Return (variable name, password) for the credential the API actually uses."""
    url = _value(env, "DATABASE_URL")
    if url:
        try:
            password = urlsplit(url).password
        except ValueError:
            password = None
        return "DATABASE_URL", unquote(password) if password else ""
    return "POSTGRES_PASSWORD", _value(env, "POSTGRES_PASSWORD")


def collect_config_problems(env: Mapping[str, str] | None = None) -> list[str]:
    """List every production-blocking configuration problem (empty when safe)."""
    env = os.environ if env is None else env
    problems: list[str] = []

    jwt_secret = _value(env, "JWT_SECRET_KEY")
    if not jwt_secret:
        problems.append("JWT_SECRET_KEY is not set")
    elif is_insecure_secret(jwt_secret):
        problems.append("JWT_SECRET_KEY is a known default or placeholder value")
    elif len(jwt_secret) < JWT_SECRET_MIN_LENGTH:
        problems.append(f"JWT_SECRET_KEY is shorter than {JWT_SECRET_MIN_LENGTH} characters")

    algorithm = _value(env, "JWT_ALGORITHM") or "HS256"
    if algorithm not in ALLOWED_JWT_ALGORITHMS:
        problems.append(
            "JWT_ALGORITHM must be one of " + ", ".join(sorted(ALLOWED_JWT_ALGORITHMS))
        )

    db_var, db_password = _database_password(env)
    if not db_password:
        problems.append(f"{db_var} has no database password")
    elif is_insecure_secret(db_password):
        problems.append(f"{db_var} uses a known default or placeholder database password")
    # Postgres itself is started from POSTGRES_PASSWORD; flag it too when it is
    # visible here and differs from the URL (both must be strong).
    pg_password = _value(env, "POSTGRES_PASSWORD")
    if db_var != "POSTGRES_PASSWORD" and pg_password and is_insecure_secret(pg_password):
        problems.append("POSTGRES_PASSWORD is a known default or placeholder value")

    backend = (_value(env, "STORAGE_BACKEND") or _value(env, "STORAGE_TYPE") or "local").lower()
    if backend in ("minio", "s3"):
        s3_secret = _value(env, "S3_SECRET_ACCESS_KEY")
        if not s3_secret:
            problems.append("S3_SECRET_ACCESS_KEY is not set")
        elif is_insecure_secret(s3_secret):
            problems.append("S3_SECRET_ACCESS_KEY is a known default or placeholder value")
    for name in ("MINIO_ROOT_PASSWORD", "MINIO_METHODS_PASSWORD"):
        if is_insecure_secret(_value(env, name)):
            problems.append(f"{name} is a known default or placeholder value")

    origins = [o.strip() for o in _value(env, "CORS_ORIGINS").split(",") if o.strip()]
    if "*" in origins:
        problems.append("CORS_ORIGINS must list explicit origins, not '*'")

    return problems


def is_production(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return _value(env, "ENV").lower() == "production"


def enforce_production_config(env: Mapping[str, str] | None = None) -> None:
    """Raise InsecureConfigurationError when ENV=production and config is unsafe."""
    if not is_production(env):
        return
    problems = collect_config_problems(env)
    if problems:
        raise InsecureConfigurationError(
            "Refusing to start in production with insecure configuration:\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\nSet strong, unique values in .env (see .env.example) and restart."
        )
