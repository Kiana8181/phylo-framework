"""No credential and no env file in the repository, and the tool that checks it.

The first tests are the gate: they run scripts/scan_secrets.py on the files git
tracks here. The rest prove the scanner on throwaway repositories. Every fake
credential below is assembled at run time, so this file contains nothing the
scanner (or anyone else's) would report.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCANNER = ROOT / "scripts" / "scan_secrets.py"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
           "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": "/nonexistent"}

# Shaped like the real thing, obviously not real, never written out in one piece.
FAKE_RESEND = "re_" + "Ab3dEf9h" + "_" + "Zq7" * 8
FAKE_GOOGLE = "GOCSPX" + "-" + "aB3_" * 7
FAKE_AWS = "AKIA" + "QWERTYUIOP123456"
FAKE_GITHUB = "ghp_" + "a1B2" * 9
FAKE_PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----"
FAKE_DB_PASSWORD = "kT9" + "vLm2" * 5


def in_git_checkout() -> bool:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--is-inside-work-tree"], capture_output=True).returncode == 0


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=GIT_ENV)
    assert done.returncode == 0, done.stderr
    return done.stdout


def scan(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCANNER), "--repo", str(repo), *args], capture_output=True, text=True, env=GIT_ENV)


def fingerprint(value: str) -> str:
    return f"{hashlib.sha256(value.encode()).hexdigest()[:8]}/{len(value)}"


@pytest.fixture
def repo(tmp_path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("hello\n")
    (path / ".env.example").write_text(f"POSTGRES_PASSWORD=phylo_pass\nJWT_SECRET_KEY=change-me\nEXAMPLE_TOKEN=Xy12{'z' * 20}\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "start")
    return path


def commit(repo: Path, files: dict[str, str | bytes], message: str = "change") -> None:
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())
    git(repo, "add", "-A", "-f")
    git(repo, "commit", "-q", "-m", message)


# --------------------------------------------------------------------------- #
# The gate: this repository
# --------------------------------------------------------------------------- #
def test_no_credential_and_no_env_file_is_tracked_here():
    if not in_git_checkout():
        pytest.skip("not a git checkout")
    done = subprocess.run([sys.executable, str(SCANNER)], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "nothing found in the files tracked by git" in done.stdout


def test_only_example_env_files_are_tracked():
    if not in_git_checkout():
        pytest.skip("not a git checkout")
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True).stdout.splitlines()
    env_like = [p for p in tracked if re.search(r"(^|/)\.env", p)]
    assert env_like == [".env.example"]
    assert not [p for p in tracked if p.endswith((".DS_Store", ".pem", ".key", ".p12", ".pfx"))]


def test_env_files_keys_and_folder_metadata_are_ignored_everywhere():
    if not in_git_checkout():
        pytest.skip("not a git checkout")
    ignored = [".env", "apps/api/.env", "apps/web/.env", "services/gctree/.env", ".env.production", ".env.local",
               ".DS_Store", "docs/.DS_Store", "deploy/server.pem", "tls/private.key", "id_rsa", "id_ed25519.pub"]
    kept = [".env.example", "apps/api/database/migrations/env.py", "apps/api/security/tokens.py", "apps/api/security/keys.py"]
    check = lambda paths: subprocess.run(["git", "-C", str(ROOT), "check-ignore", "--no-index", *paths],   # noqa: E731
                                         capture_output=True, text=True).stdout.splitlines()
    assert sorted(check(ignored)) == sorted(ignored)
    assert check(kept) == []


def test_ci_runs_the_scanner_on_every_push():
    workflow = (ROOT / ".github/workflows/tests.yml").read_text()
    assert "python scripts/scan_secrets.py" in workflow


def test_the_example_configuration_holds_placeholders_only():
    """What is published as an example must be safe to publish."""
    example = (ROOT / ".env.example").read_text()
    for name in ("GOOGLE_CLIENT_SECRET", "JWT_SECRET_KEY", "POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD", "SMTP_PASSWORD"):
        for line in re.findall(rf"^#? ?{name}=(.*)$", example, re.MULTILINE):
            value = line.strip()
            assert not value or re.search(r"(?i)change|your|phylo_|secret|example|<", value), name
    assert "RESEND" not in example                                           # the old mail provider is gone entirely
    assert not re.search(r"\d{8,}-[a-z0-9]{20,}\.apps\.googleusercontent\.com", example)


# --------------------------------------------------------------------------- #
# The scanner
# --------------------------------------------------------------------------- #
def test_a_clean_repository_passes(repo):
    done = scan(repo)
    assert done.returncode == 0 and "nothing found" in done.stdout
    assert scan(repo, "--history").returncode == 0


@pytest.mark.parametrize("kind,value,line", [
    ("Resend API key", FAKE_RESEND, "RESEND_API_KEY={}"),
    ("Google OAuth client secret", FAKE_GOOGLE, 'client_secret = "{}"'),
    ("AWS access key id", FAKE_AWS, "aws_access_key_id: {}"),
    ("GitHub token", FAKE_GITHUB, "token={}"),
    ("Private key block", FAKE_PRIVATE_KEY, "{}"),
    ("Password inside a URL", FAKE_DB_PASSWORD, "DATABASE_URL=postgresql://app:{}@db.internal:5432/app"),
])
def test_each_kind_is_reported_by_place_and_fingerprint_never_by_value(repo, kind, value, line):
    commit(repo, {"config/settings.txt": "first line\n" + line.format(value) + "\n"})
    done = scan(repo)
    assert done.returncode == 1
    assert f"{kind}: 1 distinct value(s)" in done.stdout
    assert f"{fingerprint(value)}  in config/settings.txt:2" in done.stdout
    assert value not in done.stdout + done.stderr                            # the whole point
    assert value[8:24] not in done.stdout + done.stderr                      # not even part of it


def test_files_that_do_not_belong_are_reported_whatever_they_contain(repo):
    commit(repo, {".env": "A=1\n", "apps/api/.env": "", "services/x/.env.production": "B=2\n", ".DS_Store": b"\0\0binary",
                  "deploy/tls/server.key": "k\n", "apps/api/database/migrations/env.py": "x = 1\n", "docs/env.md": "notes\n"})
    done = scan(repo)
    assert done.returncode == 1
    listed = done.stdout.split("Files that must not be in a repository (tracked files):")[1].split("\n\n")[0].split()
    assert listed == [".DS_Store", ".env", "apps/api/.env", "deploy/tls/server.key", "services/x/.env.production"]


def test_placeholders_examples_and_marked_lines_are_not_reported(repo):
    marker = "scan-secrets" + ": fake"
    commit(repo, {
        "docs/setup.md": "DATABASE_URL=postgresql://phylo_user:phylo_pass@localhost:5440/phylo_db\n"
                         "postgresql://user:change-me-please@db/app\npostgresql://app:${POSTGRES_PASSWORD}@db/app\n"
                         "redis://default:<your-password>@cache:6379\n",
        "tests/test_keys.py": f'KEY = "{FAKE_RESEND}"  # {marker}\n',
        "compose.yml": f"url: http://reader:Xy12{'z' * 20}@host/x\n",        # the value .env.example publishes
        "logo.bin": b"\0\1\2" + FAKE_GOOGLE.encode(),                        # binary files are not text
    })
    done = scan(repo)
    assert done.returncode == 0, done.stdout


def test_the_scanner_does_not_report_itself_or_this_test():
    for path in (SCANNER, Path(__file__)):
        completed = subprocess.run([sys.executable, "-c",
                                    "import importlib.util,sys,pathlib;"
                                    "s=importlib.util.spec_from_file_location('m',sys.argv[1]);m=importlib.util.module_from_spec(s);"
                                    "s.loader.exec_module(m);print(len(m.scan_content(pathlib.Path(sys.argv[2]).read_bytes(), set())))",
                                    str(SCANNER), str(path)], capture_output=True, text=True)
        assert completed.stdout.strip() == "0", (path.name, completed.stdout, completed.stderr)


def test_deleting_a_credential_does_not_remove_it_from_history(repo):
    commit(repo, {".env": f"RESEND_API_KEY={FAKE_RESEND}\n", "notes.txt": f"key {FAKE_GOOGLE}\n"}, "oops")
    (repo / ".env").unlink()
    commit(repo, {"notes.txt": "cleaned\n"}, "remove the secrets")
    assert scan(repo).returncode == 0                                        # the tracked files are clean now
    history = scan(repo, "--history")
    assert history.returncode == 1
    assert "Resend API key: 1 distinct value(s)" in history.stdout and "Google OAuth client secret: 1" in history.stdout
    assert ".env  (1 version(s))" in history.stdout
    assert f"{fingerprint(FAKE_RESEND)}  in .env" in history.stdout
    assert FAKE_RESEND not in history.stdout and FAKE_GOOGLE not in history.stdout
    assert "must be replaced" in history.stdout                              # says what actually has to happen


def test_history_includes_other_branches_tags_and_the_stash(repo):
    git(repo, "checkout", "-q", "-b", "side")
    commit(repo, {"side.txt": f"{FAKE_AWS}\n"}, "on a side branch")
    git(repo, "checkout", "-q", "main")
    git(repo, "branch", "-q", "-D", "side")                                  # unreachable from any branch, still in the reflog
    (repo / "README.md").write_text(f"local edit {FAKE_GITHUB}\n")
    git(repo, "stash", "push", "-q", "-m", "server settings")
    history = scan(repo, "--history")
    assert history.returncode == 1
    assert "AWS access key id: 1 distinct value(s)" in history.stdout and "GitHub token: 1 distinct value(s)" in history.stdout
    assert scan(repo).returncode == 0


def test_a_bare_repository_can_be_scanned_for_history(repo, tmp_path):
    commit(repo, {".env": f"X={FAKE_GOOGLE}\n"})
    bare = tmp_path / "mirror.git"
    subprocess.run(["git", "clone", "-q", "--mirror", str(repo), str(bare)], check=True, capture_output=True, env=GIT_ENV)
    done = scan(bare, "--history")
    assert done.returncode == 1 and "Google OAuth client secret" in done.stdout
