# What this method service may use, and how that is split between jobs.
#
# The service runs in a container with CPU and memory limits (cgroups). The
# host may have many more cores than the container is allowed to use, and
# parallel::detectCores() reports the host's. Everything here is derived from
# the *effective* limits instead, so jobs neither oversubscribe the CPU
# allowance nor get started when their memory is not there.
#
#   effective CPUs      cgroup quota, usable cores and METHOD_CPU_LIMIT (lowest wins)
#   job slots           how many jobs may run at once
#   threads per job     CPU budget of one job (processes x threads inside it)
#   memory admission    a job only starts if its estimated memory still fits
#
# Tunables (all optional; unset or empty means "derive it"):
#   METHOD_MAX_CONCURRENT_JOBS, METHOD_THREADS_PER_JOB, METHOD_JOB_MEMORY_MB,
#   METHOD_BASELINE_MEMORY_MB, METHOD_MEMORY_HEADROOM_PERCENT (default 10),
#   METHOD_CPU_LIMIT (can only lower the CPU count)
#
# Shared verbatim by the R method services (dowser, brepphylo);
# services/gctree/resource_limits.py is the Python counterpart and the two
# must make the same decisions.

# Per-method memory estimates in MiB: idle service, one job. Measured on the
# regression dataset; a job on a much larger dataset needs more.
RL_MEMORY_DEFAULTS_MB <- list(
  gctree = c(160, 256),
  clonaltree = c(60, 192),
  dowser = c(850, 950),
  brepphylo = c(850, 950)
)
RL_FALLBACK_MEMORY_MB <- c(256, 512)
RL_DEFAULT_HEADROOM_PERCENT <- 10
RL_V1_UNLIMITED <- 2^60

RL_ACCEPT <- "ACCEPT"
RL_BUSY <- "METHOD_BUSY"                    # retry later: capacity will free up
RL_INSUFFICIENT <- "INSUFFICIENT_CAPACITY"  # retrying cannot help: configuration

.rl_root <- function() {
  root <- Sys.getenv("PHYLO_CGROUP_ROOT", "")
  if (nzchar(root)) root else "/sys/fs/cgroup"
}

.rl_read <- function(path) {
  if (!file.exists(path)) return(NULL)
  out <- tryCatch(suppressWarnings(readLines(path, warn = FALSE)), error = function(e) NULL)
  if (is.null(out)) return(NULL)
  trimws(paste(out, collapse = "\n"))
}

.rl_pos_num <- function(raw) {
  if (is.null(raw) || length(raw) == 0) return(NA_real_)
  v <- suppressWarnings(as.numeric(trimws(as.character(raw[[1]]))))
  if (is.na(v) || !is.finite(v) || v <= 0) NA_real_ else v
}

.rl_pos_int <- function(raw) {
  v <- .rl_pos_num(raw)
  if (is.na(v) || v < 1) NA_integer_ else as.integer(floor(v))
}

.rl_env <- function(name) {
  v <- Sys.getenv(name, "")
  if (nzchar(v)) v else NULL
}

# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------
rl_cgroup_cpu_limit <- function() {
  root <- .rl_root()
  v2 <- .rl_read(file.path(root, "cpu.max"))
  if (!is.null(v2) && nzchar(v2)) {
    parts <- strsplit(v2, "[[:space:]]+")[[1]]
    if (length(parts) == 2 && parts[1] != "max") {
      quota <- .rl_pos_num(parts[1]); period <- .rl_pos_num(parts[2])
      if (!is.na(quota) && !is.na(period)) return(quota / period)
    }
    return(NA_real_)
  }
  for (base in c(file.path(root, "cpu"), file.path(root, "cpu,cpuacct"), root)) {
    quota <- .rl_read(file.path(base, "cpu.cfs_quota_us"))
    period <- .rl_read(file.path(base, "cpu.cfs_period_us"))
    if (!is.null(quota) && !is.null(period)) {
      q <- .rl_pos_num(quota); p <- .rl_pos_num(period)
      return(if (!is.na(q) && !is.na(p)) q / p else NA_real_)
    }
  }
  NA_real_
}

# Cores this process may be scheduled on. `nproc` honours CPU affinity;
# detectCores() is the fallback and reports every core of the host.
rl_host_cpus <- function() {
  n <- tryCatch(
    suppressWarnings(as.integer(system2("nproc", stdout = TRUE, stderr = FALSE)[1])),
    error = function(e) NA_integer_
  )
  if (is.na(n) || n < 1) {
    n <- tryCatch(as.integer(parallel::detectCores(logical = TRUE)), error = function(e) NA_integer_)
  }
  if (is.na(n) || n < 1) 1L else n
}

