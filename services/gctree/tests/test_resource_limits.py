"""Resource awareness shared by the Python method services.

Everything is derived from the container's effective limits, never from the
host's core count. cgroup files are faked in a temp directory through
PHYLO_CGROUP_ROOT, so these tests run anywhere.
"""
from __future__ import annotations

import itertools
import os
import subprocess
import sys
from pathlib import Path

import pytest

import importlib.util

SERVICES = Path(__file__).resolve().parents[2]


def load_resource_limits(service: str):
    """Import one service's own copy of resource_limits.py."""
    name = f"resource_limits_of_{service}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SERVICES / service / "resource_limits.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses need the module to be registered
    spec.loader.exec_module(module)
    return module


rl = load_resource_limits("gctree")


@pytest.fixture(autouse=True, params=["gctree", "clonaltree"])
def service_copy(request, monkeypatch):
    """Every test below runs against each Python service's own file: both are
    shipped, so both are tested (they must also stay byte-identical)."""
    monkeypatch.setattr(sys.modules[__name__], "rl", load_resource_limits(request.param))
    return request.param


MIB = 1024 * 1024


def cgroup_v2(tmp_path: Path, *, cpu: str | None = None, memory: str | None = None,
              current: int | None = None, inactive_file: int = 0) -> dict[str, str]:
    if cpu is not None:
        (tmp_path / "cpu.max").write_text(cpu + "\n")
    if memory is not None:
        (tmp_path / "memory.max").write_text(memory + "\n")
    if current is not None:
        (tmp_path / "memory.current").write_text(f"{current}\n")
        (tmp_path / "memory.stat").write_text(f"anon 1\ninactive_file {inactive_file}\nactive_file 5\n")
    return {"PHYLO_CGROUP_ROOT": str(tmp_path)}


# --------------------------------------------------------------------------- #
# Reading limits
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("content,expected", [
    ("150000 100000", 1.5), ("60000 100000", 0.6), ("400000 100000", 4.0),
    ("max 100000", None), ("garbage", None), ("0 100000", None),
])
def test_cgroup_v2_cpu_quota(tmp_path, content, expected):
    assert rl.cgroup_cpu_limit(cgroup_v2(tmp_path, cpu=content)) == expected


def test_cgroup_v1_cpu_quota(tmp_path):
    (tmp_path / "cpu").mkdir()
    (tmp_path / "cpu" / "cpu.cfs_quota_us").write_text("250000\n")
    (tmp_path / "cpu" / "cpu.cfs_period_us").write_text("100000\n")
    assert rl.cgroup_cpu_limit({"PHYLO_CGROUP_ROOT": str(tmp_path)}) == 2.5
    (tmp_path / "cpu" / "cpu.cfs_quota_us").write_text("-1\n")  # v1 spelling of "no quota"
    assert rl.cgroup_cpu_limit({"PHYLO_CGROUP_ROOT": str(tmp_path)}) is None


def test_no_cgroup_files_means_no_quota(tmp_path):
    assert rl.cgroup_cpu_limit({"PHYLO_CGROUP_ROOT": str(tmp_path)}) is None
    assert rl.memory_limit_bytes({"PHYLO_CGROUP_ROOT": str(tmp_path)}) is None
    assert rl.memory_in_use_bytes({"PHYLO_CGROUP_ROOT": str(tmp_path)}) is None


def test_effective_cpus_is_the_lowest_of_quota_host_and_override(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "host_cpus", lambda: 64)  # a big shared server
    env = cgroup_v2(tmp_path, cpu="200000 100000")
    assert rl.effective_cpus(env) == 2.0                       # the quota, not 64
    assert rl.effective_cpus({**env, "METHOD_CPU_LIMIT": "1"}) == 1.0
    assert rl.effective_cpus({**env, "METHOD_CPU_LIMIT": "32"}) == 2.0  # cannot raise it
    monkeypatch.setattr(rl, "host_cpus", lambda: 1)
    assert rl.effective_cpus(env) == 1.0                       # never more than the host has
    monkeypatch.setattr(rl, "host_cpus", lambda: 64)
    assert rl.effective_cpus({"PHYLO_CGROUP_ROOT": str(tmp_path / "missing")}) == 64.0


