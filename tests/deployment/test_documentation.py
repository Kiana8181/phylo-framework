"""The documentation describes the code that is here.

Checked on the files themselves, so that documentation cannot drift silently:
links resolve, the commands and scripts it names exist, the settings it names
are real, the configuration reference and ``.env.example`` cover the same
settings with the same defaults, and things that were removed are no longer
described as steps to take.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
# Upstream ClonalTree code, kept as it came: its own README is not ours to check.
UPSTREAM = "services/clonaltree/base-codes/"


def tracked(suffix: str) -> list[str]:
    # Tracked files and new ones not yet committed (ignored files never).
    done = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
                          capture_output=True, text=True)
    if done.returncode != 0:
        pytest.skip("not a git checkout")
    return [p for p in done.stdout.splitlines()
            if p.endswith(suffix) and not p.startswith(UPSTREAM) and (ROOT / p).is_file()]


DOCS = tracked(".md")
TEXT = {path: (ROOT / path).read_text(encoding="utf-8") for path in DOCS}
OPERATOR_DOCS = ["README.md", "docs/DEPLOYMENT.md", "docs/CONFIGURATION.md", "docs/DEVELOPMENT.md", "docs/VALIDATION.md",
                 "docs/TESTING.md", "docs/SECURITY-AUDIT.md", "docs/HISTORY-CLEANUP.md"]
PACKAGE = json.loads((ROOT / "package.json").read_text())["scripts"]
WEB_PACKAGE = json.loads((ROOT / "apps/web/package.json").read_text())["scripts"]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
COMPOSE_TEXT = (ROOT / "docker-compose.yml").read_text()
ENV_EXAMPLE = (ROOT / ".env.example").read_text()
REFERENCE = TEXT["docs/CONFIGURATION.md"]


def without_code_blocks(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def code_blocks(text: str) -> list[str]:
    return re.findall(r"```(?:bash|sh|shell)?\n(.*?)```", text, flags=re.S)


def slug(heading: str) -> str:
    """The anchor GitHub gives a heading."""
    text = re.sub(r"`|\*|_(?=\w)|(?<=\w)_", lambda m: "" if m.group(0) in "`*" else m.group(0), heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def anchors(path: str) -> set[str]:
    found: set[str] = set()
    for line in without_code_blocks(TEXT[path]).splitlines():
        match = re.match(r"#{1,6}\s+(.*)", line)
        if match:
            base = slug(match.group(1))
            name, n = base, 1
            while name in found:
                name, n = f"{base}-{n}", n + 1
            found.add(name)
    return found


# --------------------------------------------------------------------------- #
# Links
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", DOCS)
def test_every_relative_link_leads_somewhere(path):
    problems = []
    for label, target in re.findall(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)", without_code_blocks(TEXT[path])):
        if re.match(r"[a-z][a-z0-9+.-]*:", target):            # http:, https:, mailto:
            continue
        file_part, _, anchor = target.partition("#")
        destination = (ROOT / path).parent / file_part if file_part else ROOT / path
        if not destination.exists():
            problems.append(f"[{label}]({target}): no such file")
            continue
        if anchor and destination.suffix == ".md":
            relative = destination.resolve().relative_to(ROOT).as_posix()
            if relative in TEXT and anchor not in anchors(relative):
                problems.append(f"[{label}]({target}): no heading '#{anchor}' in {relative}")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("path", DOCS)
def test_every_image_exists(path):
    for target in re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", TEXT[path]):
        if not target.startswith("http"):
            assert ((ROOT / path).parent / target).exists(), f"{path}: image {target} is missing"


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
RUN_SH_COMMANDS = {"prod", "check", "status", "ports", "down", "help"}


def all_commands() -> list[tuple[str, str]]:
    """(document, line) for every line inside a shell block or an inline `code` span."""
    lines = []
    for path, text in TEXT.items():
        for block in code_blocks(text):
            lines += [(path, line.strip()) for line in block.splitlines() if line.strip() and not line.strip().startswith("#")]
        lines += [(path, span) for span in re.findall(r"`([^`\n]+)`", without_code_blocks(text))]
    return lines


COMMANDS = all_commands()


def test_every_npm_script_named_in_the_documentation_exists():
    missing = set()
    for path, line in COMMANDS:
        for name in re.findall(r"npm run ([a-z][\w:.-]*)", line):
            if name not in PACKAGE:
                missing.add((path, name))
        for name in re.findall(r"npm -w web run ([a-z][\w:.-]*)", line):
            if name not in WEB_PACKAGE:
                missing.add((path, f"web:{name}"))
    assert not missing, sorted(missing)


def test_every_run_sh_command_named_in_the_documentation_exists():
    runner = (ROOT / "run.sh").read_text()
    for name in RUN_SH_COMMANDS - {"help"}:
        assert re.search(rf"^\s*{name}\)", runner, re.M), name       # the list above is what run.sh implements
    unknown = {(path, word) for path, line in COMMANDS
               for word in re.findall(r"\./run\.sh ([a-z][\w-]*)", line) if word not in RUN_SH_COMMANDS}
    assert not unknown, sorted(unknown)


def test_every_script_and_file_path_named_in_the_documentation_exists():
    missing = set()
    pattern = re.compile(r"(?<![\w./-])((?:scripts|apps|services|packages|tests|docs|config)/[\w./-]+(?:\(site\)[\w./-]+)?"
                         r"\.(?:sh|py|mjs|R|yml|json|md|ts|tsx))(?![\w/-])")
    for path, text in TEXT.items():
        if path == "docs/TESTING.md":                           # also lists report files that tests generate
            text = text.split("## Coverage and evidence")[0] + text.split("## Test matrix and audit findings")[-1]
        for candidate in pattern.findall(text):
            if "<" in candidate or "*" in candidate or "{" in candidate:
                continue
            if not (ROOT / candidate).exists():
                missing.add((path, candidate))
    assert not missing, sorted(missing)


def test_compose_commands_use_profiles_and_services_that_exist():
    services = COMPOSE["services"]
    by_profile = {profile: {name for name, s in services.items() if profile in s.get("profiles", [])} for profile in ("dev", "prod")}
    problems = []
    for path, line in COMMANDS:
        if "docker compose" not in line or "docker-compose.test.yml" in line or "phylo-framework-mirror" in line:
            continue
        profiles = re.findall(r"--profile (\S+)", line)
        for profile in profiles:
            if profile not in ("dev", "prod", "full", "<dev"):        # `full` belongs to the test stack
                problems.append(f"{path}: unknown profile in `{line}`")
        match = re.search(r"\b(logs|exec|restart|stop|start|up|build)\b(.*)$", line)
        if not match or not profiles or profiles[0] not in by_profile:
            continue
        for word in match.group(2).split():
            if word.startswith(("-", "<", "$", "|", ">", "#", "&")) or word in ("python", "sh", "alembic", "grep"):
                if word in ("python", "sh", "alembic", "grep", "|", "#", "&&"):
                    break
                continue
            if re.fullmatch(r"[a-z][a-z0-9-]*", word):
                if word in services and word not in by_profile[profiles[0]]:
                    problems.append(f"{path}: service '{word}' is not in profile '{profiles[0]}': `{line}`")
                elif word not in services and word not in ("always", "web", "api"):
                    continue
    assert not problems, "\n".join(problems)


def test_services_named_after_logs_and_exec_exist():
    """`docker compose ... logs api-prod` must name a real service."""
    services = set(COMPOSE["services"])
    problems = []
    for path, line in COMMANDS:
        if "docker-compose.test.yml" in line or "docker compose" not in line:
            continue
        for verb, rest in re.findall(r"\b(logs|exec)\b((?:\s+-\S+)*(?:\s+[a-z][a-z0-9-]+)+)", line):
            for word in rest.split():
                if word.startswith("-"):
                    continue
                if word in ("python", "sh", "alembic", "psql", "pg_dump", "cat"):
                    break
                if word not in services and not word.startswith("<"):
                    problems.append(f"{path}: '{word}' is not a service: `{line}`")
                if verb == "exec":
                    break
    assert not problems, "\n".join(problems)


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def example_settings() -> dict[str, str]:
    """Every setting in .env.example, active or commented out, with its value.
    (A commented line counts when it is an assignment, not a sentence.)"""
    return dict(re.findall(r"^(?:# )?([A-Z][A-Z0-9_]+)=(\S*)$", ENV_EXAMPLE, re.M))


def reference_names() -> set[str]:
    """Every setting named in a table cell of the configuration reference."""
    names: set[str] = set()
    for line in REFERENCE.splitlines():
        if line.startswith("|"):
            names |= set(re.findall(r"`([A-Z][A-Z0-9_]*(?:<[A-Z]+>[A-Z0-9_]*)*)(?:=[^`]*)?`", line))
    return names


def documented(name: str, names: set[str]) -> bool:
    if name in names:
        return True
    for pattern in (n for n in names if "<" in n):
        if re.fullmatch(re.sub(r"<[A-Z]+>", "[A-Z0-9_]+", pattern), name):
            return True
    return False


def settings_the_product_reads() -> set[str]:
    names = set(re.findall(r"\$\{([A-Z][A-Z0-9_]+)", COMPOSE_TEXT))
    names |= set(re.findall(r"\$\{([A-Z][A-Z0-9_]+)", (ROOT / "docker-compose.dev.yml").read_text()))
    patterns = [r"os\.getenv\(\s*[\"']([A-Z][A-Z0-9_]+)[\"']", r"os\.environ(?:\.get\(|\[)\s*[\"']([A-Z][A-Z0-9_]+)[\"']",
                r"_(?:get|env|seconds|number|flag)\(\s*(?:env,\s*)?[\"']([A-Z][A-Z0-9_]+)[\"']"]
    for path in tracked(".py"):
        if not path.startswith("apps/api/") or "/tests/" in path:
            continue
        text = (ROOT / path).read_text()
        for pattern in patterns:
            names |= set(re.findall(pattern, text))
    return names


# Read by the code, but not configuration of a deployment.
NOT_CONFIGURATION = {
    "TEST_DB_NAME", "TEST_DATABASE_URL",                       # the test harness
    "TZ",                                                       # forced to UTC by the API itself
    "VAR",                                                      # the word in a comment that explains ${VAR:?...}
}


def test_every_setting_in_the_example_file_is_in_the_reference():
    names = reference_names()
    missing = sorted(name for name in example_settings() if not documented(name, names))
    assert not missing, f"in .env.example but not in docs/CONFIGURATION.md: {missing}"


def test_every_setting_the_product_reads_is_in_the_reference():
    names = reference_names()
    missing = sorted(name for name in settings_the_product_reads()
                     if name not in NOT_CONFIGURATION and not documented(name, names))
    assert not missing, f"read by docker-compose.yml or the API but not in docs/CONFIGURATION.md: {missing}"


def test_the_reference_names_no_setting_that_does_not_exist():
    """Nothing invented: every name in the reference is in .env.example, in a
    compose file, or read by the application or a method service."""
    known = set(example_settings()) | settings_the_product_reads()
    sources = COMPOSE_TEXT + (ROOT / "docker-compose.dev.yml").read_text()
    for path in tracked(".py") + tracked(".R") + tracked(".sh") + tracked(".mjs") + tracked("Dockerfile"):
        if "/tests/" not in path and not path.startswith("tests/"):
            sources += (ROOT / path).read_text(errors="replace")
    unknown = []
    for name in sorted(reference_names()):
        if "<" in name:
            probe = re.sub(r"<[A-Z]+>", "DOWSER", name)
            alternatives = {probe, re.sub(r"<[A-Z]+>", "API", name)}
            if not any(a in known or a in sources for a in alternatives) and name.split("<")[0] not in sources:
                unknown.append(name)
        elif name not in known and name not in sources:
            unknown.append(name)
    assert not unknown, f"named in docs/CONFIGURATION.md but found nowhere in the product: {unknown}"


# The example shows a value to choose for these, not the default that applies when unset.
NOT_A_DEFAULT = {"JWT_SECRET_KEY", "ENV", "PHYLO_GIT_DIR", "S3_ENDPOINT_URL_DOCKER"}


def single_setting_defaults() -> dict[str, tuple[str, str]]:
    """setting -> (default in the reference, value in .env.example), for every
    setting that has a table row of its own with one literal default."""
    out = {}
    for name, value in example_settings().items():
        row = re.search(rf"^\| `{name}` \| `([^`]*)` \|", REFERENCE, re.M)
        if row is not None and value.strip() and name not in NOT_A_DEFAULT:
            out[name] = (row.group(1), value.strip())
    return out


@pytest.mark.parametrize("name", sorted(single_setting_defaults()))
def test_defaults_in_the_reference_match_the_example_file(name):
    in_reference, in_example = single_setting_defaults()[name]
    assert in_reference == in_example, f"{name}: reference says {in_reference!r}, .env.example has {in_example!r}"


def test_enough_defaults_are_compared_for_the_check_to_mean_something():
    assert len(single_setting_defaults()) >= 30


def test_settings_named_in_the_readme_and_the_guide_are_real():
    names = reference_names()
    unknown = set()
    for path in ("README.md", "docs/DEPLOYMENT.md", "docs/VALIDATION.md"):
        for token in re.findall(r"`([A-Z][A-Z0-9]*_[A-Z0-9_]*(?:<[A-Z]+>[A-Z0-9_]*)?)`", TEXT[path]):
            if re.fullmatch(r"[A-Z_]+", token) and token in ERROR_CODES_AND_OTHER_WORDS:
                continue
            if not documented(token, names) and not documented(re.sub(r"<[A-Z]+>", "DOWSER", token), names):
                unknown.add((path, token))
    assert not unknown, sorted(unknown)


# Upper-case words in the guides that are not settings: run states, error
# codes, stages, HTTP details.
ERROR_CODES_AND_OTHER_WORDS = {
    "QUEUE_TIMEOUT", "STAGING_TIMEOUT", "OUT_OF_MEMORY", "JOB_PROCESS_LOST", "METHOD_RESTARTED", "METHOD_UNREACHABLE",
    "ARTIFACT_UPLOAD_FAILED", "ARTIFACTS_MISSING", "INCOMPLETE_RESULT", "ARTIFACT_STORE_UNAVAILABLE", "RESULT_UNAVAILABLE",
    "WAITING_FOR_CAPACITY", "RUN_QUOTA_EXCEEDED", "RUN_SUBMISSION_LIMIT_EXCEEDED", "QUEUE_FULL", "RESULT_EXPIRED",
    "UPLOAD_TOO_LARGE", "EXECUTION_LOG_MISSING", "NO_EXECUTION_RECORD", "DATASET_DELETED", "OMP_NUM_THREADS", "OMP_THREAD_LIMIT",
    "LOGIN_IP", "LOGIN_ACCOUNT", "REGISTER_IP", "FORGOT_IP", "FORGOT_ACCOUNT", "VERIFY_IP", "VERIFY_ACCOUNT",
    "CAPTCHA_REQUIRED", "CAPTCHA_INVALID", "EMAIL_NOT_VERIFIED", "RATE_LIMITED",
}


# --------------------------------------------------------------------------- #
# Nothing removed is still described as a step, nothing planned as done
# --------------------------------------------------------------------------- #
STALE = [
    (r"npm run version:capture(?! writes)", "the version file is written by the image build; no step on the host"),
    (r"storage:check:docker", "needs Node on the host; use ./run.sh status or the in-container storage check"),
    (r"not yet applied", "the object store replacement is applied"),
    (r"worker uploads those outputs|the \*\*worker\*\* uploads them", "method services upload their results themselves"),
    (r"`method_jobs`", "there is no such volume"),
    (r"http://minio:9000", "the store is addressed as phylo-minio"),
    (r"will be connected in a future release|coming soon|not implemented yet", "describe what exists"),
    (r"\banonymous(ly)? (users?|runs?) (can|may)\b", "every run needs a signed-in user"),
    (r"bootstrapped with \[`create-next-app`\]", "framework boilerplate instead of documentation"),
    (r"submodule", "the ClonalTree pipeline code is part of this repository"),
]


@pytest.mark.parametrize("pattern,reason", STALE)
def test_what_was_removed_is_not_described_as_current(pattern, reason):
    hits = [path for path in OPERATOR_DOCS + ["apps/web/README.md", "apps/api/database/README.md"]
            if re.search(pattern, TEXT[path], re.I)]
    assert not hits, f"{reason}: still in {hits}"


def test_the_web_app_has_no_placeholder_pages():
    for path in tracked(".tsx"):
        if path.startswith("apps/web/app/"):
            assert "future release" not in (ROOT / path).read_text(), path


# --------------------------------------------------------------------------- #
# The README does its job
# --------------------------------------------------------------------------- #
def test_the_readme_answers_a_newcomers_questions_in_order():
    readme = TEXT["README.md"]
    headings = [line.lstrip("# ").strip() for line in readme.splitlines() if line.startswith("## ")]
    wanted = ["Choose your path", "Prerequisites", "Quick start on your own machine", "Deploying on a server", "`./run.sh`",
              "Docker Compose commands", "Configuration", "Troubleshooting", "Documentation"]
    positions = [headings.index(h) for h in wanted]                          # each exists...
    assert positions == sorted(positions), headings                           # ...in an order that reads from start to finish
    opening = readme.split("## ")[0]
    assert "Dowser" in opening and "GCtree" in opening and "BrepPhylo" in opening and "ClonalTree" in opening
    assert "| Web app |" in readme and "| Worker |" in readme                 # the components
    quick = readme.split("## Quick start on your own machine")[1].split("\n## ")[0]
    assert "docker compose --profile dev up -d --build" in quick and "http://localhost:3000" in quick
    assert "What happens at the first start" in quick                        # first-run initialisation
    server = readme.split("## Deploying on a server")[1].split("\n## ")[0]
    for step in ("./run.sh check", "./run.sh prod", "./run.sh status", "openssl rand -hex 32", "proxy_net"):
        assert step in server, step
    for document in ("docs/DEPLOYMENT.md", "docs/CONFIGURATION.md", "docs/DEVELOPMENT.md", "docs/TESTING.md",
                     "docs/VALIDATION.md", "docs/SECURITY-AUDIT.md", "docs/HISTORY-CLEANUP.md"):
        assert f"]({'./' + document})" in readme, document
    assert len(readme.splitlines()) < 300                                     # an entry point, not the manual


def test_the_recommended_local_start_works_from_a_fresh_clone():
    """The dev web container must not depend on anything a fresh clone lacks:
    it keeps the image's own dependencies although the source tree is mounted."""
    web = COMPOSE["services"]["web"]
    assert {"/srv/node_modules", "/srv/packages/contracts/dist", "/srv/apps/web/.next"} <= {
        v for v in web["volumes"] if isinstance(v, str)}
    assert "ports" in web and "ports" in COMPOSE["services"]["api"]           # reachable on localhost
    assert not any("ports" in COMPOSE["services"][name] for name in ("web-prod", "api-prod"))


