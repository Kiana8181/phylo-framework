"""What this method service may use, and how that is split between jobs.

The service runs in a container with CPU and memory limits (cgroups). The host
may have many more cores than the container is allowed to use, and
``os.cpu_count()`` reports the host's. Everything here is derived from the
*effective* limits instead, so jobs neither oversubscribe the CPU allowance nor
get started when their memory is not there.

    effective CPUs      cgroup quota, CPU affinity and METHOD_CPU_LIMIT (lowest wins)
    job slots           how many jobs may run at once
    threads per job     CPU budget of one job (processes x threads inside it)
    memory admission    a job only starts if its estimated memory still fits

Tunables (all optional; unset or empty means "derive it"):

    METHOD_MAX_CONCURRENT_JOBS      job slots
    METHOD_THREADS_PER_JOB          CPU budget of one job
    METHOD_JOB_MEMORY_MB            estimated peak memory of one job
    METHOD_BASELINE_MEMORY_MB       memory the idle service itself needs
    METHOD_MEMORY_HEADROOM_PERCENT  share of the memory limit kept free (default 10)
    METHOD_CPU_LIMIT                lower the CPU count further (never raises it)

This file is shared verbatim by the Python method services (gctree,
clonaltree); services/dowser/resource_limits.R is the R counterpart.
"""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Optional

# Per-method memory estimates in MiB: (idle service, one job). Measured on the
# regression dataset; a job on a much larger dataset needs more. Override with
# METHOD_BASELINE_MEMORY_MB / METHOD_JOB_MEMORY_MB.
MEMORY_DEFAULTS_MB: dict[str, tuple[int, int]] = {
    "gctree": (160, 256),
    "clonaltree": (60, 192),
    "dowser": (850, 950),
    "brepphylo": (850, 950),
}
FALLBACK_MEMORY_MB = (256, 512)
DEFAULT_HEADROOM_PERCENT = 10.0

# cgroup v1 reports "no limit" as a huge number rather than "max".
_V1_UNLIMITED = 1 << 60


def _cgroup_root(env: Mapping[str, str]) -> Path:
    return Path(env.get("PHYLO_CGROUP_ROOT") or "/sys/fs/cgroup")


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="ascii", errors="ignore").strip()
    except OSError:
        return None


def _positive_float(raw: Optional[str]) -> Optional[float]:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 and math.isfinite(value) else None


def _positive_int(raw: Optional[str]) -> Optional[int]:
    value = _positive_float(raw)
    return int(value) if value is not None and value >= 1 else None


# --------------------------------------------------------------------------- #
# CPU
# --------------------------------------------------------------------------- #
def cgroup_cpu_limit(env: Mapping[str, str] = os.environ) -> Optional[float]:
    """CPU cores allowed by the cgroup quota, or None when there is no quota."""
    root = _cgroup_root(env)
    v2 = _read(root / "cpu.max")
    if v2:
        parts = v2.split()
        if len(parts) == 2 and parts[0] != "max":
            quota, period = _positive_float(parts[0]), _positive_float(parts[1])
            if quota and period:
                return quota / period
        return None
    for base in (root / "cpu", root / "cpu,cpuacct", root):
        quota = _read(base / "cpu.cfs_quota_us")
        period = _read(base / "cpu.cfs_period_us")
        if quota is not None and period is not None:
            q, p = _positive_float(quota), _positive_float(period)
            return q / p if q and p else None
    return None


def host_cpus() -> int:
    """CPUs this process may be scheduled on (affinity), else the host count."""
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        # sysconf, not os.cpu_count(): the latter may be patched by sitecustomize.
        try:
            return max(1, int(os.sysconf("SC_NPROCESSORS_ONLN")))
        except (AttributeError, OSError, ValueError):
            return 1


def effective_cpus(env: Mapping[str, str] = os.environ) -> float:
    """The CPU allowance that actually applies: the lowest of quota, affinity
    and the optional METHOD_CPU_LIMIT. Never more than the host offers."""
    candidates = [float(host_cpus())]
    quota = cgroup_cpu_limit(env)
    if quota:
        candidates.append(quota)
    override = _positive_float(env.get("METHOD_CPU_LIMIT"))
    if override:
        candidates.append(override)
    return min(candidates)


# --------------------------------------------------------------------------- #
# Memory
# --------------------------------------------------------------------------- #
def memory_limit_bytes(env: Mapping[str, str] = os.environ) -> Optional[int]:
    """Memory limit of the cgroup in bytes, or None when unlimited/unknown."""
    root = _cgroup_root(env)
    v2 = _read(root / "memory.max")
    if v2 is not None:
        return None if v2 == "max" else _positive_int(v2)
    for base in (root / "memory", root):
        v1 = _read(base / "memory.limit_in_bytes")
        if v1 is not None:
            limit = _positive_int(v1)
            return limit if limit and limit < _V1_UNLIMITED else None
    return None