def test_memory_limit_and_working_set(tmp_path):
    env = cgroup_v2(tmp_path, memory=str(800 * MIB), current=500 * MIB, inactive_file=120 * MIB)
    assert rl.memory_limit_bytes(env) == 800 * MIB
    # Reclaimable file cache does not count against a new job.
    assert rl.memory_in_use_bytes(env) == 380 * MIB
    (tmp_path / "memory.max").write_text("max\n")
    assert rl.memory_limit_bytes(env) is None


def test_cgroup_v1_memory(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "memory.limit_in_bytes").write_text(f"{512 * MIB}\n")
    (mem / "memory.usage_in_bytes").write_text(f"{300 * MIB}\n")
    (mem / "memory.stat").write_text(f"total_inactive_file {100 * MIB}\n")
    env = {"PHYLO_CGROUP_ROOT": str(tmp_path)}
    assert rl.memory_limit_bytes(env) == 512 * MIB
    assert rl.memory_in_use_bytes(env) == 200 * MIB
    (mem / "memory.limit_in_bytes").write_text("9223372036854771712\n")  # v1 "unlimited"
    assert rl.memory_limit_bytes(env) is None


# --------------------------------------------------------------------------- #
# Capacity plan
# --------------------------------------------------------------------------- #
@pytest.fixture
def big_host(monkeypatch):
    monkeypatch.setattr(rl, "host_cpus", lambda: 64)


@pytest.mark.parametrize("method,cpu,memory_mb,extra,slots,threads", [
    # The default strict plan of scripts/resource-plan.sh: one job, one thread.
    ("dowser", "60000 100000", 2448, {}, 1, 1),
    ("brepphylo", "60000 100000", 2448, {}, 1, 1),
    ("gctree", "60000 100000", 778, {}, 1, 1),
    ("clonaltree", "60000 100000", 584, {}, 1, 1),
    # More CPU than memory: memory decides (850 + 2 x 950 does not fit in 2448 - 10%).
    ("dowser", "400000 100000", 2448, {}, 1, 4),
    # Plenty of both: one job per whole CPU, one thread each.
    ("dowser", "400000 100000", 8192, {}, 4, 1),
    ("gctree", "250000 100000", 4096, {}, 2, 1),
    # Operator prefers fewer, wider jobs.
    ("dowser", "400000 100000", 8192, {"METHOD_MAX_CONCURRENT_JOBS": "1"}, 1, 4),
    ("dowser", "400000 100000", 8192, {"METHOD_MAX_CONCURRENT_JOBS": "2"}, 2, 2),
    # More jobs than CPUs is allowed (CPU only slows down), but each gets 1 thread.
    ("gctree", "100000 100000", 4096, {"METHOD_MAX_CONCURRENT_JOBS": "3"}, 3, 1),
    # ...and memory still caps a configured number.
    ("dowser", "400000 100000", 2448, {"METHOD_MAX_CONCURRENT_JOBS": "3"}, 1, 4),
    # A thread budget can be lowered, never raised above the container's CPUs.
    ("dowser", "400000 100000", 8192, {"METHOD_MAX_CONCURRENT_JOBS": "1", "METHOD_THREADS_PER_JOB": "2"}, 1, 2),
    ("dowser", "400000 100000", 8192, {"METHOD_MAX_CONCURRENT_JOBS": "1", "METHOD_THREADS_PER_JOB": "64"}, 1, 4),
    # A larger per-job estimate (big datasets) reduces the slots.
    ("gctree", "400000 100000", 2048, {"METHOD_JOB_MEMORY_MB": "900"}, 1, 4),
    # Not even one job fits: zero slots, reported as a configuration error.
    ("dowser", "400000 100000", 1024, {}, 0, 4),
])
def test_plan_capacity(tmp_path, big_host, method, cpu, memory_mb, extra, slots, threads):
    env = {**cgroup_v2(tmp_path, cpu=cpu, memory=str(memory_mb * MIB)), **extra}
    plan = rl.plan_capacity(method, env)
    assert (plan.job_slots, plan.threads_per_job) == (slots, threads)
    assert plan.memory_limit_mb == memory_mb


