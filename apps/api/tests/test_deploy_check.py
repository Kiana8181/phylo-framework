"""The in-container deployment check (python -m apps.api.scripts.deploy_check).

It must tell a complete installation from an incomplete one, name what is
missing, keep going when one question cannot be answered, and never print a
secret or a connection string.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import text

from apps.api.scripts import deploy_check as check
from apps.api.scripts.deploy_check import FAIL, OK, WARN, Outcome
from apps.api.services import version_info


# --------------------------------------------------------------------------- #
# The frame: every check answers, failures are contained
# --------------------------------------------------------------------------- #
async def test_one_broken_or_hanging_check_does_not_hide_the_others():
    async def check_first():
        return Outcome("first", OK, "fine")

    async def check_that_raises():
        raise RuntimeError("postgresql://user:hunter2@db/app refused")       # a driver message with a password

    async def check_that_hangs():
        await asyncio.sleep(30)

    async def check_last():
        return Outcome("last", WARN, "optional thing is off")

    outcomes = await check.run_checks((check_first, check_that_raises, check_that_hangs, check_last), timeout=0.2)
    assert [(o.name, o.status) for o in outcomes] == [
        ("first", OK), ("that raises", FAIL), ("that hangs", FAIL), ("last", WARN)]
    assert outcomes[1].detail == "check could not run (RuntimeError)"        # the kind of error, not its text
    assert "no answer within 0.2 seconds" in outcomes[2].detail
    printed = check.render(outcomes)
    assert "hunter2" not in printed and "postgresql://" not in printed
    assert check.exit_code(outcomes) == 1


def test_warnings_do_not_fail_the_check_and_failures_do():
    fine = [Outcome("a", OK, "x"), Outcome("b", WARN, "y")]
    assert check.exit_code(fine) == 0
    assert check.exit_code([*fine, Outcome("c", FAIL, "z")]) == 1
    lines = check.render(fine).splitlines()
    assert lines == ["  OK    a  x", "  WARN  b  y"]                         # the shape scripts/deploy-check.sh reads


# --------------------------------------------------------------------------- #
# Configuration, version information, email (no services needed)
# --------------------------------------------------------------------------- #
async def test_configuration_names_variables_never_values(monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    assert (await check.check_configuration()).status == WARN               # not production: nothing is enforced
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "short-secret")
    outcome = await check.check_configuration()
    assert outcome.status == FAIL and "JWT_SECRET_KEY" in outcome.detail and "short-secret" not in outcome.detail


@pytest.fixture
def version_file(tmp_path, monkeypatch):
    path = tmp_path / "version-info.json"
    monkeypatch.setenv("PHYLO_VERSION_INFO_PATH", str(path))
    monkeypatch.setattr(version_info, "_cache", False)
    yield path
    version_info._cache = False


async def test_version_information_present_incomplete_or_missing(version_file):
    missing = await check.check_version_info()
    assert missing.status == WARN and "results will not record which version produced them" in missing.detail

    version_file.write_text(json.dumps({"generated_at": "2026-10-13T08:30:05.123Z",
                                        "framework": {"version": None, "git_commit": None}}))
    no_git = await check.check_version_info()
    assert no_git.status == WARN and "PHYLO_GIT_DIR" in no_git.detail

    version_file.write_text(json.dumps({"generated_at": "2026-10-13T08:30:05.123Z", "framework": {
        "version": "v2.1.0", "git_commit": "928f1b58f83478cb67064acb8331d371cb9788da"}}))
    complete = await check.check_version_info()
    assert complete.status == OK
    assert complete.detail == "v2.1.0 (commit 928f1b58f834, built 2026-10-13T08:30:05.123Z)"

    version_file.write_text("{ not json")
    assert (await check.check_version_info()).status == WARN                # damaged counts as missing


async def test_email_off_is_a_warning_and_a_broken_setting_is_a_failure(monkeypatch):
    for name in ("SMTP_HOST", "SMTP_FROM", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_SECURITY", "SMTP_PORT"):
        monkeypatch.delenv(name, raising=False)
    off = await check.check_email()
    assert off.status == WARN and "SMTP_HOST is empty" in off.detail
    monkeypatch.setenv("SMTP_HOST", "mail.example.org")
    broken = await check.check_email()
    assert broken.status == FAIL and "SMTP_FROM" in broken.detail
    monkeypatch.setenv("SMTP_FROM", "Phylo <phylo@example.org>")
    monkeypatch.setenv("SMTP_USERNAME", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "Zx-mail-secret-91")
    configured = await check.check_email()
    assert configured.status == OK and "Zx-mail-secret-91" not in configured.detail


# --------------------------------------------------------------------------- #
# Method services
# --------------------------------------------------------------------------- #
async def test_every_method_service_is_asked_and_the_silent_ones_are_named(monkeypatch):
    from apps.api.services import method_jobs_client as jobs

    async def capacity(method_id):
        if method_id == "dowser":
            raise ConnectionError("http://phylo-dowser:8001 refused")
        return jobs.MethodCapacity(method_id=method_id, job_slots=2 if method_id == "gctree" else 1, running_jobs=0,
                                   free_slots=1, threads_per_job=1, accepting=True)

    monkeypatch.setattr(jobs, "get_capacity", capacity)
    outcome = await check.check_methods()
    assert outcome.status == FAIL and outcome.detail == "not reachable: dowser (ConnectionError)"

    async def all_up(method_id):
        return await capacity("gctree" if method_id == "dowser" else method_id)

    monkeypatch.setattr(jobs, "get_capacity", all_up)
    outcome = await check.check_methods()
    assert outcome.status == OK
    assert outcome.detail == "brepphylo (1 job slot), clonaltree (1 job slot), dowser (2 job slots), gctree (2 job slots)"


# --------------------------------------------------------------------------- #
# Database, migrations, buckets: against the real test services
# --------------------------------------------------------------------------- #
def test_the_newest_revision_is_read_from_the_code():
    heads = check.migration_heads()
    assert len(heads) == 1 and heads[0].startswith("016_")


@pytest.mark.integration
async def test_a_reachable_migrated_database_passes(session, monkeypatch):
    from apps.api.database import base

    monkeypatch.setattr(base, "engine", session.bind)
    assert (await check.check_database()).status == OK
    migrated = await check.check_migrations()
    assert migrated.status == OK and migrated.detail == f"at {check.migration_heads()[0]}"


@pytest.mark.integration
async def test_a_database_behind_the_code_is_reported_with_both_revisions(session, monkeypatch):
    from apps.api.database import base

    monkeypatch.setattr(base, "engine", session.bind)
    current = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    await session.execute(text("UPDATE alembic_version SET version_num = '015_auth_abuse_prevention'"))
    await session.commit()
    try:
        behind = await check.check_migrations()
        assert behind.status == FAIL
        assert behind.detail == f"database is at 015_auth_abuse_prevention, this image expects {current}"
    finally:
        await session.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": current})
        await session.commit()


async def test_an_unreachable_database_is_a_failure_without_its_address(monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine

    from apps.api.database import base

    dead = create_async_engine("postgresql+asyncpg://someone:Zx-db-secret-91@127.0.0.1:1/nowhere")
    monkeypatch.setattr(base, "engine", dead)
    for outcome in (await check.check_database(), await check.check_migrations()):
        assert outcome.status == FAIL
        assert "Zx-db-secret-91" not in outcome.detail and "127.0.0.1" not in outcome.detail
    await dead.dispose()


async def test_buckets_usable_and_not_usable(monkeypatch, tmp_path):
    from apps.api import storage
    from apps.api.storage.local_storage import LocalStorage

    bucket = LocalStorage(str(tmp_path / "bucket"))
    monkeypatch.setattr(storage, "get_dataset_storage", lambda: bucket)
    monkeypatch.setattr(storage, "get_artifact_storage", lambda: bucket)
    usable = await check.check_buckets()
    assert usable.status == OK and usable.detail.startswith("datasets=") and ", artifacts=" in usable.detail

    def no_store():
        raise ConnectionError("http://phylo-minio:9000 with key AKIAZXSECRET refused")

    monkeypatch.setattr(storage, "get_artifact_storage", no_store)
    broken = await check.check_buckets()
    assert broken.status == FAIL and broken.detail == "artifacts bucket not usable (ConnectionError)"
