"""Production must refuse to start on missing, default or weak secrets.

Pure unit tests plus real-process checks: no database or object store needed.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from apps.api.security.production_config import (
    InsecureConfigurationError,
    collect_config_problems,
    enforce_production_config,
    is_insecure_secret,
)

ROOT = Path(__file__).resolve().parents[3]

STRONG = {
    "ENV": "production",
    "JWT_SECRET_KEY": "unit-test-jwt-9f2c7a41d8e35b60c1a7f4e29b83d650",
    "JWT_ALGORITHM": "HS256",
    "DATABASE_URL": "postgresql+asyncpg://app:unit-test-db-7c1e93af52b8@db:5432/phylo",
    "POSTGRES_PASSWORD": "unit-test-db-7c1e93af52b8",
    "STORAGE_BACKEND": "minio",
    "S3_SECRET_ACCESS_KEY": "unit-test-s3-51d8c2f7a94e63b0",
    "MINIO_ROOT_PASSWORD": "unit-test-s3-51d8c2f7a94e63b0",
    "MINIO_METHODS_PASSWORD": "unit-test-methods-a3f81c5d2e97b406",
    "CORS_ORIGINS": "https://phylo.example.org",
}


def _with(**overrides: str | None) -> dict[str, str]:
    env = dict(STRONG)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def test_strong_configuration_has_no_problems():
    assert collect_config_problems(STRONG) == []
    enforce_production_config(STRONG)  # does not raise


@pytest.mark.parametrize(
    "overrides,variable",
    [
        ({"JWT_SECRET_KEY": None}, "JWT_SECRET_KEY"),
        ({"JWT_SECRET_KEY": "   "}, "JWT_SECRET_KEY"),
        ({"JWT_SECRET_KEY": "short-but-unique-key"}, "JWT_SECRET_KEY"),
        ({"JWT_SECRET_KEY": "your-secret-key-change-in-production"}, "JWT_SECRET_KEY"),
        ({"JWT_SECRET_KEY": "change-this-secret-key-in-production-use-long-random-string"}, "JWT_SECRET_KEY"),
        ({"JWT_SECRET_KEY": "CHANGE_ME_generate_with_openssl_rand_hex_32"}, "JWT_SECRET_KEY"),
        ({"JWT_ALGORITHM": "none"}, "JWT_ALGORITHM"),
        ({"DATABASE_URL": "postgresql+asyncpg://phylo_user:phylo_pass@postgres:5432/phylo_db"}, "DATABASE_URL"),
        ({"DATABASE_URL": "postgresql+asyncpg://phylo_user@postgres:5432/phylo_db"}, "DATABASE_URL"),
        ({"DATABASE_URL": None, "POSTGRES_PASSWORD": "phylo_pass"}, "POSTGRES_PASSWORD"),
        ({"DATABASE_URL": None, "POSTGRES_PASSWORD": None}, "POSTGRES_PASSWORD"),
        ({"POSTGRES_PASSWORD": "phylo_pass"}, "POSTGRES_PASSWORD"),
        ({"S3_SECRET_ACCESS_KEY": "phylo_minio_secret"}, "S3_SECRET_ACCESS_KEY"),
        ({"S3_SECRET_ACCESS_KEY": None}, "S3_SECRET_ACCESS_KEY"),
        ({"MINIO_ROOT_PASSWORD": "phylo_minio_secret"}, "MINIO_ROOT_PASSWORD"),
        ({"MINIO_METHODS_PASSWORD": "phylo_methods_secret"}, "MINIO_METHODS_PASSWORD"),
        ({"CORS_ORIGINS": "https://phylo.example.org,*"}, "CORS_ORIGINS"),
    ],
)
def test_each_unsafe_setting_is_reported_by_variable_name(overrides, variable):
    env = _with(**overrides)
    problems = collect_config_problems(env)
    assert any(p.startswith(variable) for p in problems), problems
    with pytest.raises(InsecureConfigurationError) as raised:
        enforce_production_config(env)
    assert variable in str(raised.value)


def test_messages_never_contain_secret_values():
    env = _with(
        JWT_SECRET_KEY="short-but-unique-key",
        DATABASE_URL="postgresql+asyncpg://phylo_user:phylo_pass@postgres:5432/phylo_db",
        S3_SECRET_ACCESS_KEY="phylo_minio_secret",
        MINIO_METHODS_PASSWORD="phylo_methods_secret",
    )
    with pytest.raises(InsecureConfigurationError) as raised:
        enforce_production_config(env)
    message = str(raised.value)
    for secret in ("short-but-unique-key", "phylo_pass", "phylo_minio_secret", "phylo_methods_secret"):
        assert secret not in message


def test_all_problems_are_reported_together():
    env = _with(JWT_SECRET_KEY=None, S3_SECRET_ACCESS_KEY="phylo_minio_secret", CORS_ORIGINS="*")
    assert len(collect_config_problems(env)) == 3


@pytest.mark.parametrize("env_name", ["development", "test", "", "Production-like", "staging"])
def test_checks_only_apply_when_env_is_exactly_production(env_name):
    weak = {"ENV": env_name, "JWT_SECRET_KEY": "x", "DATABASE_URL": "postgresql://u:phylo_pass@h/d"}
    enforce_production_config(weak)  # does not raise


def test_env_value_is_case_and_whitespace_insensitive():
    with pytest.raises(InsecureConfigurationError):
        enforce_production_config({"ENV": " PRODUCTION ", "JWT_SECRET_KEY": "x"})


def test_local_storage_backend_needs_no_s3_secret():
    env = _with(STORAGE_BACKEND="local", S3_SECRET_ACCESS_KEY=None, MINIO_ROOT_PASSWORD=None)
    assert collect_config_problems(env) == []


@pytest.mark.parametrize("value,expected", [
    ("phylo_pass", True), ("PHYLO_PASS", True), ("change-me-strong", True),
    ("CHANGE_ME_please", True), ("", False), ("f3a91c0e7d5b28a4", False),
])
def test_is_insecure_secret(value, expected):
    assert is_insecure_secret(value) is expected


# --------------------------------------------------------------------------- #
# Real processes: the API module and the worker must actually exit non-zero.
# --------------------------------------------------------------------------- #
def _process_env(**overrides: str) -> dict[str, str]:
    # Every checked variable is set explicitly so the developer's .env (loaded
    # with override=False by apps.api.config) cannot influence the outcome.
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "CONTRACTS_DIR")}
    env.update(STRONG)
    env.update(overrides)
    env["PYTHONPATH"] = str(ROOT)
    return env


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )


def test_api_refuses_to_import_with_default_secrets():
    result = _run(
        ["-c", "import apps.api.main"],
        _process_env(JWT_SECRET_KEY="your-secret-key-change-in-production",
                     S3_SECRET_ACCESS_KEY="phylo_minio_secret"),
    )
    assert result.returncode != 0
    assert "Refusing to start in production" in result.stderr
    assert "JWT_SECRET_KEY" in result.stderr and "S3_SECRET_ACCESS_KEY" in result.stderr
    assert "your-secret-key-change-in-production" not in result.stderr
    assert "phylo_minio_secret" not in result.stderr


def test_api_imports_with_strong_secrets_and_hides_docs():
    result = _run(
        ["-c", "import apps.api.main as m; print(m.app.docs_url, m.app.redoc_url, m.app.openapi_url)"],
        _process_env(),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "None None None"


def test_api_docs_can_be_enabled_explicitly_in_production():
    result = _run(
        ["-c", "import apps.api.main as m; print(m.app.docs_url)"],
        _process_env(API_DOCS_ENABLED="true"),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "/docs"


def test_worker_exits_non_zero_with_default_secrets():
    result = _run(
        ["-m", "apps.api.workers.run_worker"],
        _process_env(DATABASE_URL="postgresql+asyncpg://phylo_user:phylo_pass@127.0.0.1:1/phylo_db"),
    )
    assert result.returncode == 1
    assert "Refusing to start in production" in result.stderr
    assert "DATABASE_URL" in result.stderr
    assert "phylo_pass" not in result.stderr
    assert "Traceback" not in result.stderr


def test_jwt_key_has_no_builtin_default_outside_production():
    script = (
        "import apps.api.auth.jwt_handler as j;"
        "print(len(j.JWT_SECRET_KEY) >= 32, j.JWT_SECRET_KEY != 'your-secret-key-change-in-production')"
    )
    env = _process_env(ENV="development", JWT_SECRET_KEY="")
    result = _run(["-c", script], env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True True"
    assert "JWT_SECRET_KEY is not set" in result.stderr
    # A fresh random key per process, never a shared constant.
    show_key = ["-c", "import apps.api.auth.jwt_handler as j; print(j.JWT_SECRET_KEY)"]
    assert _run(show_key, env).stdout != _run(show_key, env).stdout


# --------------------------------------------------------------------------- #
# Email settings and production start-up
# --------------------------------------------------------------------------- #
def test_a_placeholder_mail_password_is_refused_like_any_other_secret():
    assert collect_config_problems(_with(SMTP_PASSWORD="change-me-strong")) == [
        "SMTP_PASSWORD is a known default or placeholder value"]
    assert collect_config_problems(_with(SMTP_PASSWORD="unit-test-smtp-4b7e19c2a6d0f385")) == []


@pytest.mark.parametrize("smtp", [
    {},                                                               # email switched off
    {"SMTP_HOST": "mail.example"},                                    # incomplete: no sender
    {"SMTP_HOST": "mail.example", "SMTP_FROM": "a@b.example", "SMTP_SECURITY": "bogus"},
])
def test_missing_or_broken_mail_settings_never_block_start_up(smtp):
    """Email is not needed to run analyses: a mail problem is reported in the
    log and on each failed delivery, but the service still starts."""
    assert collect_config_problems(_with(**smtp)) == []
    enforce_production_config(_with(**smtp))
