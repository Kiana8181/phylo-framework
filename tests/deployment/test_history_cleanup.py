"""The history rewrite, run for real on throwaway repositories.

scripts/history-cleanup/rewrite-mirror.sh removes every `.env` and `.DS_Store`
from the whole history of a mirror clone; verify-rewrite.py proves that nothing
else changed. Both are exercised here with git-filter-repo itself (a test-only
dependency), including rewrites that are deliberately wrong, which the
verification must refuse.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REWRITE = ROOT / "scripts/history-cleanup/rewrite-mirror.sh"
VERIFY = ROOT / "scripts/history-cleanup/verify-rewrite.py"
VENV_BIN = Path(sys.executable).parent
PATH = f"{VENV_BIN}:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"
GIT_ENV = {"GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.invalid", "GIT_COMMITTER_NAME": "Ada",
           "GIT_COMMITTER_EMAIL": "ada@example.invalid", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
           "PATH": PATH, "HOME": "/nonexistent"}
FAKE_KEY = "re_" + "Ab3dEf9h" + "_" + "Zq7" * 8
FAKE_SECRET = "GOCSPX" + "-" + "aB3_" * 7

pytestmark = pytest.mark.skipif(
    shutil.which("git-filter-repo", path=PATH) is None,
    reason="git-filter-repo is not installed (pip install -r requirements-test.txt)")


def git(repo: Path, *args: str, date: str | None = None) -> str:
    env = dict(GIT_ENV)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
    assert done.returncode == 0, f"git {' '.join(args)}: {done.stderr}"
    return done.stdout.strip()


def write(repo: Path, files: dict[str, str | bytes]) -> None:
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())


class Project:
    """A small repository with the same kinds of mistakes as the real one."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.source = tmp_path / "source"
        self.source.mkdir()
        r, n = self.source, iter(range(1, 60))
        day = lambda: f"2026-01-{next(n):02d}T10:00:00+00:00"                # noqa: E731
        commit = lambda message: (git(r, "add", "-A", "-f"), git(r, "commit", "-q", "-m", message, date=day()))  # noqa: E731
        git(r, "init", "-q", "-b", "main")
        write(r, {"README.md": "project\n", ".env.example": "API_KEY=change-me\n", "apps/api/main.py": "print('hi')\n",
                  "apps/api/database/migrations/env.py": "config = None\n", ".envrc": "use flake\n"})
        commit("first commit")
        write(r, {".env": f"RESEND_API_KEY={FAKE_KEY}\nGOOGLE_CLIENT_SECRET={FAKE_SECRET}\n", "apps/api/.env": "DEBUG=1\n",
                  ".DS_Store": b"\0\0\1Bud1", "apps/api/main.py": "print('hello')\n"})
        commit("add settings\n\nwith a body that must survive")
        git(r, "tag", "v1.0.0")                                              # lightweight tag
        write(r, {".env": f"RESEND_API_KEY={FAKE_KEY}\nGOOGLE_CLIENT_SECRET={FAKE_SECRET}\nEXTRA=1\n"})
        commit("only the env file changes")                                 # will disappear
        git(r, "checkout", "-q", "-b", "feature/x")
        write(r, {"apps/web/.env": "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000\n", "apps/web/page.tsx": "export {}\n",
                  "docs/.DS_Store": b"\0junk"})
        commit("feature work")
        git(r, "checkout", "-q", "main")
        write(r, {"apps/api/worker.py": "pass\n"})
        commit("main moves on")
        git(r, "merge", "-q", "--no-ff", "feature/x", "-m", "Merge feature/x", date=day())
        git(r, "tag", "-a", "v1.1.0", "-m", "release 1.1.0", date=day())     # annotated tag
        (r / ".env").unlink()
        commit("stop tracking the env file")                                # also disappears
        write(r, {"apps/api/main.py": "print('final')\n"})
        commit("last commit")
        self.original = tmp_path / "original.git"
        self.mirror = tmp_path / "mirror.git"
        subprocess.run(["git", "clone", "-q", "--mirror", str(self.source), str(self.original)], check=True,
                       capture_output=True, env=GIT_ENV)
        shutil.copytree(self.original, self.mirror)

    def rewrite(self, target: Path | None = None, path: str = PATH) -> subprocess.CompletedProcess:
        return subprocess.run(["sh", str(REWRITE), str(target or self.mirror)], capture_output=True, text=True,
                              env={**GIT_ENV, "PATH": path})

    def verify(self, rewritten: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(VERIFY), str(self.original), str(rewritten or self.mirror)],
                              capture_output=True, text=True, env=GIT_ENV)

    def filter_repo(self, target: Path, *args: str) -> None:
        """A rewrite other than the intended one, for the negative tests."""
        subprocess.run(["git", "-C", str(target), "filter-repo", "--force", *args], check=True, capture_output=True, env=GIT_ENV)


