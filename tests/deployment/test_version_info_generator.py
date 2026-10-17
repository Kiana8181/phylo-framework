"""scripts/generate_version_info.py: what a deployment records about itself.

The script runs inside the API image build, where there is neither ``git`` nor
``docker``. Everything here therefore uses ``--no-commands`` and git
directories written by hand: the facts must come from the files alone.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate_version_info.py"
A, B, C = "a" * 40, "b" * 40, "c" * 40

spec = importlib.util.spec_from_file_location("generate_version_info", SCRIPT)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


def git_dir(tmp_path: Path, head: str, *, loose: dict[str, str] | None = None, packed: str | None = None) -> Path:
    directory = tmp_path / "gitdir"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "HEAD").write_text(head + "\n")
    for ref, sha in (loose or {}).items():
        path = directory / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sha + "\n")
    if packed is not None:
        (directory / "packed-refs").write_text(packed)
    return directory


def framework(directory: Path) -> tuple[dict, dict]:
    unavailable: dict[str, str] = {}
    return gen.framework_identity(ROOT, directory, False, unavailable), unavailable


# --------------------------------------------------------------------------- #
# Which commit, branch and version: from the files of a .git directory
# --------------------------------------------------------------------------- #
def test_a_branch_with_a_loose_ref(tmp_path):
    facts, unavailable = framework(git_dir(tmp_path, "ref: refs/heads/main", loose={"refs/heads/main": A}))
    assert facts == {"version": A[:7], "git_commit": A, "git_branch": "main", "git_dirty": None}
    # The image build cannot see the working tree, and says so instead of guessing.
    assert "working tree is not visible" in unavailable["framework.git_dirty"]
    assert "framework.git_commit" not in unavailable and "framework.version" not in unavailable


def test_a_fresh_clone_keeps_its_refs_packed(tmp_path):
    packed = f"# pack-refs with: peeled fully-peeled sorted \n{B} refs/heads/other\n{A} refs/heads/feat/x\n"
    facts, _ = framework(git_dir(tmp_path, "ref: refs/heads/feat/x", packed=packed))
    assert (facts["git_commit"], facts["git_branch"]) == (A, "feat/x")


def test_a_loose_ref_is_newer_than_the_packed_one(tmp_path):
    directory = git_dir(tmp_path, "ref: refs/heads/main", loose={"refs/heads/main": B},
                        packed=f"{A} refs/heads/main\n")
    assert framework(directory)[0]["git_commit"] == B


def test_a_tagged_commit_is_named_by_its_tag(tmp_path):
    packed = (f"{A} refs/heads/main\n{A} refs/tags/v1.9.0\n{B} refs/tags/v1.10.0\n"
              f"{C} refs/tags/v2.0.0\n^{A}\n")                      # v2.0.0 is annotated and points at A
    facts, _ = framework(git_dir(tmp_path, "ref: refs/heads/main", packed=packed))
    assert facts["version"] == "v2.0.0"                             # the highest of v1.9.0 and v2.0.0
    lightweight = git_dir(tmp_path / "second", "ref: refs/heads/main", loose={"refs/heads/main": A, "refs/tags/v1.9.0": A,
                                                                              "refs/tags/v1.10.0": A, "refs/tags/rc/x": B})
    assert framework(lightweight)[0]["version"] == "v1.10.0"        # numbers compare as numbers


def test_an_untagged_commit_is_named_by_its_abbreviated_id(tmp_path):
    packed = f"{A} refs/heads/main\n{B} refs/tags/v1.0.0\n"
    assert framework(git_dir(tmp_path, "ref: refs/heads/main", packed=packed))[0]["version"] == A[:7]


def test_a_detached_head_has_a_commit_and_no_branch(tmp_path):
    facts, unavailable = framework(git_dir(tmp_path, A))
    assert (facts["git_commit"], facts["git_branch"], facts["version"]) == (A, None, A[:7])
    assert "detached" in unavailable["framework.git_branch"]


@pytest.mark.parametrize("make", [
    lambda d: None,                                                  # no directory at all
    lambda d: d.mkdir(),                                             # an empty one (config/no-git)
    lambda d: (d.mkdir(), (d / "HEAD").write_text(""))[0],           # a damaged one
])
def test_without_git_data_nothing_is_invented(tmp_path, make):
    directory = tmp_path / "nogit"
    make(directory)
    facts, unavailable = framework(directory)
    assert facts == {"version": None, "git_commit": None, "git_branch": None, "git_dirty": None}
    assert unavailable["framework.git_commit"] == unavailable["framework.version"] == "not a git checkout at build time"


def test_a_head_that_resolves_to_nothing_is_reported(tmp_path):
    # e.g. a linked worktree: its refs live in another directory.
    facts, unavailable = framework(git_dir(tmp_path, "ref: refs/heads/gone"))
    assert facts["git_commit"] is None and facts["version"] is None and facts["git_branch"] == "gone"
    assert "could not be resolved" in unavailable["framework.git_commit"]


@pytest.mark.parametrize("head", ["ref: ../../outside", "ref: /etc/hostname", "ref: refs/heads/../../../outside"])
def test_head_cannot_point_outside_the_git_directory(tmp_path, head):
    (tmp_path / "outside").write_text(A + "\n")
    facts, _ = framework(git_dir(tmp_path, head))
    assert facts["git_commit"] is None


def test_garbage_in_ref_files_is_not_taken_for_a_commit(tmp_path):
    directory = git_dir(tmp_path, "ref: refs/heads/main", loose={"refs/heads/main": "not-a-sha; rm -rf /"},
                        packed="garbage line\n^orphan-peel\nzzzz refs/heads/main\n")
    assert framework(directory)[0]["git_commit"] is None


def test_sha256_repositories_are_understood(tmp_path):
    long = "d" * 64
    assert framework(git_dir(tmp_path, long))[0]["git_commit"] == long


# --------------------------------------------------------------------------- #
# The whole document, as the image build produces it
# --------------------------------------------------------------------------- #
def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "config/method-services.json").write_text(json.dumps({"services": [
        {"id": "gctree", "path": "services/gctree", "dockerImage": "phylo-gctree:dev"},
        {"id": "dowser", "dockerImage": "registry.example.org:5000/phylo/dowser"},
        {"id": "ghost", "dockerImage": None},
        {"name": "no id"},
    ]}))
    (repo / "services/gctree").mkdir(parents=True)
    (repo / "services/gctree/Dockerfile").write_text(
        "ARG PY=3.11\nFROM python:${PY}-slim AS build\nRUN python - <<'PY'\nfrom x import y\nPY\n"
        "FROM build AS runtime\nARG TOOL_COMMIT=abc123\n")
    (repo / "services/gctree/requirements.txt").write_text("gctree==4.3.0\nnumpy[extra]==2.2.6  # pinned\nrequests==2.0\nete3>=3\n")
    (repo / "services/dowser").mkdir(parents=True)
    (repo / "services/dowser/Dockerfile").write_text("FROM immcantation/suite:4.6.0\n")
    return repo


def test_the_document_the_image_build_writes(tmp_path):
    repo = make_repo(tmp_path)
    moment = datetime(2026, 10, 13, 8, 30, 5, 123456, tzinfo=timezone.utc)
    payload = gen.build_payload(repo, git_dir(tmp_path, "ref: refs/heads/main", loose={"refs/heads/main": A}),
                                use_commands=False, image_tag="latest", now=moment)
    assert payload["schema_version"] == 1 and payload["generated_at"] == "2026-10-13T08:30:05.123Z"
    assert payload["framework"]["git_commit"] == A and payload["reference_data"] is None
    gctree, dowser, ghost = (payload["services"][k] for k in ("gctree", "dowser", "ghost"))
    assert gctree == {
        "image_name": "phylo-gctree:latest",                         # the tag the deployment runs, not the dev tag
        "image_digest": None,
        "base_image": "python:3.11-slim",                            # build arg resolved, build stage skipped
        "build_args": {"PY": "3.11", "TOOL_COMMIT": "abc123"},
        "tool_versions": {"gctree": "4.3.0", "numpy": "2.2.6"},      # only the tools worth naming, only exact pins
    }
    assert dowser["image_name"] == "registry.example.org:5000/phylo/dowser:latest"   # a registry port is not a tag
    assert dowser["base_image"] == "immcantation/suite:4.6.0" and dowser["tool_versions"] == {}
    assert ghost["image_name"] is None and ghost["base_image"] is None
    assert set(payload["services"]) == {"gctree", "dowser", "ghost"}
    reasons = payload["unavailable"]
    assert "cannot ask the Docker daemon" in reasons["services.gctree.image_digest"]
    assert "services.ghost.image_digest" not in reasons and "Dockerfile not readable" in reasons["services.ghost.base_image"]
    assert "services.dowser.tool_versions" in reasons and "reference_data" in reasons


def test_a_repository_without_service_configuration_still_gets_a_document(tmp_path):
    payload = gen.build_payload(tmp_path, tmp_path / "nogit", use_commands=False)
    assert payload["services"] == {} and "config/method-services.json" in payload["unavailable"]["services"]
    assert payload["framework"]["git_commit"] is None


def test_the_script_runs_with_nothing_but_python_on_the_path(tmp_path):
    """As in the image build: no git, no docker, no node, no site packages."""
    repo = make_repo(tmp_path)
    out = tmp_path / "out" / "version-info.json"
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    done = subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT), "--root", str(repo), "--no-commands", "--image-tag", "latest",
         "--git-dir", str(git_dir(tmp_path, "ref: refs/heads/main", loose={"refs/heads/main": A})), "--out", str(out)],
        capture_output=True, text=True, env={"PATH": str(empty_bin)})
    assert done.returncode == 0, done.stderr
    payload = json.loads(out.read_text())
    assert payload["framework"]["git_commit"] == A and "3 services" in done.stdout


def test_on_this_repository_it_names_the_commit_git_names():
    """The files-only reading agrees with git itself on the real repository."""
    if not (ROOT / ".git").is_dir():
        pytest.skip("not run from a git checkout with a .git directory")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    if head.returncode != 0:
        pytest.skip("git is not installed")
    facts, _ = framework(ROOT / ".git")
    assert facts["git_commit"] == head.stdout.strip()
    payload = gen.build_payload(ROOT, ROOT / ".git", use_commands=False, image_tag="latest")
    assert set(payload["services"]) == {"dowser", "gctree", "brepphylo", "clonaltree"}
    assert all(s["image_name"] == f"phylo-{name}:latest" for name, s in payload["services"].items())


# --------------------------------------------------------------------------- #
# How the image gets it
# --------------------------------------------------------------------------- #
def test_the_api_image_writes_its_own_version_information():
    dockerfile = (ROOT / "apps/api/Dockerfile").read_text()
    # Works without the git context too: an empty stage of the same name stands in.
    assert "FROM scratch AS gitmeta" in dockerfile
    assert "generate_version_info.py" in dockerfile and "--no-commands" in dockerfile
    assert "COPY --from=version-info /out/version-info.json /version-info.json" in dockerfile
    assert "ENV PHYLO_VERSION_INFO_PATH=/version-info.json" in dockerfile
    # Only what names HEAD is copied from the git directory, never its objects.
    copies = [line for line in dockerfile.splitlines() if line.startswith("COPY --from=gitmeta")]
    assert copies == ["COPY --from=gitmeta HEA[D] packed-ref[s] /gitmeta/", "COPY --from=gitmeta ref[s] /gitmeta/refs/"]
    final_stage = dockerfile[dockerfile.rindex("\nFROM "):]
    assert "gitmeta" not in final_stage and "apt-get install -y --no-install-recommends \\\n    ca-certificates curl tini" in final_stage


def test_git_data_and_host_run_data_stay_out_of_the_build_context():
    ignored = (ROOT / ".dockerignore").read_text().splitlines()
    assert ".git" in ignored and "runtime" in ignored and ".env" in ignored


def test_the_old_host_side_capture_step_is_gone():
    assert not (ROOT / "scripts/generate-version-info.mjs").exists()
    package = json.loads((ROOT / "package.json").read_text())["scripts"]
    assert package["version:capture"] == "python3 scripts/generate_version_info.py"
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "runtime/version-info.json" not in compose and "version:capture" not in compose
    assert (ROOT / "config/no-git/README.md").is_file() and not (ROOT / "config/no-git/HEAD").exists()