rl_effective_cpus <- function() {
  candidates <- c(as.numeric(rl_host_cpus()), rl_cgroup_cpu_limit(), .rl_pos_num(.rl_env("METHOD_CPU_LIMIT")))
  min(candidates[!is.na(candidates)])
}

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
rl_memory_limit_bytes <- function() {
  root <- .rl_root()
  v2 <- .rl_read(file.path(root, "memory.max"))
  if (!is.null(v2)) {
    if (identical(v2, "max")) return(NA_real_)
    return(.rl_pos_num(v2))
  }
  for (base in c(file.path(root, "memory"), root)) {
    v1 <- .rl_read(file.path(base, "memory.limit_in_bytes"))
    if (!is.null(v1)) {
      limit <- .rl_pos_num(v1)
      return(if (!is.na(limit) && limit < RL_V1_UNLIMITED) limit else NA_real_)
    }
  }
  NA_real_
}

.rl_stat_value <- function(text, key) {
  if (is.null(text)) return(0)
  for (line in strsplit(text, "\n", fixed = TRUE)[[1]]) {
    parts <- strsplit(trimws(line), "[[:space:]]+")[[1]]
    if (length(parts) == 2 && identical(parts[1], key)) {
      v <- suppressWarnings(as.numeric(parts[2]))
      if (!is.na(v)) return(v)
    }
  }
  0
}

# Memory the cgroup cannot give back without killing something: current usage
# minus reclaimable file cache. NA when it cannot be read.
rl_memory_in_use_bytes <- function() {
  root <- .rl_root()
  current <- .rl_read(file.path(root, "memory.current"))
  if (!is.null(current) && grepl("^[0-9]+$", current)) {
    inactive <- .rl_stat_value(.rl_read(file.path(root, "memory.stat")), "inactive_file")
    return(max(0, as.numeric(current) - inactive))
  }
  for (base in c(file.path(root, "memory"), root)) {
    usage <- .rl_read(file.path(base, "memory.usage_in_bytes"))
    if (!is.null(usage) && grepl("^[0-9]+$", usage)) {
      inactive <- .rl_stat_value(.rl_read(file.path(base, "memory.stat")), "total_inactive_file")
      return(max(0, as.numeric(usage) - inactive))
    }
  }
  NA_real_
}

# How many processes of this container the kernel has killed for running out of
# memory; NA when the counter cannot be read. A job compares the value before
# and after to tell an out-of-memory kill from other failures.
rl_oom_kill_count <- function() {
  root <- .rl_root()
  events <- .rl_read(file.path(root, "memory.events"))
  if (!is.null(events)) return(.rl_stat_value(events, "oom_kill"))
  for (base in c(file.path(root, "memory"), root)) {
    control <- .rl_read(file.path(base, "memory.oom_control"))
    if (!is.null(control)) return(.rl_stat_value(control, "oom_kill"))
  }
  NA_real_
}

# ---------------------------------------------------------------------------
# Capacity plan
# ---------------------------------------------------------------------------
# * At most one job per whole CPU, so jobs do not fight over cores.
# * No more jobs than the memory limit can hold (baseline + N x job estimate,
#   inside the limit minus headroom). Zero when not even one job fits.
# * The CPU allowance divided by the slots is each job's thread budget, so
#   job_slots * threads_per_job never exceeds the allowance (rounded down to
#   whole cores, minimum one).
rl_plan_capacity <- function(method_id) {
  cpus <- rl_effective_cpus()
  whole_cpus <- max(1L, as.integer(floor(cpus + 1e-9)))

  defaults <- RL_MEMORY_DEFAULTS_MB[[method_id]]
  if (is.null(defaults)) defaults <- RL_FALLBACK_MEMORY_MB
  baseline <- .rl_pos_int(.rl_env("METHOD_BASELINE_MEMORY_MB"))
  if (is.na(baseline)) baseline <- as.integer(defaults[1])
  job_memory <- .rl_pos_int(.rl_env("METHOD_JOB_MEMORY_MB"))
  if (is.na(job_memory)) job_memory <- as.integer(defaults[2])
  headroom <- .rl_pos_num(.rl_env("METHOD_MEMORY_HEADROOM_PERCENT"))
  if (is.na(headroom) || headroom >= 90) headroom <- RL_DEFAULT_HEADROOM_PERCENT

  limit_bytes <- rl_memory_limit_bytes()
  limit_mb <- if (is.na(limit_bytes)) NA_integer_ else as.integer(floor(limit_bytes / (1024 * 1024)))

  configured <- .rl_pos_int(.rl_env("METHOD_MAX_CONCURRENT_JOBS"))
  if (!is.na(configured)) {
    slots <- configured; source <- "configured"
  } else {
    slots <- whole_cpus; source <- "auto"
  }
  if (!is.na(limit_mb)) {
    budget <- limit_mb * (1 - headroom / 100)
    memory_slots <- as.integer(floor((budget - baseline) / job_memory + 1e-9))
    slots <- max(0L, min(slots, memory_slots))
  }

  threads <- max(1L, whole_cpus %/% max(1L, slots))
  configured_threads <- .rl_pos_int(.rl_env("METHOD_THREADS_PER_JOB"))
  # An operator may lower the per-job budget, never raise it above the allowance.
  if (!is.na(configured_threads)) threads <- min(configured_threads, whole_cpus)

  list(
    method_id = method_id,
    cpus = round(cpus, 2),
    memory_limit_mb = limit_mb,
    baseline_memory_mb = baseline,
    job_memory_mb = job_memory,
    headroom_percent = headroom,
    job_slots = as.integer(slots),
    threads_per_job = as.integer(threads),
    slots_source = source
  )
}

