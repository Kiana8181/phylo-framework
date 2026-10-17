#!/usr/bin/env python3
"""Capture the identity of a deployment: which commit, which images, which pins.

Writes one JSON document that the worker copies into every run's stored result
under ``version_info``, so a result stays interpretable after the deployment
behind it has been rebuilt.

It runs in two places and needs nothing but the Python standard library:

  * inside the API image build (apps/api/Dockerfile), where there is no ``git``
    and no ``docker`` command. Git facts are then read directly from the files
    of the repository's ``.git`` directory, which Compose hands to the build as
    a named context;
  * on a developer's machine (``npm run version:capture``), where ``git`` and
    ``docker`` are used when present and add what only they can know.

    python3 scripts/generate_version_info.py [--out PATH] [--root DIR]
                                             [--git-dir DIR] [--no-commands]
                                             [--image-tag TAG]

A field that cannot be determined is written as ``null`` and its reason is
recorded under ``unavailable``, so a reader can tell "not captured" apart from
"captured as empty". Nothing here invents a version string.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 1
SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
# Only tools the thesis actually names are surfaced per service; the rest of a
# requirements file is build noise.
TOOLS_OF_INTEREST = {"gctree", "ete3", "numpy", "scipy", "biopython", "muscle"}

NO_GIT = "not a git checkout at build time"
NO_WORKTREE = "the working tree is not visible to an image build, so local modifications cannot be detected"
NO_DAEMON = "an image build cannot ask the Docker daemon; a locally built image has no registry digest either"


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def read_json(path: Path) -> Any:
    raw = read_text(path)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def run(command: list[str], cwd: Path) -> Optional[str]:
    """Trimmed stdout of a command, or None if it is missing or fails."""
    if shutil.which(command[0]) is None:
        return None
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


# --------------------------------------------------------------------------- #
# Git facts from the files of a .git directory (no git command)
# --------------------------------------------------------------------------- #
def _packed_refs(git_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """(ref -> object, ref -> commit an annotated tag points to)."""
    refs: dict[str, str] = {}
    peeled: dict[str, str] = {}
    last = None
    for line in (read_text(git_dir / "packed-refs") or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("^"):
            if last and SHA.match(line[1:]):
                peeled[last] = line[1:]
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2 and SHA.match(parts[0]):
            refs[parts[1]] = parts[0]
            last = parts[1]
    return refs, peeled


def _loose_ref(git_dir: Path, ref: str) -> Optional[str]:
    # A ref name comes from HEAD or from a directory listing below refs/; it is
    # never allowed to leave the git directory.
    if ".." in ref.split("/") or ref.startswith("/"):
        return None
    value = (read_text(git_dir / ref) or "").strip()
    return value if SHA.match(value) else None


def git_facts_from_files(git_dir: Path) -> Optional[dict[str, Any]]:
    """Commit, branch and exact tags of HEAD, or None when ``git_dir`` is not a
    git directory (no readable HEAD)."""
    head = (read_text(git_dir / "HEAD") or "").strip()
    if not head:
        return None
    packed, peeled = _packed_refs(git_dir)

    branch = None
    if head.startswith("ref:"):
        ref = head[4:].strip()
        commit = _loose_ref(git_dir, ref) or packed.get(ref)
        if ref.startswith("refs/heads/"):
            branch = ref[len("refs/heads/"):]
    else:
        commit = head if SHA.match(head) else None

    tags: list[str] = []
    if commit:
        candidates = {ref: sha for ref, sha in packed.items() if ref.startswith("refs/tags/")}
        tags_dir = git_dir / "refs" / "tags"
        if tags_dir.is_dir():
            for path in sorted(p for p in tags_dir.rglob("*") if p.is_file()):
                ref = "refs/tags/" + path.relative_to(tags_dir).as_posix()
                sha = _loose_ref(git_dir, ref)
                if sha:
                    candidates[ref] = sha
        # An annotated tag names a tag object; its commit is the peeled value,
        # which is only known for packed tags (every tag of a fresh clone).
        tags = sorted(
            (ref[len("refs/tags/"):] for ref, sha in candidates.items() if commit in (sha, peeled.get(ref))),
            key=_version_key,
        )
    return {"commit": commit, "branch": branch, "tags": tags}


def _version_key(tag: str) -> tuple:
    """Sort v1.9.0 before v1.10.0; anything that is not a number sorts as text."""
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in re.split(r"(\d+)", tag) if part)


def framework_identity(root: Path, git_dir: Path, use_commands: bool, unavailable: dict[str, str]) -> dict[str, Any]:
    facts = git_facts_from_files(git_dir)
    if facts is None:
        unavailable["framework.git_commit"] = NO_GIT
        unavailable["framework.version"] = NO_GIT
        return {"version": None, "git_commit": None, "git_branch": None, "git_dirty": None}

    commit, branch = facts["commit"], facts["branch"]
    version = dirty = None
    # `git` knows two things the files alone do not: how far HEAD is from the
    # nearest tag, and whether the working tree was modified.
    if use_commands and (root / ".git").exists() and git_dir.resolve() == (root / ".git").resolve():
        commit = run(["git", "rev-parse", "HEAD"], root) or commit
        version = run(["git", "describe", "--tags", "--always", "--dirty"], root)
        status = run(["git", "status", "--porcelain"], root) if version is not None else None
        dirty = None if status is None else bool(status)

    if commit is None:
        unavailable["framework.git_commit"] = "HEAD of the git directory could not be resolved to a commit"
    if version is None and commit is not None:
        # Without `git`: the tag when the deployed commit is exactly a tagged
        # one, otherwise the abbreviated commit, as `git describe --always`
        # prints for a commit with no tag.
        version = facts["tags"][-1] if facts["tags"] else commit[:7]
    if version is None:
        unavailable["framework.version"] = "no commit to describe"
    if dirty is None:
        unavailable["framework.git_dirty"] = NO_WORKTREE if not use_commands else "git status unavailable"
    if branch is None and commit is not None:
        unavailable["framework.git_branch"] = "HEAD is detached (a commit or tag was checked out, not a branch)"
    return {"version": version, "git_commit": commit, "git_branch": branch, "git_dirty": dirty}


# --------------------------------------------------------------------------- #
# Services: what their build definitions declare
# --------------------------------------------------------------------------- #
def dockerfile_args(text: str) -> dict[str, str]:
    """``ARG NAME=value`` pairs of a Dockerfile."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$", line)
        if match:
            out[match.group(1)] = re.sub(r"^[\"']|[\"']$", "", match.group(2))
    return out


