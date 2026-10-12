"""scripts/resource-plan.sh: one global budget becomes per-container limits.

Pure script tests: no Docker, no services.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "resource-plan.sh"
CONTAINERS = {
    "POSTGRES", "MINIO", "MINIO_INIT", "API", "WORKER", "WEB",
    "DOWSER", "BREPPHYLO", "GCTREE", "CLONALTREE",
}
METHODS = {"DOWSER", "BREPPHYLO", "GCTREE", "CLONALTREE"}


def run(*args: str, env_file: Path | None = None) -> subprocess.CompletedProcess:
    cmd = ["sh", str(SCRIPT), "--env-file", str(env_file or "/dev/null"), *args]
    # A clean environment: the developer's exported PHYLO_* must not leak in.
    return subprocess.run(cmd, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin:/usr/local/bin"})


def plan(*args: str, env_file: Path | None = None) -> dict[str, dict[str, float]]:
    result = run("--env", *args, env_file=env_file)
    assert result.returncode == 0, result.stderr
    out: dict[str, dict[str, float]] = {}
    for line in result.stdout.splitlines():
        match = re.fullmatch(r"PHYLO_(CPUS|MEM|PIDS)_([A-Z_]+)=([0-9.]+)m?", line)
        if match:
            out.setdefault(match.group(2), {})[match.group(1)] = float(match.group(3))
    return out


def totals(p: dict[str, dict[str, float]]) -> tuple[float, float, float]:
    return (
        round(sum(v["CPUS"] for v in p.values()), 2),
        sum(v["MEM"] for v in p.values()),
        sum(v["PIDS"] for v in p.values()),
    )


def test_default_plan_covers_every_container_within_the_budget():
    p = plan()
    assert set(p) == CONTAINERS
    cpu, mem, pids = totals(p)
    assert cpu <= 4 and mem <= 8192 and pids <= 4096
    # Nothing is wasted either: the plan uses (almost) the whole budget.
    assert cpu >= 3.9 and mem >= 8192 - len(CONTAINERS) and pids >= 4096 - len(CONTAINERS)


@pytest.mark.parametrize(
    "cpus,memory,pids",
    [("2.05", "6592", "2432"), ("3", "7000", "3000"), ("4", "8192", "4096"),
     ("6.5", "12288", "5000"), ("8", "16384", "8192"), ("16", "65536", "32768"), ("3.333", "9999", "4097")],
)
def test_strict_plan_never_exceeds_the_budget(cpus, memory, pids):
    p = plan("--cpus", cpus, "--memory-mb", memory, "--pids", pids)
    cpu, mem, pid_total = totals(p)
    assert cpu <= float(cpus) + 1e-9
    assert mem <= int(memory)
    assert pid_total <= int(pids)


def test_every_container_keeps_its_measured_floor():
    """Floors come from measurement: an R service needs ~1.7 GiB for one job, and
    the MinIO init step is OOM-killed below ~128 MiB."""
    p = plan("--cpus", "2.05", "--memory-mb", "6592", "--pids", "2432")
    assert p["DOWSER"]["MEM"] >= 2048 and p["BREPPHYLO"]["MEM"] >= 2048
    assert p["GCTREE"]["MEM"] >= 512 and p["CLONALTREE"]["MEM"] >= 384
    assert p["MINIO_INIT"]["MEM"] >= 256
    assert p["POSTGRES"]["PIDS"] >= 256  # one process per connection
    assert all(v["CPUS"] > 0 for v in p.values())


def test_a_bigger_budget_gives_methods_more():
    small, big = plan(), plan("--cpus", "8", "--memory-mb", "16384")
    for name in METHODS:
        assert big[name]["CPUS"] > small[name]["CPUS"]
        assert big[name]["MEM"] > small[name]["MEM"]


@pytest.mark.parametrize(
    "args,variable",
    [
        (("--cpus", "1"), "PHYLO_CPU_BUDGET"),
        (("--memory-mb", "4096"), "PHYLO_MEMORY_BUDGET_MB"),
        (("--pids", "500"), "PHYLO_PIDS_BUDGET"),
    ],
)
def test_undersized_budget_is_refused_with_the_minimum(args, variable):
    result = run("--env", *args)
    assert result.returncode == 1
    assert variable in result.stderr and "below the minimum" in result.stderr
    assert result.stdout == ""  # no partial plan


@pytest.mark.parametrize("args", [("--cpus", "abc"), ("--memory-mb", "8g"), ("--pids", "-5"), ("--mode", "fast"), ("--bogus",)])
def test_invalid_input_is_rejected(args):
    result = run("--env", *args)
    assert result.returncode == 2
    assert result.stderr.startswith("resource-plan:")


def test_pooled_mode_only_relaxes_method_cpu():
    strict = plan("--cpus", "8", "--memory-mb", "16384")
    pooled = plan("--cpus", "8", "--memory-mb", "16384", "--mode", "pooled")
    method_share = round(sum(strict[m]["CPUS"] for m in METHODS), 2)
    for name in CONTAINERS:
        assert pooled[name]["MEM"] == strict[name]["MEM"]    # memory is never pooled
        assert pooled[name]["PIDS"] == strict[name]["PIDS"]
        if name in METHODS:
            assert pooled[name]["CPUS"] == method_share       # each method may use the whole share
        else:
            assert pooled[name]["CPUS"] == strict[name]["CPUS"]
    assert totals(pooled)[1] <= 16384
    # The human-readable output must say that the CPU caps now exceed the budget.
    shown = run("--cpus", "8", "--memory-mb", "16384", "--mode", "pooled").stdout
    assert "PHYLO_CGROUP_PARENT" in shown and "more than the budget" in shown


def test_budget_is_read_from_the_env_file_and_options_win(tmp_path):
    env = tmp_path / ".env"
    env.write_text('PHYLO_CPU_BUDGET=6\nPHYLO_MEMORY_BUDGET_MB="12288"  # half the server\nexport PHYLO_PIDS_BUDGET=5000\n')
    from_file = plan(env_file=env)
    assert totals(from_file)[1] <= 12288 and totals(from_file)[1] > 8192
    assert totals(from_file)[2] <= 5000 and totals(from_file)[2] > 4096
    assert totals(plan("--memory-mb", "9000", env_file=env))[1] <= 9000


def test_write_is_idempotent_and_keeps_the_rest_of_the_file(tmp_path):
    env = tmp_path / ".env"
    original = "JWT_SECRET_KEY=keep-me\nPHYLO_CPU_BUDGET=6\n\n# a comment\nOTHER=1\n"
    env.write_text(original)
    env.chmod(0o600)
    assert run("--write", env_file=env).returncode == 0
    first = env.read_text()
    assert first.startswith(original.rstrip("\n"))
    assert first.count("# >>> resource plan") == 1 and first.count("PHYLO_CPUS_API=") == 1
    assert run("--write", env_file=env).returncode == 0
    assert env.read_text() == first
    assert oct(env.stat().st_mode & 0o777) == "0o600"  # a secrets file keeps its permissions
    assert run("--check", env_file=env).returncode == 0


def test_check_detects_a_stale_plan(tmp_path):
    env = tmp_path / ".env"
    env.write_text("PHYLO_CPU_BUDGET=6\n")
    run("--write", env_file=env)
    env.write_text(env.read_text().replace("PHYLO_CPU_BUDGET=6", "PHYLO_CPU_BUDGET=5"))
    stale = run("--check", env_file=env)
    assert stale.returncode == 1 and "--write" in stale.stderr
    # The generated block is never mistaken for the budget itself.
    run("--write", env_file=env)
    assert run("--check", env_file=env).returncode == 0
    assert "cpu=5," in env.read_text()


def test_compose_fallbacks_equal_the_default_plan():
    """`docker compose up` without a generated block must apply the default plan,
    so the two can never drift apart."""
    compose = (ROOT / "docker-compose.yml").read_text()
    fallbacks = dict(re.findall(r"\$\{(PHYLO_(?:CPUS|MEM|PIDS)_[A-Z_]+):-([^}]+)\}", compose))
    default = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in run("--env").stdout.splitlines()
        if re.match(r"PHYLO_(CPUS|MEM|PIDS)_", line)
    }
    assert fallbacks == default