rl_memory_budget_mb <- function(capacity) {
  if (is.na(capacity$memory_limit_mb)) return(NA_real_)
  capacity$memory_limit_mb * (1 - capacity$headroom_percent / 100)
}

# ---------------------------------------------------------------------------
# Admission
# ---------------------------------------------------------------------------
rl_admit <- function(capacity, running_jobs, in_use_bytes) {
  if (capacity$job_slots < 1) {
    return(list(code = RL_INSUFFICIENT, retry_after_seconds = 0L, reason = sprintf(
      paste0(
        "The %s service has a memory limit of %s MiB, which cannot hold the service (%d MiB) ",
        "plus one job (%d MiB) with %g%% headroom. Raise the memory budget or lower METHOD_JOB_MEMORY_MB."
      ),
      capacity$method_id, format(capacity$memory_limit_mb), capacity$baseline_memory_mb,
      capacity$job_memory_mb, capacity$headroom_percent
    )))
  }
  if (running_jobs >= capacity$job_slots) {
    return(list(code = RL_BUSY, retry_after_seconds = 10L, reason = sprintf(
      "All %d %s job slot(s) are in use.", capacity$job_slots, capacity$method_id
    )))
  }
  budget_mb <- rl_memory_budget_mb(capacity)
  if (!is.na(budget_mb)) {
    # Memory already spoken for. A job that has just started has not allocated
    # its memory yet, so what is measured lags behind what will be used: every
    # running job counts for at least its estimate. Measured usage wins when it
    # is higher (jobs that turned out bigger than estimated).
    reserved_mb <- capacity$baseline_memory_mb + running_jobs * capacity$job_memory_mb
    measured_mb <- if (is.na(in_use_bytes)) 0 else in_use_bytes / (1024 * 1024)
    committed_mb <- max(reserved_mb, measured_mb)
    if (committed_mb + capacity$job_memory_mb > budget_mb) {
      return(list(code = RL_BUSY, retry_after_seconds = 15L, reason = sprintf(
        "Not enough free memory for another %s job: %.0f MiB in use or reserved, a job needs about %d MiB, budget %.0f MiB.",
        capacity$method_id, committed_mb, capacity$job_memory_mb, budget_mb
      )))
    }
  }
  list(code = RL_ACCEPT, retry_after_seconds = 0L, reason = "")
}

# ---------------------------------------------------------------------------
# Thread control inside a job
# ---------------------------------------------------------------------------
# Clamp a user-requested worker/thread count to `allowed`. Anything that is not
# a positive whole number counts as a request for 1.
rl_clamp_parallelism <- function(requested, allowed) {
  wanted <- suppressWarnings(as.integer(requested[1]))
  if (length(wanted) == 0 || is.na(wanted) || wanted < 1L) wanted <- 1L
  allowed <- max(1L, as.integer(allowed))
  list(effective = min(wanted, allowed), requested = wanted, reduced = wanted > allowed)
}

# Environment for a job's process tree that keeps it inside `threads` CPUs.
# `threads` is the job's whole CPU budget. OMP_THREAD_LIMIT is a hard ceiling
# even for programs that ask for a number explicitly (IgPhyML --threads).
# R jobs already parallelise with forked processes (mclapply), so BLAS/OpenMP
# stay single-threaded by default: processes x BLAS threads would multiply.
rl_thread_environment <- function(threads, blas_threads = 1L) {
  threads <- max(1L, as.integer(threads))
  blas <- max(1L, min(threads, as.integer(blas_threads)))
  c(
    PHYLO_JOB_THREADS = threads,
    OMP_NUM_THREADS = blas,
    OMP_THREAD_LIMIT = threads,
    OPENBLAS_NUM_THREADS = blas,
    GOTO_NUM_THREADS = blas,
    MKL_NUM_THREADS = blas,
    BLIS_NUM_THREADS = blas,
    FLEXIBLAS_NUM_THREADS = blas,
    RCPP_PARALLEL_NUM_THREADS = threads,
    MC_CORES = threads
  )
}

# CPU budget of the current job: what the job manager handed down, else the
# plan for this container (direct /run calls, local development).
rl_job_threads <- function(method_id = "") {
  handed <- .rl_pos_int(.rl_env("PHYLO_JOB_THREADS"))
  if (!is.na(handed)) return(handed)
  rl_plan_capacity(method_id)$threads_per_job
}