def test_deleting_data_is_never_documented_without_saying_so():
    """Every place that shows `down -v` or the reset script says what it destroys."""
    for path in ("README.md", "docs/DEVELOPMENT.md", "docs/DEPLOYMENT.md", "docs/TESTING.md"):
        text = TEXT[path]
        for match in re.finditer(r"down -v|reset-local\.sh", text):
            nearby = text[max(0, match.start() - 700): match.end() + 700].lower()
            assert re.search(r"delet|wipe|throwaway|disposable|never|cleanup is|test containers", nearby), (path, match.group(0))


def test_the_retention_policy_is_documented_as_required():
    guide = TEXT["docs/DEPLOYMENT.md"].split("## Storage lifecycle and retention")[1].split("\n## ")[0]
    for point in ("default 60", "RESULT_RETENTION_DAYS", "fixed at the moment a run ends", "counted from the day of that deployment",
                  "Uploaded datasets", "Never automatically", "must download", "For ever, marked"):
        assert point in guide, point


# --------------------------------------------------------------------------- #
# Procedures that were found broken when they were executed as written
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("shell", ["bash", "sh"])
def test_the_example_configuration_can_be_read_by_a_shell(shell):
    """The development guide sources `.env`. An unquoted value with spaces
    stopped the shell there, and every setting after it was silently missing."""
    import shutil

    if shutil.which(shell) is None:
        pytest.skip(f"{shell} is not installed")
    script = 'set -a; . "$1"; set +a; printf "%s|%s|%s" "$SMTP_FROM" "$PHYLO_LOG_MAX_SIZE" "$METHOD_CLONALTREE_CONTAINER_PORT"'
    done = subprocess.run([shell, "-c", script, shell, str(ROOT / ".env.example")], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin"})
    assert done.returncode == 0 and done.stderr == "", done.stderr
    assert done.stdout == "Phylo Runner <phylo@example.org>|10m|8004"            # including what comes last in the file


def test_every_reader_of_the_example_configuration_sees_the_same_values():
    """Quoting a value for the shell must not change what the application gets."""
    from dotenv import dotenv_values

    script = 'set -a; . "$1"; set +a; env'
    done = subprocess.run(["sh", "-c", script, "sh", str(ROOT / ".env.example")], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin"})
    from_shell = dict(line.split("=", 1) for line in done.stdout.splitlines() if "=" in line)
    for name, value in dotenv_values(ROOT / ".env.example").items():
        assert from_shell.get(name) == value, name


def test_the_restore_procedure_is_the_one_that_was_tested():
    """Loading a dump into a database that already has its tables failed halfway
    and left a partial database without saying so."""
    section = TEXT["docs/DEPLOYMENT.md"].split("## Backup & restore")[1].split("\n## ")[0]
    assert "dropdb" in section and "createdb" in section and "ON_ERROR_STOP=1" in section
    assert section.index("stop api-prod api-worker-prod web-prod") < section.index("dropdb") < section.index("./run.sh prod --no-build")
    assert ". ./.env" not in section and "source .env" not in section          # credentials come from the running container
    assert "nothing in this project takes or schedules them" in section       # backups stay manual
    compose = COMPOSE_TEXT.lower()
    assert "pg_dump" not in compose and "backup" not in compose