def dockerfile_base_image(text: str) -> Optional[str]:
    """Base image of the stage that ships: the last ``FROM <image>`` whose image
    is not an earlier build stage, with ``${ARG}`` references resolved from the
    Dockerfile's own defaults. (Upper-case ``FROM`` only: Dockerfile heredocs
    contain Python lines such as ``from x import y``.)"""
    args = dockerfile_args(text)
    stages: set[str] = set()
    base = None
    for line in text.splitlines():
        match = re.match(r"^\s*FROM\s+(\S+)(?:\s+AS\s+(\S+))?", line)
        if not match:
            continue
        image = re.sub(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", lambda m: args.get(m.group(1), m.group(0)), match.group(1))
        if image not in stages:
            base = image
        if match.group(2):
            stages.add(match.group(2))
    return base


def requirement_pins(text: str) -> dict[str, str]:
    """Pinned ``pkg==version`` lines of a pip requirements file."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([A-Za-z0-9._-]+)(?:\[[^\]]*\])?\s*==\s*([^\s#]+)", line)
        if match:
            out[match.group(1)] = match.group(2)
    return out


def with_tag(image: Optional[str], tag: Optional[str]) -> Optional[str]:
    """``image`` with its tag replaced (the name the deployment really runs)."""
    if not image or not tag:
        return image
    name = image.rsplit(":", 1)[0] if ":" in image.rsplit("/", 1)[-1] else image
    return f"{name}:{tag}"


def service_records(root: Path, use_commands: bool, image_tag: Optional[str],
                    unavailable: dict[str, str]) -> dict[str, Any]:
    config = read_json(root / "config" / "method-services.json")
    entries = config.get("services") if isinstance(config, dict) else None
    if not isinstance(entries, list) or not entries:
        unavailable["services"] = "config/method-services.json missing or has no services"
        return {}

    services: dict[str, Any] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        service_id = str(entry["id"])
        service_path = root / (entry.get("path") or f"services/{service_id}")
        record: dict[str, Any] = {
            "image_name": with_tag(entry.get("dockerImage"), image_tag),
            # A digest only exists once an image has been pushed to or pulled
            # from a registry; a locally built image has none.
            "image_digest": None,
            "base_image": None,
            "build_args": {},
            "tool_versions": {},
        }

        dockerfile = read_text(service_path / "Dockerfile")
        if dockerfile is None:
            unavailable[f"services.{service_id}.base_image"] = "Dockerfile not readable at build time"
        else:
            record["base_image"] = dockerfile_base_image(dockerfile)
            record["build_args"] = dockerfile_args(dockerfile)

        for name in ("requirements.docker.txt", "requirements.txt"):
            requirements = read_text(service_path / name)
            if requirements is None:
                continue
            for package, version in requirement_pins(requirements).items():
                if package.lower() in TOOLS_OF_INTEREST:
                    record["tool_versions"][package] = version

        if record["image_name"]:
            digest = None
            if use_commands:
                digest = run(["docker", "image", "inspect", record["image_name"], "--format",
                              "{{index .RepoDigests 0}}"], root)
            if digest:
                record["image_digest"] = digest
            else:
                unavailable[f"services.{service_id}.image_digest"] = (
                    "image not present locally, or built without a registry digest" if use_commands else NO_DAEMON)

        if not record["tool_versions"]:
            unavailable[f"services.{service_id}.tool_versions"] = (
                "no pinned versions found in the build definition; the service reports its own at run time")
        services[service_id] = record
    return services


# --------------------------------------------------------------------------- #
def build_payload(root: Path, git_dir: Path, *, use_commands: bool, image_tag: Optional[str] = None,
                  now: Optional[datetime] = None) -> dict[str, Any]:
    unavailable: dict[str, str] = {}
    framework = framework_identity(root, git_dir, use_commands, unavailable)
    services = service_records(root, use_commands, image_tag, unavailable)
    # Reference data (germline databases and similar) is baked into the upstream
    # images rather than pinned by this repository.
    unavailable["reference_data"] = ("reference germline data is bundled inside the upstream tool images and "
                                     "carries no separate version in this deployment")
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z",
        "framework": framework,
        "services": services,
        "reference_data": None,
        "unavailable": unavailable,
    }


def main(argv: Optional[list[str]] = None) -> int:
    default_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=default_root, help="repository root (default: this script's)")
    parser.add_argument("--git-dir", type=Path, help="the repository's .git directory (default: <root>/.git)")
    parser.add_argument("--out", type=Path, help="output file (default: <root>/runtime/version-info.json)")
    parser.add_argument("--no-commands", action="store_true",
                        help="do not call git or docker even when they are installed (image builds)")
    parser.add_argument("--image-tag", help="tag the deployment runs the method images under (e.g. latest)")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    git_dir = (args.git_dir or root / ".git").resolve()
    out = (args.out or root / "runtime" / "version-info.json").resolve()
    payload = build_payload(root, git_dir, use_commands=not args.no_commands, image_tag=args.image_tag)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"version-info written to {out} (framework {payload['framework']['version'] or 'unknown'}, "
          f"{len(payload['services'])} services, {len(payload['unavailable'])} field(s) unavailable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
