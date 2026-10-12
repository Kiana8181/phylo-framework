"""requirements.txt and requirements.lock must not drift apart.

The Dockerfiles install `-r requirements.txt -c requirements.lock`, and CI
audits the lock files. If a pin changes in one file but not the other, the
build either fails or silently audits versions that are not the ones deployed.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SERVICES = {
    "api": ROOT / "apps" / "api",
    "gctree": ROOT / "services" / "gctree",
    "clonaltree": ROOT / "services" / "clonaltree",
}
# Installed from distribution packages in the image, not from pip (gctree).
NOT_FROM_PIP = {"pyqt5"}
# Verified unused and removed; must not come back unnoticed.
REMOVED_FROM_API = {"python-jose", "ecdsa", "rq", "redis", "psycopg2-binary", "python-multipart"}


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^\s;]+)", line)
        assert match, f"{path.name}: every entry must be an exact pin, got {raw!r}"
        pins[_normalize(match.group(1))] = match.group(2)
    return pins


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_every_requirement_is_pinned_identically_in_the_lock(service):
    directory = SERVICES[service]
    requirements = _pins(directory / "requirements.txt")
    lock = _pins(directory / "requirements.lock")
    for name, version in requirements.items():
        if name in NOT_FROM_PIP:
            continue
        assert name in lock, f"{service}: {name} is missing from requirements.lock"
        assert lock[name] == version, (
            f"{service}: {name} is {version} in requirements.txt but {lock[name]} in "
            "requirements.lock - run scripts/update-python-locks.sh"
        )


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_dockerfile_installs_with_the_lock(service):
    dockerfile = (SERVICES[service] / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"pip install[^\n]*-c\s+\S*requirements\.lock", dockerfile), (
        f"{service}: Dockerfile must install with `-c requirements.lock`"
    )


def test_removed_api_dependencies_stay_removed():
    present = set(_pins(SERVICES["api"] / "requirements.txt")) | set(_pins(SERVICES["api"] / "requirements.lock"))
    assert not (present & REMOVED_FROM_API), sorted(present & REMOVED_FROM_API)