def test_no_limits_at_all_uses_the_host_but_stays_finite(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "host_cpus", lambda: 8)
    plan = rl.plan_capacity("gctree", {"PHYLO_CGROUP_ROOT": str(tmp_path)})
    assert plan.job_slots == 8 and plan.threads_per_job == 1 and plan.memory_limit_mb is None


def test_jobs_times_threads_never_exceeds_the_cpu_allowance(tmp_path, big_host):
    """The core guarantee: concurrent jobs x threads inside each job <= CPUs."""
    quotas = [0.3, 0.6, 1, 1.5, 2, 2.4, 3.9, 4, 8, 16.5]
    memories = [512, 778, 2448, 4096, 16384, 65536]
    configured = [None, 1, 2, 3, 8]
    for method, quota, memory, jobs in itertools.product(rl.MEMORY_DEFAULTS_MB, quotas, memories, configured):
        env = cgroup_v2(tmp_path, cpu=f"{int(quota * 100000)} 100000", memory=str(memory * MIB))
        if jobs:
            env["METHOD_MAX_CONCURRENT_JOBS"] = str(jobs)
        plan = rl.plan_capacity(method, env)
        whole = max(1, int(quota))
        assert plan.threads_per_job >= 1
        if jobs is None:
            assert plan.job_slots * plan.threads_per_job <= whole, (method, quota, memory, plan)
        else:
            # Explicitly configured: more jobs than CPUs is the operator's choice,
            # but then every job is single-threaded.
            assert plan.job_slots * plan.threads_per_job <= max(whole, plan.job_slots)
        budget = memory * (1 - plan.headroom_percent / 100)
        assert plan.baseline_memory_mb + plan.job_slots * plan.job_memory_mb <= budget or plan.job_slots == 0


def test_invalid_tunables_fall_back_to_derived_values(tmp_path, big_host):
    env = {**cgroup_v2(tmp_path, cpu="200000 100000", memory=str(4096 * MIB)),
           "METHOD_MAX_CONCURRENT_JOBS": "many", "METHOD_THREADS_PER_JOB": "-3",
           "METHOD_JOB_MEMORY_MB": "", "METHOD_MEMORY_HEADROOM_PERCENT": "150"}
    plan = rl.plan_capacity("gctree", env)
    assert (plan.job_slots, plan.threads_per_job, plan.job_memory_mb, plan.headroom_percent) == (2, 1, 256, 10.0)


# --------------------------------------------------------------------------- #
# Admission
# --------------------------------------------------------------------------- #
def _plan(tmp_path, monkeypatch, **extra):
    monkeypatch.setattr(rl, "host_cpus", lambda: 64)
    return rl.plan_capacity("dowser", {**cgroup_v2(tmp_path, cpu="400000 100000", memory=str(8192 * MIB)), **extra})


def test_admission_accepts_while_a_slot_and_memory_are_free(tmp_path, monkeypatch):
    plan = _plan(tmp_path, monkeypatch)
    assert rl.admit(plan, running_jobs=0, in_use_bytes=850 * MIB).accepted
    assert rl.admit(plan, running_jobs=3, in_use_bytes=3700 * MIB).accepted


def test_admission_refuses_when_all_slots_are_used(tmp_path, monkeypatch):
    decision = rl.admit(_plan(tmp_path, monkeypatch), running_jobs=4, in_use_bytes=1000 * MIB)
    assert decision.code == rl.BUSY and "4 dowser job slot" in decision.reason
    assert decision.retry_after_seconds > 0


def test_admission_refuses_when_memory_is_short_even_with_free_slots(tmp_path, monkeypatch):
    """Memory does not slow down gracefully: a job that does not fit must wait."""
    plan = _plan(tmp_path, monkeypatch)
    budget_mb = 8192 * 0.9
    fits = int((budget_mb - 950 - 1) * MIB)
    too_much = int((budget_mb - 950 + 1) * MIB)
    assert rl.admit(plan, running_jobs=1, in_use_bytes=fits).accepted
    decision = rl.admit(plan, running_jobs=1, in_use_bytes=too_much)
    assert decision.code == rl.BUSY and "Not enough free memory" in decision.reason