@pytest.fixture
def project(tmp_path) -> Project:
    return Project(tmp_path)


# --------------------------------------------------------------------------- #
# The intended rewrite
# --------------------------------------------------------------------------- #
def test_env_files_and_folder_metadata_leave_the_whole_history_and_nothing_else_does(project):
    before = git(project.original, "rev-list", "--all", "--count")
    done = project.rewrite()
    assert done.returncode == 0, done.stdout + done.stderr
    m = project.mirror

    everything = git(m, "rev-list", "--all", "--objects")
    paths = {line.split(" ", 1)[1] for line in everything.splitlines() if " " in line}
    for gone in (".env", "apps/api/.env", "apps/web/.env", ".DS_Store", "docs/.DS_Store"):
        assert gone not in paths, gone
    # Similar names are not env files and stay: the example, a module called env.py, .envrc.
    for kept in (".env.example", "apps/api/database/migrations/env.py", ".envrc", "apps/api/main.py", "apps/web/page.tsx"):
        assert kept in paths, kept
    assert git(m, "log", "--all", "--oneline", "--", ".env", "apps/api/.env", "apps/web/.env") == ""
    # The fake credentials are in no version of any file any more.
    for sha in (line.split()[0] for line in everything.splitlines()):
        if git(m, "cat-file", "-t", sha) == "blob":
            content = git(m, "cat-file", "blob", sha)
            assert FAKE_KEY not in content and FAKE_SECRET not in content

    # Two commits changed nothing but the env file: they are gone. The rest is the same story.
    assert int(git(m, "rev-list", "--all", "--count")) == int(before) - 2
    subjects = git(m, "log", "--format=%s", "main").splitlines()
    assert subjects == ["last commit", "Merge feature/x", "main moves on", "feature work", "add settings", "first commit"]
    assert git(m, "log", "-1", "--format=%b", "v1.0.0") == "with a body that must survive"
    assert git(m, "log", "-1", "--format=%an <%ae> %at", "v1.0.0") == "Ada <ada@example.invalid> 1767348000"   # 2026-01-02 10:00 UTC
    assert len(git(m, "log", "-1", "--format=%P", "main~1").split()) == 2    # the merge is still a merge
    assert git(m, "for-each-ref", "--format=%(refname) %(objecttype)", "refs/tags").splitlines() == [
        "refs/tags/v1.0.0 commit", "refs/tags/v1.1.0 tag"]
    assert git(m, "for-each-ref", "--format=%(contents:subject)", "refs/tags/v1.1.0") == "release 1.1.0"
    assert sorted(git(m, "for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines()) == ["feature/x", "main"]
    # Commit ids change, and the mapping from old to new is kept.
    assert git(m, "rev-parse", "main") != git(project.original, "rev-parse", "main")
    assert (m / "filter-repo/commit-map").is_file() and (m / "refs-before-rewrite.txt").is_file()


def test_the_rewrite_never_pushes_and_leaves_no_remote(project):
    assert git(project.mirror, "remote") == "origin"
    done = project.rewrite()
    assert done.returncode == 0
    assert git(project.mirror, "remote") == ""                               # nothing can be pushed from it by accident
    assert "nothing was pushed" in done.stdout
    # The source it was cloned from is untouched.
    assert ".env" in git(project.source, "log", "--all", "--name-only", "--format=")
    script = REWRITE.read_text()
    commands = [line.strip() for line in script.splitlines() if line.strip() and not line.strip().startswith("#")]
    assert not any("push" in line for line in commands if line.startswith("git") or " git " in line)


def test_the_verification_accepts_the_intended_rewrite(project):
    assert project.rewrite().returncode == 0
    done = project.verify()
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("  OK  ") == 9 and "FAIL" not in done.stdout
    assert "the 2 that disappeared changed nothing but removed files" in done.stdout
    assert "(the original has 2 credential value(s) and 5 forbidden path(s))" in done.stdout
    assert "verify-rewrite: all checks passed." in done.stdout
    assert FAKE_KEY not in done.stdout and FAKE_SECRET not in done.stdout


# --------------------------------------------------------------------------- #
# What it refuses
# --------------------------------------------------------------------------- #
def test_it_only_works_on_a_bare_mirror_and_only_once(project):
    checkout = project.rewrite(project.source)
    assert checkout.returncode == 1 and "is not a bare repository" in checkout.stderr
    assert ".env" in git(project.source, "log", "--all", "--name-only", "--format=")     # untouched
    assert project.rewrite(project.tmp / "nowhere").returncode == 1
    assert project.rewrite().returncode == 0
    again = project.rewrite()
    assert again.returncode == 1 and "already rewritten" in again.stderr


def test_it_refuses_the_repository_it_lives_in():
    if not (ROOT / ".git").is_dir():
        pytest.skip("not a git checkout with a .git directory")
    for target in (ROOT, ROOT / ".git"):
        done = subprocess.run(["sh", str(REWRITE), str(target)], capture_output=True, text=True, env={**GIT_ENV, "PATH": PATH})
        assert done.returncode == 1
        assert "not a bare repository" in done.stderr or "refusing to rewrite the repository this script lives in" in done.stderr


def test_without_the_tool_it_stops_before_touching_anything(project):
    before = git(project.mirror, "rev-parse", "main")
    done = project.rewrite(path="/usr/bin:/bin")
    assert done.returncode == 1 and "git-filter-repo not found" in done.stderr
    assert git(project.mirror, "rev-parse", "main") == before and git(project.mirror, "remote") == "origin"


# --------------------------------------------------------------------------- #
# Wrong rewrites must not pass the verification
# --------------------------------------------------------------------------- #
def test_a_rewrite_that_leaves_an_env_file_behind_fails(project):
    project.filter_repo(project.mirror, "--invert-paths", "--path", ".env")              # forgot the nested ones
    done = project.verify()
    assert done.returncode == 1
    assert "FAIL  removed paths still present" in done.stdout and "apps/api/.env" in done.stdout
    assert "Do not publish this mirror." in done.stdout


def test_a_rewrite_that_removes_too_much_fails(project):
    project.filter_repo(project.mirror, "--invert-paths", "--path-regex", r"(^|/)\.env$", "--path-regex", r"(^|/)\.DS_Store$",
                        "--path", "apps/api/worker.py")
    done = project.verify()
    assert done.returncode == 1 and "FAIL  file contents differ at" in done.stdout and "refs/heads/main" in done.stdout


def test_a_rewrite_that_changes_messages_or_authors_fails(project):
    project.filter_repo(project.mirror, "--invert-paths", "--path-regex", r"(^|/)\.env$", "--path-regex", r"(^|/)\.DS_Store$",
                        "--message-callback", "return message.replace(b'last commit', b'something else')")
    done = project.verify()
    assert done.returncode == 1 and "match no original commit" in done.stdout


def test_a_rewrite_that_loses_a_branch_or_a_tag_fails(project):
    assert project.rewrite().returncode == 0
    git(project.mirror, "update-ref", "-d", "refs/tags/v1.0.0")
    done = project.verify()
    assert done.returncode == 1 and "refs differ: missing ['refs/tags/v1.0.0']" in done.stdout


def test_a_credential_left_in_another_file_fails(project):
    """Removing the env files is not enough if a secret was also pasted elsewhere."""
    write(project.source, {"docs/notes.md": f"the key is {FAKE_KEY}\n"})
    git(project.source, "add", "-A")
    git(project.source, "commit", "-q", "-m", "notes", date="2026-02-01T10:00:00+00:00")
    for copy in (project.original, project.mirror):
        shutil.rmtree(copy)
    subprocess.run(["git", "clone", "-q", "--mirror", str(project.source), str(project.original)], check=True,
                   capture_output=True, env=GIT_ENV)
    shutil.copytree(project.original, project.mirror)
    assert project.rewrite().returncode == 0
    done = project.verify()
    assert done.returncode == 1 and "FAIL  scanner still finds: {'Resend API key': 1}" in done.stdout
    assert FAKE_KEY not in done.stdout


# --------------------------------------------------------------------------- #
def test_the_procedure_is_documented_with_its_consequences():
    guide = (ROOT / "docs/HISTORY-CLEANUP.md").read_text()
    for needed in ("rewrite-mirror.sh", "verify-rewrite.py", "git clone --mirror", "--force", "Rotate", "Replacing every clone",
                   "cp .env", "refs/pull", "does not make it secret again"):
        assert needed in guide, needed
    assert os.access(REWRITE, os.X_OK) and os.access(VERIFY, os.X_OK)
