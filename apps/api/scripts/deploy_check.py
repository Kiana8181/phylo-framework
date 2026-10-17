"""Is this deployment complete? Run inside the API container.

    docker compose exec -T api-prod python -m apps.api.scripts.deploy_check

(``./run.sh status`` does that after looking at the containers themselves.)

It answers the questions a fresh installation raises and that "the containers
are up" does not: is the database reachable and migrated to the newest
revision, do both buckets exist, does every method service answer, did the
image record which commit it was built from, and can email be sent.

Read-only, with one exception that changes nothing visible: asking the object
store about a bucket. It prints one line per check, never a secret or a
connection string, and exits 1 when a check failed. A warning does not fail it:
warnings are states an administrator may have chosen (email switched off, no
git information).
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

OK, WARN, FAIL = "ok", "warn", "fail"
CHECK_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class Outcome:
    name: str
    status: str
    detail: str


def _describe(exc: BaseException) -> str:
    """The kind of failure only: messages of driver errors can contain the
    connection string."""
    return type(exc).__name__


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
async def check_configuration() -> Outcome:
    from apps.api.security.production_config import collect_config_problems, is_production

    if not is_production():
        return Outcome("configuration", WARN, "ENV is not 'production': the secret checks are not enforced")
    problems = collect_config_problems()
    if problems:
        return Outcome("configuration", FAIL, "; ".join(problems))
    return Outcome("configuration", OK, "production settings accepted")


async def check_database() -> Outcome:
    from sqlalchemy import text

    from apps.api.database.base import engine

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        return Outcome("database", FAIL, f"not reachable ({_describe(exc)})")
    return Outcome("database", OK, "reachable")


def migration_heads() -> list[str]:
    """Newest revision(s) the code in this image knows."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from apps.api.config import ROOT_DIR

    config = Config(str(Path(ROOT_DIR) / "alembic.ini"))
    config.set_main_option("script_location", str(Path(ROOT_DIR) / "apps/api/database/migrations"))
    return sorted(ScriptDirectory.from_config(config).get_heads())


async def check_migrations() -> Outcome:
    from sqlalchemy import text

    from apps.api.database.base import engine

    try:
        wanted = migration_heads()
        async with engine.connect() as connection:
            applied = sorted(row[0] for row in await connection.execute(text("SELECT version_num FROM alembic_version")))
    except Exception as exc:  # noqa: BLE001
        return Outcome("migrations", FAIL, f"could not be read ({_describe(exc)})")
    if applied == wanted:
        return Outcome("migrations", OK, f"at {', '.join(applied)}")
    return Outcome("migrations", FAIL,
                   f"database is at {', '.join(applied) or 'no revision'}, this image expects {', '.join(wanted)}")


async def check_buckets() -> Outcome:
    from apps.api.storage import artifact_bucket, dataset_bucket, get_artifact_storage, get_dataset_storage

    names = []
    try:
        for label, factory, bucket in (("datasets", get_dataset_storage, dataset_bucket()),
                                       ("artifacts", get_artifact_storage, artifact_bucket())):
            storage = await asyncio.to_thread(factory)
            # A question about an object that does not exist: it is answered
            # "no such object" only when the bucket itself is there.
            await storage.stat("_deploy-check/absent")
            names.append(f"{label}={bucket or storage.get_storage_type()}")
    except Exception as exc:  # noqa: BLE001
        return Outcome("object storage", FAIL, f"{label} bucket not usable ({_describe(exc)})")
    return Outcome("object storage", OK, ", ".join(names))


async def check_methods() -> Outcome:
    from apps.api.contracts.loader import list_methods_from_contracts
    from apps.api.services import method_jobs_client as jobs

    method_ids = sorted(str(m.get("id")) for m in list_methods_from_contracts() if m.get("id"))
    if not method_ids:
        return Outcome("method services", FAIL, "no method is defined in the contracts directory")
    reachable, problems = [], []
    for method_id in method_ids:
        try:
            capacity = await jobs.get_capacity(method_id)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{method_id} ({_describe(exc)})")
            continue
        slots = getattr(capacity, "job_slots", None)
        reachable.append(f"{method_id}" + (f" ({slots} job slot{'s' if slots != 1 else ''})" if slots else ""))
    if problems:
        return Outcome("method services", FAIL, "not reachable: " + ", ".join(problems))
    return Outcome("method services", OK, ", ".join(reachable))


async def check_version_info() -> Outcome:
    from apps.api.services.version_info import load_version_info, version_info_path

    info = load_version_info(refresh=True)
    if info is None:
        return Outcome("version information", WARN,
                       f"no file at {version_info_path()}: results will not record which version produced them")
    framework = info.get("framework") or {}
    commit = framework.get("git_commit")
    if not commit:
        return Outcome("version information", WARN,
                       "the image was built without git information (see PHYLO_GIT_DIR): results will not record the commit")
    return Outcome("version information", OK,
                   f"{framework.get('version') or commit[:7]} (commit {commit[:12]}, built {info.get('generated_at')})")


async def check_email() -> Outcome:
    from apps.api.services.email import email_enabled, settings_problems

    if not email_enabled():
        return Outcome("email", WARN, "switched off (SMTP_HOST is empty): no notification or confirmation email is sent")
    problems = settings_problems()
    if problems:
        return Outcome("email", FAIL, "; ".join(problems))
    return Outcome("email", OK, "configured (not sent to: this check does not contact the mail server)")


CHECKS: tuple[Callable[[], Awaitable[Outcome]], ...] = (
    check_configuration, check_database, check_migrations, check_buckets,
    check_methods, check_version_info, check_email,
)


# --------------------------------------------------------------------------- #
async def run_checks(checks=CHECKS, timeout: float = CHECK_TIMEOUT_SECONDS) -> list[Outcome]:
    outcomes = []
    for check in checks:
        name = check.__name__.removeprefix("check_").replace("_", " ")
        try:
            outcomes.append(await asyncio.wait_for(check(), timeout=timeout))
        except asyncio.TimeoutError:
            outcomes.append(Outcome(name, FAIL, f"no answer within {timeout:g} seconds"))
        except Exception as exc:  # noqa: BLE001 - one broken check must not hide the others
            outcomes.append(Outcome(name, FAIL, f"check could not run ({_describe(exc)})"))
    return outcomes


def render(outcomes: list[Outcome]) -> str:
    label = {OK: "OK  ", WARN: "WARN", FAIL: "FAIL"}
    width = max(len(o.name) for o in outcomes)
    return "\n".join(f"  {label[o.status]}  {o.name.ljust(width)}  {o.detail}" for o in outcomes)


def exit_code(outcomes: list[Outcome]) -> int:
    return 1 if any(o.status == FAIL for o in outcomes) else 0


async def _main(as_json: bool) -> int:
    outcomes = await run_checks()
    try:
        from apps.api.database.base import close_db

        await close_db()
    except Exception:  # noqa: BLE001
        pass
    if as_json:
        print(json.dumps([o.__dict__ for o in outcomes], indent=2))
    else:
        print(render(outcomes))
    return exit_code(outcomes)


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    return asyncio.run(_main("--json" in argv))


if __name__ == "__main__":
    sys.exit(main())