def test_admission_reports_a_configuration_error_when_no_job_can_ever_fit(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "host_cpus", lambda: 64)
    plan = rl.plan_capacity("dowser", cgroup_v2(tmp_path, cpu="400000 100000", memory=str(1024 * MIB)))
    decision = rl.admit(plan, running_jobs=0, in_use_bytes=0)
    assert decision.code == rl.INSUFFICIENT and decision.retry_after_seconds == 0
    assert "1024 MiB" in decision.reason and "METHOD_JOB_MEMORY_MB" in decision.reason


def test_admission_without_readable_memory_only_counts_slots(tmp_path, monkeypatch):
    plan = _plan(tmp_path, monkeypatch)
    assert rl.admit(plan, running_jobs=0, in_use_bytes=None).accepted
    assert rl.admit(plan, running_jobs=4, in_use_bytes=None).code == rl.BUSY


def test_a_job_that_just_started_already_counts_for_its_estimate(tmp_path, monkeypatch):
    """Two submits in the same second: the first job has allocated nothing yet,
    so measured memory still looks idle. Its estimate must count as reserved, or
    both jobs are admitted and collide later (seen live: 2673 of 2704 MiB)."""
    monkeypatch.setattr(rl, "host_cpus", lambda: 64)
    env = {**cgroup_v2(tmp_path, cpu="200000 100000", memory=str(2704 * MIB)), "METHOD_MAX_CONCURRENT_JOBS": "2"}
    # Operator allowed two slots, but 850 + 2 x 950 does not fit in 2704 - 10%:
    # the plan itself already reduces that to one.
    assert rl.plan_capacity("dowser", env).job_slots == 1
    # Even where the plan allows two (a lower estimate), the reservation holds:
    plan = rl.plan_capacity("dowser", {**env, "METHOD_JOB_MEMORY_MB": "780"})
    assert plan.job_slots == 2
    idle_looking = 800 * MIB                                   # first job not grown yet
    assert rl.admit(plan, running_jobs=0, in_use_bytes=idle_looking).accepted
    assert rl.admit(plan, running_jobs=1, in_use_bytes=idle_looking).accepted   # 850+780+780 fits
    tight = rl.plan_capacity("dowser", {**env, "METHOD_JOB_MEMORY_MB": "780", "METHOD_BASELINE_MEMORY_MB": "900"})
    assert tight.job_slots == 1 or not rl.admit(tight, 1, idle_looking).accepted
    # Measured usage above the reservation still wins (a job bigger than estimated).
    decision = rl.admit(plan, running_jobs=1, in_use_bytes=1900 * MIB)
    assert decision.code == rl.BUSY and "in use or reserved" in decision.reason


# --------------------------------------------------------------------------- #
# Threads inside a job
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("requested,allowed,expected", [
    (1, 4, (1, False)), (4, 4, (4, False)), (64, 2, (2, True)), (10**9, 1, (1, True)),
    (0, 4, (1, False)), (-5, 4, (1, False)), ("8", 2, (2, True)), ("abc", 4, (1, False)),
    (None, 4, (1, False)), (3.9, 2, (2, True)), (2, 0, (1, True)),
])
def test_clamp_parallelism(requested, allowed, expected):
    assert rl.clamp_parallelism(requested, allowed) == expected


def test_thread_environment_caps_every_known_thread_pool():
    env = rl.thread_environment(3)
    for name in ("OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "NUMEXPR_MAX_THREADS", "BLIS_NUM_THREADS",
                 "VECLIB_MAXIMUM_THREADS", "RCPP_PARALLEL_NUM_THREADS", "MC_CORES", "PHYLO_JOB_THREADS"):
        assert env[name] == "3", name
    assert all(isinstance(v, str) for v in env.values())
    assert rl.thread_environment(0)["OMP_NUM_THREADS"] == "1"