def _stat_value(text: Optional[str], key: str) -> int:
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == key and parts[1].isdigit():
            return int(parts[1])
    return 0


def memory_in_use_bytes(env: Mapping[str, str] = os.environ) -> Optional[int]:
    """Memory the cgroup cannot give back without killing something: current
    usage minus reclaimable file cache. None when it cannot be read."""
    root = _cgroup_root(env)
    current = _read(root / "memory.current")
    if current is not None and current.isdigit():
        inactive = _stat_value(_read(root / "memory.stat"), "inactive_file")
        return max(0, int(current) - inactive)
    for base in (root / "memory", root):
        usage = _read(base / "memory.usage_in_bytes")
        if usage is not None and usage.isdigit():
            inactive = _stat_value(_read(base / "memory.stat"), "total_inactive_file")
            return max(0, int(usage) - inactive)
    return None


# --------------------------------------------------------------------------- #
# Capacity plan
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Capacity:
    method_id: str
    cpus: float
    memory_limit_mb: Optional[int]
    baseline_memory_mb: int
    job_memory_mb: int
    headroom_percent: float
    job_slots: int
    threads_per_job: int
    slots_source: str  # "auto" or "configured"

    @property
    def memory_budget_mb(self) -> Optional[float]:
        """Memory jobs and service may use together: the limit minus headroom."""
        if self.memory_limit_mb is None:
            return None
        return self.memory_limit_mb * (1.0 - self.headroom_percent / 100.0)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["cpus"] = round(self.cpus, 2)
        return data