def test_methods_with_their_own_process_pool_keep_blas_single_threaded():
    clonal = rl.job_environment("clonaltree", 4)
    # The pool and MUSCLE (OpenMP) get the budget; BLAS inside each pool worker gets 1.
    assert clonal["PHYLO_JOB_THREADS"] == "4" and clonal["OMP_NUM_THREADS"] == "4"
    assert clonal["OMP_THREAD_LIMIT"] == "4" and clonal["OPENBLAS_NUM_THREADS"] == "1"
    assert rl.job_environment("gctree", 4)["OPENBLAS_NUM_THREADS"] == "4"


def test_job_threads_prefers_what_the_job_manager_handed_down(tmp_path, big_host):
    env = cgroup_v2(tmp_path, cpu="400000 100000", memory=str(8192 * MIB))
    assert rl.job_threads({**env, "PHYLO_JOB_THREADS": "2"}, "dowser") == 2
    assert rl.job_threads({**env, "METHOD_MAX_CONCURRENT_JOBS": "1"}, "dowser") == 4
    assert rl.job_threads({**env, "PHYLO_JOB_THREADS": "junk"}, "dowser") == 1


# --------------------------------------------------------------------------- #
# Shared files stay identical; the CPU-count patch works
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("left,right", [
    ("gctree/resource_limits.py", "clonaltree/resource_limits.py"),
    ("gctree/job_manager.py", "clonaltree/job_manager.py"),
    ("dowser/resource_limits.R", "brepphylo/resource_limits.R"),
    ("dowser/job_manager.R", "brepphylo/job_manager.R"),
])
def test_shared_service_files_are_identical(left, right):
    assert (SERVICES / left).read_bytes() == (SERVICES / right).read_bytes(), (
        f"{left} and {right} must stay byte-identical; change one, copy to the other"
    )


def test_python_and_r_use_the_same_memory_estimates():
    import re
    text = (SERVICES / "dowser" / "resource_limits.R").read_text()
    for method, (baseline, job) in rl.MEMORY_DEFAULTS_MB.items():
        assert re.search(rf"{method} = c\({baseline}, {job}\)", text), method


@pytest.mark.parametrize("budget,expected", [("", None), ("1", 1), ("3", 3), ("junk", None), ("0", None)])
def test_sitecustomize_makes_cpu_count_report_the_job_budget(budget, expected):
    """ClonalTree's pipeline sizes a process pool with multiprocessing.cpu_count()."""
    script = (
        "import os, multiprocessing as mp\n"
        "pool = mp.Pool(); size = pool._processes; pool.close(); pool.join()\n"
        "print(os.cpu_count(), mp.cpu_count(), size)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(SERVICES / "clonaltree"), "PHYLO_JOB_THREADS": budget}
    out = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True)
    reported = [int(x) for x in out.stdout.split()]
    host = rl.host_cpus()
    want = min(host, expected) if expected else reported[0]
    assert reported == [want, want, want]
    if expected is None:
        assert reported[0] >= 1


# --------------------------------------------------------------------------- #
# Out-of-memory kill counter
# --------------------------------------------------------------------------- #
def test_oom_kill_count_reads_cgroup_v2_and_v1_and_reports_unknown_as_none(tmp_path):
    v2 = tmp_path / "v2"
    v2.mkdir()
    (v2 / "memory.events").write_text("low 0\nhigh 0\nmax 12\noom 3\noom_kill 2\n")
    assert rl.oom_kill_count({"PHYLO_CGROUP_ROOT": str(v2)}) == 2

    v1 = tmp_path / "v1"
    (v1 / "memory").mkdir(parents=True)
    (v1 / "memory" / "memory.oom_control").write_text("oom_kill_disable 0\nunder_oom 0\noom_kill 5\n")
    assert rl.oom_kill_count({"PHYLO_CGROUP_ROOT": str(v1)}) == 5

    # An old kernel whose file has no oom_kill line: zero kills are known of.
    (v1 / "memory" / "memory.oom_control").write_text("oom_kill_disable 0\nunder_oom 0\n")
    assert rl.oom_kill_count({"PHYLO_CGROUP_ROOT": str(v1)}) == 0

    empty = tmp_path / "none"
    empty.mkdir()
    assert rl.oom_kill_count({"PHYLO_CGROUP_ROOT": str(empty)}) is None