def plan_capacity(method_id: str, env: Mapping[str, str] = os.environ) -> Capacity:
    """Derive job slots and the per-job CPU budget from the effective limits.

    * At most one job per whole CPU, so jobs do not fight over cores.
    * No more jobs than the memory limit can hold (baseline + N x job estimate,
      inside the limit minus headroom). Zero when not even one job fits.
    * The CPU allowance divided by the slots is each job's thread budget, so
      ``job_slots * threads_per_job`` never exceeds the allowance (rounded down
      to whole cores, minimum one).
    """
    cpus = effective_cpus(env)
    whole_cpus = max(1, int(math.floor(cpus + 1e-9)))

    default_baseline, default_job = MEMORY_DEFAULTS_MB.get(method_id, FALLBACK_MEMORY_MB)
    baseline = _positive_int(env.get("METHOD_BASELINE_MEMORY_MB")) or default_baseline
    job_memory = _positive_int(env.get("METHOD_JOB_MEMORY_MB")) or default_job
    headroom = _positive_float(env.get("METHOD_MEMORY_HEADROOM_PERCENT"))
    if headroom is None or headroom >= 90:
        headroom = DEFAULT_HEADROOM_PERCENT

    limit_bytes = memory_limit_bytes(env)
    limit_mb = int(limit_bytes // (1024 * 1024)) if limit_bytes else None

    configured = _positive_int(env.get("METHOD_MAX_CONCURRENT_JOBS"))
    if configured:
        slots, source = configured, "configured"
    else:
        slots, source = whole_cpus, "auto"
    if limit_mb is not None:
        budget = limit_mb * (1.0 - headroom / 100.0)
        memory_slots = int(math.floor((budget - baseline) / job_memory + 1e-9))
        slots = max(0, min(slots, memory_slots))

    threads = max(1, whole_cpus // max(1, slots))
    configured_threads = _positive_int(env.get("METHOD_THREADS_PER_JOB"))
    if configured_threads:
        # An operator may lower the per-job budget, never raise it above the allowance.
        threads = min(configured_threads, whole_cpus)

    return Capacity(
        method_id=method_id,
        cpus=cpus,
        memory_limit_mb=limit_mb,
        baseline_memory_mb=baseline,
        job_memory_mb=job_memory,
        headroom_percent=headroom,
        job_slots=slots,
        threads_per_job=threads,
        slots_source=source,
    )


# --------------------------------------------------------------------------- #
# Admission
# --------------------------------------------------------------------------- #
ACCEPT = "ACCEPT"
BUSY = "METHOD_BUSY"                      # retry later: capacity will free up
INSUFFICIENT = "INSUFFICIENT_CAPACITY"    # retrying cannot help: configuration


@dataclass(frozen=True)
class Admission:
    code: str
    reason: str = ""
    retry_after_seconds: int = 0

    @property
    def accepted(self) -> bool:
        return self.code == ACCEPT


def admit(capacity: Capacity, running_jobs: int, in_use_bytes: Optional[int]) -> Admission:
    """Decide whether one more job may start now."""
    if capacity.job_slots < 1:
        return Admission(
            INSUFFICIENT,
            (
                f"The {capacity.method_id} service has a memory limit of {capacity.memory_limit_mb} MiB, "
                f"which cannot hold the service ({capacity.baseline_memory_mb} MiB) plus one job "
                f"({capacity.job_memory_mb} MiB) with {capacity.headroom_percent:g}% headroom. "
                "Raise the memory budget or lower METHOD_JOB_MEMORY_MB."
            ),
        )
    if running_jobs >= capacity.job_slots:
        return Admission(
            BUSY,
            f"All {capacity.job_slots} {capacity.method_id} job slot(s) are in use.",
            retry_after_seconds=10,
        )
    budget_mb = capacity.memory_budget_mb
    if budget_mb is not None:
        # Memory already spoken for. A job that has just started has not
        # allocated its memory yet, so what is measured lags behind what will be
        # used: every running job counts for at least its estimate. Measured
        # usage wins when it is higher (jobs that turned out bigger than
        # estimated).
        reserved_mb = capacity.baseline_memory_mb + running_jobs * capacity.job_memory_mb
        measured_mb = in_use_bytes / (1024 * 1024) if in_use_bytes is not None else 0.0
        committed_mb = max(reserved_mb, measured_mb)
        if committed_mb + capacity.job_memory_mb > budget_mb:
            return Admission(
                BUSY,
                (
                    f"Not enough free memory for another {capacity.method_id} job: "
                    f"{committed_mb:.0f} MiB in use or reserved, a job needs about "
                    f"{capacity.job_memory_mb} MiB, budget {budget_mb:.0f} MiB."
                ),
                retry_after_seconds=15,
            )
    return Admission(ACCEPT)


# --------------------------------------------------------------------------- #
# Thread control inside a job
# --------------------------------------------------------------------------- #
def clamp_parallelism(requested: object, allowed: int) -> tuple[int, bool]:
    """Clamp a user-requested worker/thread count to ``allowed``.

    Returns (effective, was_reduced). Anything that is not a positive whole
    number counts as a request for 1.
    """
    try:
        wanted = int(requested)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        wanted = 1
    wanted = max(1, wanted)
    allowed = max(1, int(allowed))
    return min(wanted, allowed), wanted > allowed


def thread_environment(threads: int, *, blas_threads: Optional[int] = None) -> dict[str, str]:
    """Environment for a job's process tree that keeps it inside ``threads`` CPUs.

    ``threads`` is the job's whole CPU budget. Tools that pick their own thread
    count from the host's core count (OpenMP programs such as MUSCLE and
    IgPhyML, BLAS libraries, R's mclapply default, numexpr) read these
    variables instead. ``OMP_THREAD_LIMIT`` is a hard ceiling even for programs
    that request a number explicitly. ``blas_threads`` lets a method that
    already runs several processes keep its linear algebra single-threaded.
    """
    threads = max(1, int(threads))
    blas = max(1, min(threads, int(blas_threads))) if blas_threads else threads
    return {
        "PHYLO_JOB_THREADS": str(threads),
        "OMP_NUM_THREADS": str(threads),
        "OMP_THREAD_LIMIT": str(threads),
        "OPENBLAS_NUM_THREADS": str(blas),
        "GOTO_NUM_THREADS": str(blas),
        "MKL_NUM_THREADS": str(blas),
        "BLIS_NUM_THREADS": str(blas),
        "VECLIB_MAXIMUM_THREADS": str(blas),
        "NUMEXPR_NUM_THREADS": str(blas),
        "NUMEXPR_MAX_THREADS": str(blas),
        "RCPP_PARALLEL_NUM_THREADS": str(threads),
        "MC_CORES": str(threads),
    }


# Methods that already run several worker processes per job keep their linear
# algebra single-threaded, otherwise processes x BLAS threads multiply.
BLAS_THREADS_PER_METHOD: dict[str, int] = {
    "clonaltree": 1,  # multiprocessing pool sized by the (capped) CPU count
}


def job_environment(method_id: str, threads: int) -> dict[str, str]:
    """Thread-control environment for one job of ``method_id``."""
    return thread_environment(threads, blas_threads=BLAS_THREADS_PER_METHOD.get(method_id))


def job_threads(env: Mapping[str, str] = os.environ, method_id: str = "") -> int:
    """CPU budget of the current job: what the job manager handed down, else the
    plan for this container (direct /run calls, local development)."""
    handed = _positive_int(env.get("PHYLO_JOB_THREADS"))
    if handed:
        return handed
    return plan_capacity(method_id, env).threads_per_job
