# Runs in either R method image; covers disk lifecycle and object manifest.
source('/srv/job_manager.R')
source('/srv/artifact_manifest.R')
testthat::test_that('job state persists, terminal cancellation is idempotent, missing jobs are absent', {
  Sys.setenv(METHOD_JOBS_DIR = tempfile('phylo-r-tests-'))
  mgr <- job_manager_new('test')
  testthat::expect_null(job_manager_status(mgr, 'missing'))
  testthat::expect_equal(job_manager_result(mgr, 'missing')$code, 404)
  sd <- .job_state_dir(mgr, 'job')
  dir.create(sd)
  .job_write_json_atomic(file.path(sd, 'status.json'), list(status = 'RUNNING'))
  testthat::expect_equal(job_manager_result(mgr, 'job')$code, 409)
  .job_write_json_atomic(file.path(sd, 'result.json'), list(ok = TRUE, trees = list('(a,b);')))
  .job_write_json_atomic(file.path(sd, 'status.json'), list(status = 'DONE'))
  testthat::expect_equal(job_manager_result(mgr, 'job')$code, 200)
  testthat::expect_equal(job_manager_cancel(mgr, 'job')$status, 'DONE')
  writeLines('broken', file.path(sd, 'status.json'))
  testthat::expect_null(job_manager_status(mgr, 'job'))
  unlink(mgr$root, recursive = TRUE)
})
testthat::test_that('manifest names are sanitized and deprecated binary fields are removed', {
  path <- tempfile(fileext = '.nwk')
  writeLines('(a,b);', path)
  upload_artifact <- function(local_path, run_id, job_id, filename, content_type) {
    list(object_key = paste(run_id, job_id, filename, sep = '/'), size_bytes = file.info(local_path)$size,
         checksum_sha256 = digest::digest(file = local_path, algo = 'sha256'))
  }
  # Override only network upload; test actual metadata conversion and file checks.
  target <- environment(materialize_artifacts)
  original_upload <- get('upload_artifact', envir = target)
  assign('upload_artifact', upload_artifact, envir = target)
  withr::defer(assign('upload_artifact', original_upload, envir = target))
  result <- materialize_artifacts(list(ok = TRUE, figures = 'old', artifact_zip_b64 = 'old',
    artifact_files = list(list(path = path, filename = '../unsafe name.nwk', kind = 'newick', tree_index = 0))), 'run', 'job')
  testthat::expect_equal(result$manifest_version, 1)
  testthat::expect_length(result$artifacts, 1)
  testthat::expect_equal(result$artifacts[[1]]$filename, 'unsafe_name.nwk')
  testthat::expect_equal(result$artifacts[[1]]$size_bytes, 7)
  testthat::expect_equal(nchar(result$artifacts[[1]]$checksum_sha256), 64)
  testthat::expect_null(result$artifact_files)
  testthat::expect_null(result$figures)
  testthat::expect_null(result$artifact_zip_b64)
  testthat::expect_error(materialize_artifacts(list(), '', 'job'), 'required')
  unlink(path)
})
testthat::test_that('real child job completes and a running process group can be cancelled', {
  Sys.setenv(METHOD_JOBS_DIR = tempfile('phylo-r-process-tests-'))
  runner <- tempfile(fileext = '.R')
  writeLines(c(
    'library(jsonlite)',
    'args <- commandArgs(TRUE); sd <- args[match("--state-dir", args) + 1]',
    'request <- fromJSON(file.path(sd, "request.json"))',
    'write_state <- function(x) { p <- file.path(sd,"status.json"); writeLines(toJSON(x,auto_unbox=TRUE),paste0(p,".tmp")); file.rename(paste0(p,".tmp"),p) }',
    'child <- if (isTRUE(request$params$slow)) as.integer(system("sleep 60 >/dev/null 2>&1 & echo $!", intern=TRUE)) else NULL',
    'write_state(list(status="RUNNING", pid=Sys.getpid(), child_pid=child))',
    'if (isTRUE(request$params$slow)) Sys.sleep(60) else Sys.sleep(0.1)',
    'writeLines(toJSON(list(ok=TRUE,trees=list("(a,b);")),auto_unbox=TRUE),file.path(sd,"result.json"))',
    'write_state(list(status="DONE", pid=Sys.getpid()))'
  ), runner)
  target <- environment(job_manager_submit)
  original <- get('.job_find_runner', envir=target)
  assign('.job_find_runner', function() runner, envir=target)
  withr::defer(assign('.job_find_runner', original, envir=target))
  mgr <- job_manager_new('test')
  wait_state <- function(id, wanted) {
    deadline <- Sys.time() + 10
    repeat {
      state <- job_manager_status(mgr, id)
      if (!is.null(state) && state$status == wanted) return(state)
      if (Sys.time() > deadline) stop('job did not reach ', wanted)
      Sys.sleep(0.05)
    }
  }
  id <- job_manager_submit(mgr, NULL, list(slow=FALSE), 'run')
  wait_state(id, 'DONE')
  result <- job_manager_result(mgr, id)
  testthat::expect_equal(result$code, 200)
  testthat::expect_equal(jsonlite::fromJSON(result$path)$trees, '(a,b);')
  id <- job_manager_submit(mgr, NULL, list(slow=TRUE), 'run')
  state <- wait_state(id, 'RUNNING')
  # Ensure failed assertions still terminate our own test children.
  withr::defer(system(sprintf('kill -KILL -- -%d 2>/dev/null', state$pid)))
  testthat::expect_equal(job_manager_cancel(mgr, id)$status, 'CANCELLED')
  testthat::expect_equal(job_manager_cancel(mgr, id)$status, 'CANCELLED')
  alive <- function(pid) {
    path <- sprintf('/proc/%d/stat', pid)
    file.exists(path) && !grepl('\\) Z ', readLines(path, warn=FALSE)[1])
  }
  deadline <- Sys.time() + 8
  while ((alive(state$pid) || alive(state$child_pid)) && Sys.time() < deadline) Sys.sleep(0.1)
  testthat::expect_false(alive(state$pid))
  testthat::expect_false(alive(state$child_pid))
  unlink(mgr$root, recursive=TRUE)
  unlink(runner)
})

# ---------------------------------------------------------------------------
# Resource awareness (resource_limits.R) and admission control. The R services
# must make the same decisions as services/gctree/resource_limits.py.
# ---------------------------------------------------------------------------
MIB <- 1024 * 1024
rl_tunables <- c("METHOD_MAX_CONCURRENT_JOBS", "METHOD_THREADS_PER_JOB", "METHOD_JOB_MEMORY_MB",
                 "METHOD_BASELINE_MEMORY_MB", "METHOD_MEMORY_HEADROOM_PERCENT", "METHOD_CPU_LIMIT",
                 "PHYLO_JOB_THREADS")
fake_cgroup <- function(cpu = NULL, memory_mb = NULL, in_use_mb = NULL, inactive_mb = 0, ...) {
  root <- tempfile("phylo-cgroup-")
  dir.create(root)
  if (!is.null(cpu)) writeLines(cpu, file.path(root, "cpu.max"))
  if (!is.null(memory_mb)) writeLines(format(memory_mb * MIB, scientific = FALSE), file.path(root, "memory.max"))
  if (!is.null(in_use_mb)) {
    writeLines(format(in_use_mb * MIB, scientific = FALSE), file.path(root, "memory.current"))
    writeLines(c("anon 1", paste("inactive_file", format(inactive_mb * MIB, scientific = FALSE))), file.path(root, "memory.stat"))
  }
  do.call(Sys.unsetenv, list(rl_tunables))
  Sys.setenv(PHYLO_CGROUP_ROOT = root)
  extra <- list(...)
  if (length(extra)) do.call(Sys.setenv, extra)
  root
}
with_host_cpus <- function(n, code) {
  target <- environment(rl_effective_cpus)
  original <- get("rl_host_cpus", envir = target)
  assign("rl_host_cpus", function() n, envir = target)
  on.exit(assign("rl_host_cpus", original, envir = target), add = TRUE)
  force(code)
}

testthat::test_that('effective limits come from the cgroup, not from the host', {
  with_host_cpus(64L, {
    fake_cgroup(cpu = "150000 100000", memory_mb = 800, in_use_mb = 500, inactive_mb = 120)
    testthat::expect_equal(rl_cgroup_cpu_limit(), 1.5)
    testthat::expect_equal(rl_effective_cpus(), 1.5)
    testthat::expect_equal(rl_memory_limit_bytes(), 800 * MIB)
    testthat::expect_equal(rl_memory_in_use_bytes(), 380 * MIB)   # reclaimable cache excluded
    Sys.setenv(METHOD_CPU_LIMIT = "1");  testthat::expect_equal(rl_effective_cpus(), 1)
    Sys.setenv(METHOD_CPU_LIMIT = "32"); testthat::expect_equal(rl_effective_cpus(), 1.5)  # cannot raise
    fake_cgroup(cpu = "max 100000")
    testthat::expect_true(is.na(rl_cgroup_cpu_limit()))
    testthat::expect_equal(rl_effective_cpus(), 64)
    fake_cgroup()
    testthat::expect_true(is.na(rl_memory_limit_bytes()))
    testthat::expect_true(is.na(rl_memory_in_use_bytes()))
  })
  with_host_cpus(1L, { fake_cgroup(cpu = "400000 100000"); testthat::expect_equal(rl_effective_cpus(), 1) })
})

testthat::test_that('cgroup v1 files are understood', {
  root <- fake_cgroup()
  dir.create(file.path(root, "cpu")); dir.create(file.path(root, "memory"))
  writeLines("250000", file.path(root, "cpu", "cpu.cfs_quota_us"))
  writeLines("100000", file.path(root, "cpu", "cpu.cfs_period_us"))
  writeLines(format(512 * MIB, scientific = FALSE), file.path(root, "memory", "memory.limit_in_bytes"))
  writeLines(format(300 * MIB, scientific = FALSE), file.path(root, "memory", "memory.usage_in_bytes"))
  writeLines(paste("total_inactive_file", format(100 * MIB, scientific = FALSE)), file.path(root, "memory", "memory.stat"))
  testthat::expect_equal(rl_cgroup_cpu_limit(), 2.5)
  testthat::expect_equal(rl_memory_limit_bytes(), 512 * MIB)
  testthat::expect_equal(rl_memory_in_use_bytes(), 200 * MIB)
  writeLines("-1", file.path(root, "cpu", "cpu.cfs_quota_us"))
  testthat::expect_true(is.na(rl_cgroup_cpu_limit()))
  writeLines("9223372036854771712", file.path(root, "memory", "memory.limit_in_bytes"))
  testthat::expect_true(is.na(rl_memory_limit_bytes()))
})

testthat::test_that('capacity plan matches the Python services case by case', {
  cases <- list(
    list("dowser", "60000 100000", 2448, list(), 1L, 1L),
    list("brepphylo", "60000 100000", 2448, list(), 1L, 1L),
    list("dowser", "400000 100000", 2448, list(), 1L, 4L),
    list("dowser", "400000 100000", 8192, list(), 4L, 1L),
    list("dowser", "400000 100000", 8192, list(METHOD_MAX_CONCURRENT_JOBS = "1"), 1L, 4L),
    list("dowser", "400000 100000", 8192, list(METHOD_MAX_CONCURRENT_JOBS = "2"), 2L, 2L),
    list("dowser", "400000 100000", 2448, list(METHOD_MAX_CONCURRENT_JOBS = "3"), 1L, 4L),
    list("dowser", "400000 100000", 8192, list(METHOD_MAX_CONCURRENT_JOBS = "1", METHOD_THREADS_PER_JOB = "2"), 1L, 2L),
    list("dowser", "400000 100000", 8192, list(METHOD_MAX_CONCURRENT_JOBS = "1", METHOD_THREADS_PER_JOB = "64"), 1L, 4L),
    list("gctree", "100000 100000", 4096, list(METHOD_MAX_CONCURRENT_JOBS = "3"), 3L, 1L),
    list("gctree", "400000 100000", 2048, list(METHOD_JOB_MEMORY_MB = "900"), 1L, 4L),
    list("dowser", "400000 100000", 1024, list(), 0L, 4L)
  )
  with_host_cpus(64L, for (case in cases) {
    do.call(fake_cgroup, c(list(cpu = case[[2]], memory_mb = case[[3]]), case[[4]]))
    plan <- rl_plan_capacity(case[[1]])
    testthat::expect_equal(c(plan$job_slots, plan$threads_per_job), c(case[[5]], case[[6]]),
                           info = paste(case[[1]], case[[2]], case[[3]], paste(names(case[[4]]), case[[4]], collapse = " ")))
    testthat::expect_equal(plan$memory_limit_mb, case[[3]])
  })
  with_host_cpus(64L, {
    fake_cgroup(cpu = "200000 100000", memory_mb = 4096, METHOD_MAX_CONCURRENT_JOBS = "many",
                METHOD_THREADS_PER_JOB = "-3", METHOD_MEMORY_HEADROOM_PERCENT = "150")
    plan <- rl_plan_capacity("gctree")
    testthat::expect_equal(c(plan$job_slots, plan$threads_per_job, plan$job_memory_mb, plan$headroom_percent), c(2, 1, 256, 10))
  })
  with_host_cpus(8L, { fake_cgroup(); plan <- rl_plan_capacity("unknown-method")
    testthat::expect_equal(c(plan$job_slots, plan$baseline_memory_mb, plan$job_memory_mb), c(8, 256, 512))
    testthat::expect_true(is.na(plan$memory_limit_mb)); testthat::expect_true(is.na(rl_memory_budget_mb(plan))) })
})

testthat::test_that('admission: slots, memory, and impossible configurations', {
  with_host_cpus(64L, {
    fake_cgroup(cpu = "400000 100000", memory_mb = 8192)
    plan <- rl_plan_capacity("dowser")
    testthat::expect_equal(rl_admit(plan, 0L, 850 * MIB)$code, RL_ACCEPT)
    full <- rl_admit(plan, 4L, 1000 * MIB)
    testthat::expect_equal(full$code, RL_BUSY); testthat::expect_match(full$reason, "4 dowser job slot")
    budget_mb <- 8192 * 0.9
    testthat::expect_equal(rl_admit(plan, 1L, (budget_mb - 950 - 1) * MIB)$code, RL_ACCEPT)
    short <- rl_admit(plan, 1L, (budget_mb - 950 + 1) * MIB)
    testthat::expect_equal(short$code, RL_BUSY); testthat::expect_match(short$reason, "Not enough free memory")
    testthat::expect_equal(rl_admit(plan, 0L, NA_real_)$code, RL_ACCEPT)   # unreadable memory: slots only
    fake_cgroup(cpu = "400000 100000", memory_mb = 1024)
    never <- rl_admit(rl_plan_capacity("dowser"), 0L, 0)
    testthat::expect_equal(never$code, RL_INSUFFICIENT); testthat::expect_match(never$reason, "1024 MiB")
    testthat::expect_equal(never$retry_after_seconds, 0L)
  })
})

testthat::test_that('requested parallelism is clamped and thread pools are capped', {
  expect_clamp <- function(requested, allowed, effective, reduced) {
    out <- rl_clamp_parallelism(requested, allowed)
    testthat::expect_equal(c(out$effective, out$reduced), c(effective, reduced), info = paste(requested, allowed))
  }
  expect_clamp(1, 4, 1, FALSE); expect_clamp(4, 4, 4, FALSE); expect_clamp(64, 2, 2, TRUE)
  expect_clamp(1e9, 1, 1, TRUE); expect_clamp(0, 4, 1, FALSE); expect_clamp(-5, 4, 1, FALSE)
  expect_clamp("8", 2, 2, TRUE); expect_clamp("abc", 4, 1, FALSE); expect_clamp(NA, 4, 1, FALSE)
  expect_clamp(2, 0, 1, TRUE)
  testthat::expect_equal(rl_clamp_parallelism(64, 2)$requested, 64L)

  env <- rl_thread_environment(3L)
  testthat::expect_equal(unname(env[c("PHYLO_JOB_THREADS", "OMP_THREAD_LIMIT", "MC_CORES", "RCPP_PARALLEL_NUM_THREADS")]), rep(3L, 4))
  # R jobs parallelise with forked processes, so BLAS/OpenMP stay single-threaded.
  testthat::expect_equal(unname(env[c("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "FLEXIBLAS_NUM_THREADS")]), rep(1L, 3))
  testthat::expect_equal(unname(rl_thread_environment(0L)["PHYLO_JOB_THREADS"]), 1L)

  with_host_cpus(64L, {
    fake_cgroup(cpu = "400000 100000", memory_mb = 8192, METHOD_MAX_CONCURRENT_JOBS = "1")
    testthat::expect_equal(rl_job_threads("dowser"), 4L)                 # the container's plan
    Sys.setenv(PHYLO_JOB_THREADS = "2"); testthat::expect_equal(rl_job_threads("dowser"), 2L)  # handed down
    Sys.unsetenv("PHYLO_JOB_THREADS")
  })
})

testthat::test_that('a full service refuses the next job, then accepts it once the slot is free', {
  Sys.setenv(METHOD_JOBS_DIR = tempfile('phylo-r-admission-tests-'))
  runner <- tempfile(fileext = '.R')
  writeLines(c(
    'library(jsonlite)',
    'args <- commandArgs(TRUE); sd <- args[match("--state-dir", args) + 1]',
    'request <- fromJSON(file.path(sd, "request.json"))',
    'write_state <- function(x) { p <- file.path(sd,"status.json"); writeLines(toJSON(x,auto_unbox=TRUE),paste0(p,".tmp")); file.rename(paste0(p,".tmp"),p) }',
    'write_state(list(status="RUNNING", pid=Sys.getpid()))',
    'env <- as.list(Sys.getenv(c("PHYLO_JOB_THREADS","OMP_NUM_THREADS","OMP_THREAD_LIMIT","MC_CORES")))',
    'if (isTRUE(request$params$slow)) Sys.sleep(60) else Sys.sleep(0.1)',
    'writeLines(toJSON(list(ok=TRUE,env=env),auto_unbox=TRUE),file.path(sd,"result.json"))',
    'write_state(list(status="DONE", pid=Sys.getpid()))'
  ), runner)
  target <- environment(job_manager_submit)
  original_finder <- get('.job_find_runner', envir = target)
  assign('.job_find_runner', function() runner, envir = target)
  withr::defer(assign('.job_find_runner', original_finder, envir = target))
  wait_until <- function(pred, seconds = 60) { deadline <- Sys.time() + seconds; while (Sys.time() < deadline) { if (isTRUE(pred())) return(TRUE); Sys.sleep(0.2) }; FALSE }

  with_host_cpus(64L, {
    fake_cgroup(cpu = "200000 100000", memory_mb = 8192, in_use_mb = 100, METHOD_MAX_CONCURRENT_JOBS = "1")
    mgr <- job_manager_new('test')
    testthat::expect_equal(c(mgr$capacity$job_slots, mgr$capacity$threads_per_job), c(1L, 2L))
    report <- job_manager_capacity(mgr)
    testthat::expect_true(report$accepting); testthat::expect_equal(report$free_slots, 1L)

    first <- job_manager_submit(mgr, NULL, list(slow = TRUE), 'run-a')
    testthat::expect_true(is.character(first))
    refused <- job_manager_submit(mgr, NULL, list(slow = TRUE), 'run-b')
    testthat::expect_true(isTRUE(refused$rejected))
    testthat::expect_equal(refused$admission$code, RL_BUSY)
    testthat::expect_equal(length(list.files(mgr$root)), 1L)                # nothing created for it
    busy <- job_manager_capacity(mgr)
    testthat::expect_equal(c(busy$running_jobs, busy$free_slots), c(1L, 0L)); testthat::expect_false(busy$accepting)

    testthat::expect_true(wait_until(function() !is.null(job_manager_status(mgr, first)$pid)))
    testthat::expect_equal(job_manager_cancel(mgr, first)$status, 'CANCELLED')
    testthat::expect_equal(job_manager_running(mgr), 0L)

    second <- job_manager_submit(mgr, NULL, list(slow = FALSE), 'run-b')
    testthat::expect_true(is.character(second))
    testthat::expect_true(wait_until(function() identical(as.character(job_manager_status(mgr, second)$status), 'DONE')))
    result <- jsonlite::fromJSON(job_manager_result(mgr, second)$path)
    # The job's process tree received its CPU budget.
    testthat::expect_equal(unlist(result$env[c("PHYLO_JOB_THREADS", "OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "MC_CORES")], use.names = FALSE),
                           c("2", "1", "2", "2"))
    testthat::expect_true(wait_until(function() job_manager_running(mgr) == 0L))

    # Memory: a free slot is not enough when the job does not fit.
    fake_cgroup(cpu = "200000 100000", memory_mb = 2448, in_use_mb = 1500)
    mgr2 <- job_manager_new('dowser')
    short <- job_manager_submit(mgr2, NULL, list(), 'run-m')
    testthat::expect_true(isTRUE(short$rejected)); testthat::expect_match(short$admission$reason, "Not enough free memory")
    # And a container that can never hold a job says so instead of asking to wait.
    fake_cgroup(cpu = "200000 100000", memory_mb = 1024, in_use_mb = 100)
    never <- job_manager_submit(job_manager_new('dowser'), NULL, list(), 'run-x')
    testthat::expect_equal(never$admission$code, RL_INSUFFICIENT)
    unlink(mgr$root, recursive = TRUE)
  })
  Sys.unsetenv("PHYLO_CGROUP_ROOT"); do.call(Sys.unsetenv, list(rl_tunables))
})

testthat::test_that('a zombie or vanished process is not counted as a running job', {
  testthat::expect_false(.job_pid_running(NA)); testthat::expect_false(.job_pid_running(-1L))
  testthat::expect_false(.job_pid_running(2147483646L))
  testthat::expect_true(.job_pid_running(Sys.getpid()))
})

if (exists("parse_dowser_params", mode = "function")) {
  testthat::test_that('Dowser reduces a user-requested nproc to the CPU budget of the job', {
    do.call(Sys.unsetenv, list(rl_tunables))
    parse <- function(nproc_json) parse_dowser_params(sprintf('{"analysis_mode":"tree_only","tree_build":"pratchet"%s}', nproc_json))
    Sys.setenv(PHYLO_JOB_THREADS = "2")
    p <- parse(',"nproc":64')
    testthat::expect_equal(c(p$nproc, p$nproc_requested), c(2L, 64L)); testthat::expect_true(p$nproc_reduced)
    p <- parse(',"nproc":2');  testthat::expect_equal(p$nproc, 2L); testthat::expect_false(p$nproc_reduced)
    p <- parse(',"nproc":1');  testthat::expect_equal(p$nproc, 1L); testthat::expect_false(p$nproc_reduced)
    p <- parse('');            testthat::expect_equal(c(p$nproc, p$nproc_requested), c(1L, 1L))
    p <- parse(',"nproc":0');  testthat::expect_equal(p$nproc, 1L)
    p <- parse(',"nproc":-8'); testthat::expect_equal(p$nproc, 1L)
    Sys.setenv(PHYLO_JOB_THREADS = "1")
    p <- parse(',"nproc":1000000'); testthat::expect_equal(p$nproc, 1L); testthat::expect_true(p$nproc_reduced)
    # No job manager (direct call): the container's own plan is the limit.
    Sys.unsetenv("PHYLO_JOB_THREADS")
    with_host_cpus(64L, {
      fake_cgroup(cpu = "300000 100000", memory_mb = 8192, METHOD_MAX_CONCURRENT_JOBS = "1")
      p <- parse(',"nproc":64'); testthat::expect_equal(p$nproc, 3L)
    })
    Sys.unsetenv("PHYLO_CGROUP_ROOT"); do.call(Sys.unsetenv, list(rl_tunables))
  })
}

# ---------------------------------------------------------------------------
# No job stays "running" for ever: time limit, lost process, restart, and a
# result that could not be stored is not a finished result.
# ---------------------------------------------------------------------------
recovery_runner <- function() {
  runner <- tempfile(fileext = '.R')
  writeLines(c(
    'library(jsonlite)',
    'args <- commandArgs(TRUE); sd <- args[match("--state-dir", args) + 1]',
    'request <- fromJSON(file.path(sd, "request.json"))',
    'mode <- request$params$mode',
    'write_state <- function(x) { p <- file.path(sd,"status.json"); writeLines(toJSON(x,auto_unbox=TRUE),paste0(p,".tmp")); file.rename(paste0(p,".tmp"),p) }',
    'cat("step 1 done\\nstep 2 started\\n")',
    'scratch <- Sys.getenv("TMPDIR"); if (nzchar(scratch)) writeLines("intermediate", file.path(scratch, "scratch.dat"))',
    'child <- if (identical(mode, "slow")) as.integer(system("sleep 120 >/dev/null 2>&1 & echo $!", intern=TRUE)) else NULL',
    'write_state(list(status="RUNNING", pid=Sys.getpid(), child_pid=child,',
    '                 job_child=Sys.getenv("PHYLO_JOB_CHILD"), oom_baseline=Sys.getenv("PHYLO_JOB_OOM_BASELINE"),',
    '                 tmpdir=scratch, r_tempdir=tempdir()))',
    'if (identical(mode, "slow")) Sys.sleep(120)',
    'if (identical(mode, "crash")) quit(status = 3)',
    'if (identical(mode, "oom")) {',
    '  writeLines(c("oom 1", "oom_kill 1"), file.path(Sys.getenv("PHYLO_CGROUP_ROOT"), "memory.events"))',
    '  tools::pskill(Sys.getpid(), tools::SIGKILL)',
    '  Sys.sleep(5)',
    '}',
    'Sys.sleep(0.2)',
    'writeLines(toJSON(list(ok=TRUE,trees=list("(a,b);")),auto_unbox=TRUE),file.path(sd,"result.json"))',
    'write_state(list(status="DONE", pid=Sys.getpid()))'
  ), runner)
  runner
}
with_recovery_runner <- function(code) {
  runner <- recovery_runner()
  target <- environment(job_manager_submit)
  original <- get('.job_find_runner', envir = target)
  assign('.job_find_runner', function() runner, envir = target)
  on.exit({ assign('.job_find_runner', original, envir = target); unlink(runner) }, add = TRUE)
  force(code)
}
proc_alive <- function(pid) {
  path <- sprintf('/proc/%d/stat', as.integer(pid))
  file.exists(path) && !grepl('\\) Z ', readLines(path, warn = FALSE)[1])
}
wait_for <- function(pred, seconds = 40) {
  deadline <- Sys.time() + seconds
  while (Sys.time() < deadline) { if (isTRUE(pred())) return(TRUE); Sys.sleep(0.2) }
  FALSE
}
wait_status <- function(mgr, id, wanted, seconds = 40) {
  ok <- wait_for(function() identical(.job_status_of(job_manager_status(mgr, id)), wanted), seconds)
  if (!ok) stop('job did not reach ', wanted, '; last status: ', .job_status_of(job_manager_status(mgr, id)))
  job_manager_status(mgr, id)
}
one_slot_manager <- function(dir_prefix, ...) {
  Sys.setenv(METHOD_JOBS_DIR = tempfile(dir_prefix))
  root <- fake_cgroup(cpu = "100000 100000", memory_mb = 8192, in_use_mb = 100, ...)
  list(mgr = job_manager_new('test'), cgroup = root)
}
finish_recovery_test <- function(mgr) {
  unlink(mgr$root, recursive = TRUE)
  Sys.unsetenv("PHYLO_CGROUP_ROOT"); Sys.unsetenv("METHOD_JOB_TIMEOUT_SECONDS")
  do.call(Sys.unsetenv, list(rl_tunables))
}

testthat::test_that('helpers: process group, memory-kill counter, durations', {
  testthat::expect_true(is.na(.job_pgid(NA))); testthat::expect_true(is.na(.job_pgid(2147483646L)))
  pg <- .job_pgid(Sys.getpid())
  testthat::expect_true(is.integer(pg) && !is.na(pg) && pg >= 1L)

  v2 <- fake_cgroup(memory_mb = 512)
  testthat::expect_true(is.na(rl_oom_kill_count()))                       # no counter file: unknown
  writeLines(c("low 0", "high 0", "max 12", "oom 3", "oom_kill 2"), file.path(v2, "memory.events"))
  testthat::expect_equal(rl_oom_kill_count(), 2)
  v1 <- tempfile("phylo-cgroup-v1-"); dir.create(file.path(v1, "memory"), recursive = TRUE)
  writeLines(c("oom_kill_disable 0", "under_oom 0", "oom_kill 5"), file.path(v1, "memory", "memory.oom_control"))
  Sys.setenv(PHYLO_CGROUP_ROOT = v1)
  testthat::expect_equal(rl_oom_kill_count(), 5)
  Sys.unsetenv("PHYLO_CGROUP_ROOT")

  testthat::expect_equal(.job_describe_duration(86400), "24 hours")
  testthat::expect_equal(.job_describe_duration(5400), "90 minutes")
  testthat::expect_equal(.job_describe_duration(9000), "2.5 hours")
  testthat::expect_equal(.job_describe_duration(1), "1 second")
  Sys.setenv(METHOD_JOB_TIMEOUT_SECONDS = "900"); testthat::expect_equal(.job_default_timeout_seconds(), 900)
  Sys.setenv(METHOD_JOB_TIMEOUT_SECONDS = "junk"); testthat::expect_equal(.job_default_timeout_seconds(), 0)
  Sys.unsetenv("METHOD_JOB_TIMEOUT_SECONDS"); testthat::expect_equal(.job_default_timeout_seconds(), 0)
})

testthat::test_that('a job past its time limit is stopped with its tools and reported as timeout', {
  with_recovery_runner({
    env <- one_slot_manager('phylo-r-timeout-'); mgr <- env$mgr
    id <- job_manager_submit(mgr, NULL, list(mode = "slow"), 'run-slow', timeout_seconds = 3)
    testthat::expect_true(is.character(id))
    meta <- .job_meta(mgr, id)
    testthat::expect_equal(meta$timeout_seconds, 3); testthat::expect_equal(meta$run_id, 'run-slow')
    testthat::expect_true(wait_for(function() !is.null(job_manager_status(mgr, id)$pid)))
    running <- job_manager_status(mgr, id)
    testthat::expect_equal(running$job_child, "1")                          # marked as a job, not the service
    testthat::expect_true(proc_alive(running$pid) && proc_alive(running$child_pid))
    withr::defer(system(sprintf('kill -KILL %d %d 2>/dev/null', running$pid, running$child_pid)))

    final <- wait_status(mgr, id, 'ERROR')
    testthat::expect_equal(final$error_code, JOB_CODE_TIMEOUT)
    testthat::expect_match(final$message, "time limit of 3 seconds")
    testthat::expect_true(wait_for(function() !proc_alive(running$pid) && !proc_alive(running$child_pid), 20))
    testthat::expect_equal(job_manager_running(mgr), 0L)                    # the slot is free again
    testthat::expect_true(job_manager_capacity(mgr)$accepting)
    payload <- jsonlite::fromJSON(file.path(.job_state_dir(mgr, id), "result.json"), simplifyVector = FALSE)
    testthat::expect_false(payload$ok); testthat::expect_equal(payload$error_code, JOB_CODE_TIMEOUT)
    testthat::expect_equal(payload$manifest_version, 1L)
    tails <- Filter(function(e) identical(e$step, "method.job.log_tail"), payload$logs)
    testthat::expect_match(tails[[1]]$out, "step 2 started")                # its last output is kept
    testthat::expect_equal(job_manager_result(mgr, id)$code, 409)           # an ERROR job has no result
    finish_recovery_test(mgr)
  })
})

testthat::test_that('a job inside its time limit finishes normally, and cancel still stops the whole group', {
  with_recovery_runner({
    env <- one_slot_manager('phylo-r-timeout-ok-'); mgr <- env$mgr
    id <- job_manager_submit(mgr, NULL, list(mode = "fast"), 'run-fast', timeout_seconds = 300)
    done <- wait_status(mgr, id, 'DONE')
    testthat::expect_null(done$error_code)
    testthat::expect_true(wait_for(function() job_manager_running(mgr) == 0L))

    # Under `timeout` the job is not its own group leader: cancel must still reach its tools.
    id <- job_manager_submit(mgr, NULL, list(mode = "slow"), 'run-cancel', timeout_seconds = 300)
    testthat::expect_true(wait_for(function() !is.null(job_manager_status(mgr, id)$pid)))
    running <- job_manager_status(mgr, id)
    withr::defer(system(sprintf('kill -KILL %d %d 2>/dev/null', running$pid, running$child_pid)))
    testthat::expect_false(identical(.job_pgid(running$pid), as.integer(running$pid)))
    cancelled <- job_manager_cancel(mgr, id)
    testthat::expect_equal(cancelled$status, 'CANCELLED')
    testthat::expect_match(cancelled$log_tail, "step 2 started")
    testthat::expect_true(wait_for(function() !proc_alive(running$pid) && !proc_alive(running$child_pid), 20))
    testthat::expect_equal(job_manager_status(mgr, id)$status, 'CANCELLED') # a later status request keeps it
    finish_recovery_test(mgr)
  })
})

testthat::test_that('a job whose process dies without a result is reported as failed, out-of-memory by name', {
  with_recovery_runner({
    env <- one_slot_manager('phylo-r-lost-'); mgr <- env$mgr
    id <- job_manager_submit(mgr, NULL, list(mode = "crash"), 'run-crash')
    final <- wait_status(mgr, id, 'ERROR')
    testthat::expect_equal(final$error_code, JOB_CODE_PROCESS_LOST)
    testthat::expect_match(final$message, "ended unexpectedly")
    testthat::expect_equal(job_manager_running(mgr), 0L)
    finish_recovery_test(mgr)

    env <- one_slot_manager('phylo-r-oom-'); mgr <- env$mgr
    writeLines(c("oom 0", "oom_kill 0"), file.path(env$cgroup, "memory.events"))
    id <- job_manager_submit(mgr, NULL, list(mode = "oom"), 'run-oom')
    testthat::expect_equal(.job_meta(mgr, id)$oom_kills_at_start, 0)
    final <- wait_status(mgr, id, 'ERROR')
    testthat::expect_equal(final$error_code, JOB_CODE_OUT_OF_MEMORY)
    testthat::expect_match(final$message, "ran out of memory \\(limit 8192 MiB\\)")
    testthat::expect_equal(job_manager_capacity(mgr)$free_slots, 1L)        # and the slot is free
    finish_recovery_test(mgr)
  })
})

testthat::test_that('jobs interrupted by a service restart are closed at start-up, own jobs are left alone', {
  with_recovery_runner({
    env <- one_slot_manager('phylo-r-restart-'); mgr <- env$mgr
    for (spec in list(c('interrupted', 'RUNNING'), c('queued', 'QUEUED'), c('finished', 'DONE'),
                      c('failed', 'ERROR'), c('cancelled', 'CANCELLED'))) {
      sd <- .job_state_dir(mgr, spec[1]); dir.create(sd)
      # pid 1 is alive in every container: recovery must not trust a stale pid.
      .job_write_json_atomic(file.path(sd, 'status.json'), list(job_id = spec[1], status = spec[2], pid = 1L))
    }
    mine <- job_manager_submit(mgr, NULL, list(mode = "slow"), 'run-mine')
    testthat::expect_true(wait_for(function() !is.null(job_manager_status(mgr, mine)$pid)))

    testthat::expect_equal(job_manager_recover(mgr), 2L)
    for (id in c('interrupted', 'queued')) {
      st <- job_manager_status(mgr, id)
      testthat::expect_equal(st$status, 'ERROR'); testthat::expect_equal(st$error_code, JOB_CODE_RESTARTED)
      testthat::expect_match(st$message, "restarted"); testthat::expect_match(st$message, "submit it again")
    }
    testthat::expect_equal(job_manager_status(mgr, 'finished')$status, 'DONE')
    testthat::expect_null(job_manager_status(mgr, 'failed')$error_code)
    testthat::expect_equal(job_manager_status(mgr, 'cancelled')$status, 'CANCELLED')
    testthat::expect_equal(job_manager_status(mgr, mine)$status, 'RUNNING')  # this service's own job
    testthat::expect_equal(job_manager_recover(mgr), 0L)

    # Without start-up recovery an unknown "running" job is still not believed.
    sd <- .job_state_dir(mgr, 'old'); dir.create(sd)
    .job_write_json_atomic(file.path(sd, 'status.json'), list(job_id = 'old', status = 'RUNNING', pid = Sys.getpid()))
    testthat::expect_equal(job_manager_status(mgr, 'old')$error_code, JOB_CODE_RESTARTED)

    testthat::expect_equal(job_manager_cancel(mgr, mine)$status, 'CANCELLED')
    finish_recovery_test(mgr)
  })
})

testthat::test_that('submitting the same run again returns its running job instead of a second one', {
  with_recovery_runner({
    Sys.setenv(METHOD_JOBS_DIR = tempfile('phylo-r-idempotent-'))
    with_host_cpus(64L, {
      fake_cgroup(cpu = "400000 100000", memory_mb = 16384, in_use_mb = 100, METHOD_MAX_CONCURRENT_JOBS = "4",
                  METHOD_JOB_MEMORY_MB = "64", METHOD_BASELINE_MEMORY_MB = "64")
      mgr <- job_manager_new('test')
      first <- job_manager_submit(mgr, NULL, list(mode = "slow"), 'run-same')
      testthat::expect_identical(job_manager_submit(mgr, NULL, list(mode = "slow"), 'run-same'), first)
      testthat::expect_equal(job_manager_running(mgr), 1L)
      other <- job_manager_submit(mgr, NULL, list(mode = "slow"), 'run-other')
      testthat::expect_false(identical(other, first)); testthat::expect_equal(job_manager_running(mgr), 2L)
      for (id in c(first, other)) testthat::expect_true(wait_for(function() !is.null(job_manager_status(mgr, id)$pid)))
      job_manager_cancel(mgr, first)
      again <- job_manager_submit(mgr, NULL, list(mode = "fast"), 'run-same')  # the old job is over
      testthat::expect_false(identical(again, first))
      job_manager_cancel(mgr, other)
      wait_status(mgr, again, 'DONE')
      finish_recovery_test(mgr)
    })
  })
})

testthat::test_that('a method error reported while the time limit struck is labelled as a timeout', {
  Sys.setenv(METHOD_JOBS_DIR = tempfile('phylo-r-label-'))
  fake_cgroup(cpu = "100000 100000", memory_mb = 8192, in_use_mb = 100)
  mgr <- job_manager_new('test')
  now <- as.numeric(Sys.time())
  iso <- function(t) format(as.POSIXct(t, origin = "1970-01-01", tz = "UTC"), "%Y-%m-%dT%H:%M:%SZ")
  make <- function(id, deadline, finished, code = NULL) {
    sd <- .job_state_dir(mgr, id); dir.create(sd)
    .job_write_json_atomic(file.path(sd, 'meta.json'), list(timeout_seconds = 60, deadline_at = deadline))
    st <- list(job_id = id, status = 'ERROR', message = 'igphyml failed', finished_at = iso(finished))
    if (!is.null(code)) st$error_code <- code
    .job_write_json_atomic(file.path(sd, 'status.json'), st)
  }
  make('struck', now - 10, now - 9)
  make('earlier', now + 500, now - 9)
  make('coded', now - 10, now - 9, code = 'ARTIFACT_UPLOAD_FAILED')
  struck <- job_manager_status(mgr, 'struck')
  testthat::expect_equal(struck$error_code, JOB_CODE_TIMEOUT); testthat::expect_match(struck$message, "time limit of 60 seconds")
  earlier <- job_manager_status(mgr, 'earlier')
  testthat::expect_null(earlier$error_code); testthat::expect_equal(earlier$message, 'igphyml failed')
  testthat::expect_equal(job_manager_status(mgr, 'coded')$error_code, 'ARTIFACT_UPLOAD_FAILED')
  finish_recovery_test(mgr)
})

testthat::test_that('a file that cannot be uploaded is reported, not dropped, and fails the job', {
  good <- tempfile(fileext = '.nwk'); writeLines('(a,b);', good)
  bad <- tempfile(fileext = '.png'); writeLines('png', bad)
  target <- environment(materialize_artifacts)
  original_upload <- get('upload_artifact', envir = target)
  assign('upload_artifact', function(local_path, run_id, job_id, filename, content_type) {
    if (grepl('[.]png$', filename)) stop('connection refused')
    list(object_key = paste(run_id, job_id, filename, sep = '/'), size_bytes = 7L, checksum_sha256 = 'x')
  }, envir = target)
  withr::defer(assign('upload_artifact', original_upload, envir = target))

  result <- materialize_artifacts(list(ok = TRUE, artifact_files = list(
    list(path = good, filename = 'tree.nwk'), list(path = bad, filename = 'plot.png'))), 'run', 'job')
  testthat::expect_length(result$artifacts, 1)                              # the good one is still uploaded
  testthat::expect_length(result$artifact_upload_failures, 1)
  testthat::expect_equal(result$artifact_upload_failures[[1]]$filename, 'plot.png')
  testthat::expect_match(result$artifact_upload_failures[[1]]$error, 'connection refused')

  message <- storage_failure(result)
  testthat::expect_match(message, '1 result file\\(s\\) could not be saved'); testthat::expect_match(message, 'plot.png')
  failed <- mark_storage_failure(result, message)
  testthat::expect_false(failed$ok); testthat::expect_equal(failed$error_code, UPLOAD_FAILED_CODE)
  testthat::expect_equal(failed$error, message); testthat::expect_equal(failed$manifest_version, 1L)

  # A declared file that is not on disk is reported too; entries without a path are ignored.
  gone <- materialize_artifacts(list(ok = TRUE, artifact_files = list(
    list(path = good, filename = 'tree.nwk'), list(path = file.path(tempdir(), 'never-written.zip')), list())), 'run', 'job')
  testthat::expect_length(gone$artifacts, 1)
  testthat::expect_equal(gone$artifact_upload_failures[[1]]$filename, 'never-written.zip')
  testthat::expect_match(gone$artifact_upload_failures[[1]]$error, 'does not exist')

  clean <- materialize_artifacts(list(ok = TRUE, artifact_files = list(list(path = good, filename = 'tree.nwk'))), 'run', 'job')
  testthat::expect_null(clean$artifact_upload_failures)
  testthat::expect_null(storage_failure(clean)); testthat::expect_null(storage_failure(NULL))
  testthat::expect_match(storage_failure(clean, 'run_id + job_id are required'), 'could not be saved')
  many <- list(artifact_upload_failures = lapply(1:8, function(i) list(filename = sprintf('f%d.png', i))))
  testthat::expect_match(storage_failure(many), 'and 3 more')
  blank <- mark_storage_failure(NULL, 'x')
  testthat::expect_equal(blank$artifacts, list()); testthat::expect_false(blank$ok)
  unlink(c(good, bad))
})


# ---------------------------------------------------------------------------
# Nothing of a finished job stays on the service's disk: its scratch data goes
# when it ends, its record when the worker has collected it (or after a while),
# and its log is offered in bounded form until then.
# ---------------------------------------------------------------------------
testthat::test_that('a long log is offered with its beginning and its end, and says what was left out', {
  small <- tempfile(); writeLines(c('first line', 'last line'), small)
  whole <- job_bounded_log(small, 1024)
  testthat::expect_false(whole$truncated)
  testthat::expect_equal(rawToChar(whole$content), "first line\nlast line\n")

  big <- tempfile()
  writeLines(c('THE-BEGINNING', rep(strrep('x', 99), 2000), 'THE-END'), big)
  size <- file.info(big)$size
  cut <- job_bounded_log(big, 4096)
  text <- rawToChar(cut$content)
  testthat::expect_true(cut$truncated)
  testthat::expect_true(startsWith(text, 'THE-BEGINNING')); testthat::expect_true(endsWith(text, "THE-END\n"))
  testthat::expect_match(text, sprintf('%.0f bytes of this log were left out', size - 4096))
  testthat::expect_match(text, sprintf('it is %.0f bytes long', size))
  testthat::expect_lt(length(cut$content), 4096 + 300)                     # the limit plus the note
  exact <- job_bounded_log(big, size)
  testthat::expect_false(exact$truncated); testthat::expect_equal(length(exact$content), size)

  missing <- job_bounded_log(file.path(tempdir(), 'no-such-log'))
  testthat::expect_false(missing$truncated); testthat::expect_equal(length(missing$content), 0)

  Sys.unsetenv("METHOD_JOB_LOG_MAX_MB"); testthat::expect_equal(job_log_max_bytes(), 5 * 1024 * 1024)
  Sys.setenv(METHOD_JOB_LOG_MAX_MB = "0.5"); testthat::expect_equal(job_log_max_bytes(), 524288)
  for (bad in c("junk", "0", "-3")) {
    Sys.setenv(METHOD_JOB_LOG_MAX_MB = bad); testthat::expect_equal(job_log_max_bytes(), 5 * 1024 * 1024)
  }
  Sys.unsetenv("METHOD_JOB_LOG_MAX_MB")
  Sys.setenv(METHOD_JOB_RETENTION_HOURS = "2"); testthat::expect_equal(.job_retention_seconds(), 7200)
  Sys.setenv(METHOD_JOB_RETENTION_HOURS = "junk"); testthat::expect_equal(.job_retention_seconds(), 86400)
  Sys.unsetenv("METHOD_JOB_RETENTION_HOURS")
  unlink(c(small, big))
})

testthat::test_that('each job has its own scratch directory, removed when the job is stopped', {
  with_recovery_runner({
    env <- one_slot_manager('phylo-r-scratch-'); mgr <- env$mgr
    id <- job_manager_submit(mgr, NULL, list(mode = "slow"), 'run-scratch', timeout_seconds = 300)
    testthat::expect_true(wait_for(function() !is.null(job_manager_status(mgr, id)$pid)))
    running <- job_manager_status(mgr, id)
    withr::defer(system(sprintf('kill -KILL %d %d 2>/dev/null', running$pid, running$child_pid)))
    work <- .job_work_dir(mgr, id)
    testthat::expect_equal(normalizePath(running$tmpdir), normalizePath(work))   # the job's TMPDIR
    testthat::expect_true(startsWith(normalizePath(running$r_tempdir), normalizePath(work)))  # R's tempdir() is inside it
    testthat::expect_true(file.exists(file.path(work, 'scratch.dat')))
    testthat::expect_equal(job_manager_delete(mgr, id), 409L)               # running: nothing is removed
    testthat::expect_true(file.exists(file.path(work, 'scratch.dat')))

    testthat::expect_equal(job_manager_cancel(mgr, id)$status, 'CANCELLED')
    testthat::expect_false(dir.exists(work))                                # scratch data gone at once
    log <- job_manager_log(mgr, id)                                         # the record and the log are still there
    testthat::expect_false(log$truncated); testthat::expect_match(rawToChar(log$content), 'step 2 started')

    testthat::expect_equal(job_manager_delete(mgr, id), 200L)               # the worker has what it needs
    testthat::expect_false(dir.exists(.job_state_dir(mgr, id)))
    testthat::expect_null(job_manager_status(mgr, id)); testthat::expect_null(job_manager_log(mgr, id))
    testthat::expect_equal(job_manager_delete(mgr, id), 404L)               # repeatable
    finish_recovery_test(mgr)
  })
})

testthat::test_that('scratch data is removed after a timeout and after a normal end', {
  with_recovery_runner({
    env <- one_slot_manager('phylo-r-scratch-end-'); mgr <- env$mgr
    slow <- job_manager_submit(mgr, NULL, list(mode = "slow"), 'run-slow', timeout_seconds = 3)
    testthat::expect_true(wait_for(function() !is.null(job_manager_status(mgr, slow)$child_pid)))
    running <- job_manager_status(mgr, slow)
    testthat::expect_true(file.exists(file.path(.job_work_dir(mgr, slow), 'scratch.dat')))
    withr::defer(system(sprintf('kill -KILL %d %d 2>/dev/null', running$pid, running$child_pid)))
    wait_status(mgr, slow, 'ERROR')
    testthat::expect_false(dir.exists(.job_work_dir(mgr, slow)))
    testthat::expect_match(rawToChar(job_manager_log(mgr, slow)$content), 'step 2 started')   # the log outlives it

    testthat::expect_true(wait_for(function() job_manager_running(mgr) == 0L))
    fast <- job_manager_submit(mgr, NULL, list(mode = "fast"), 'run-fast', timeout_seconds = 300)
    wait_status(mgr, fast, 'DONE')
    testthat::expect_true(wait_for(function() job_manager_running(mgr) == 0L))
    testthat::expect_false(dir.exists(.job_work_dir(mgr, fast)))
    testthat::expect_equal(job_manager_result(mgr, fast)$code, 200)         # the result is not scratch data
    finish_recovery_test(mgr)
  })
})

testthat::test_that('job ids that are not ids are never turned into paths', {
  env <- one_slot_manager('phylo-r-ids-'); mgr <- env$mgr
  outside <- file.path(dirname(mgr$root), paste0('precious-', basename(mgr$root)))
  dir.create(outside); writeLines('keep', file.path(outside, 'status.json'))
  for (bad in list(file.path('..', basename(outside)), '../..', '.', '', 'a/b', NA_character_, NULL, c('a', 'b'))) {
    testthat::expect_equal(job_manager_delete(mgr, bad), 404L)
    testthat::expect_null(job_manager_log(mgr, bad))
  }
  testthat::expect_true(file.exists(file.path(outside, 'status.json')))
  unlink(outside, recursive = TRUE)
  finish_recovery_test(mgr)
})

testthat::test_that('records nobody collected are removed after the retention time, never a running job', {
  with_recovery_runner({
    Sys.setenv(METHOD_JOB_RETENTION_HOURS = "24")
    env <- one_slot_manager('phylo-r-purge-'); mgr <- env$mgr
    done <- job_manager_submit(mgr, NULL, list(mode = "fast"), 'run-done')
    wait_status(mgr, done, 'DONE')
    testthat::expect_true(wait_for(function() job_manager_running(mgr) == 0L))
    active <- job_manager_submit(mgr, NULL, list(mode = "slow"), 'run-active')
    testthat::expect_true(wait_for(function() !is.null(job_manager_status(mgr, active)$pid)))
    running <- job_manager_status(mgr, active)
    withr::defer(system(sprintf('kill -KILL %d %d 2>/dev/null', running$pid, running$child_pid)))

    testthat::expect_equal(job_manager_purge_expired(mgr), 0L)              # too recent
    testthat::expect_equal(job_manager_status(mgr, done)$status, 'DONE')
    testthat::expect_equal(job_manager_purge_expired(mgr, Sys.time() + 23 * 3600), 0L)
    testthat::expect_equal(job_manager_purge_expired(mgr, Sys.time() + 25 * 3600), 1L)
    testthat::expect_false(dir.exists(.job_state_dir(mgr, done)))
    testthat::expect_equal(job_manager_status(mgr, active)$status, 'RUNNING')     # however old: still running
    testthat::expect_true(file.exists(file.path(.job_work_dir(mgr, active), 'scratch.dat')))
    testthat::expect_equal(job_manager_purge_expired(mgr, Sys.time() + 25 * 3600), 0L)

    job_manager_cancel(mgr, active)
    testthat::expect_equal(job_manager_purge_expired(mgr, Sys.time() + 25 * 3600), 1L)
    testthat::expect_equal(length(list.dirs(mgr$root, recursive = FALSE)), 0L)   # the service's disk is back to empty
    Sys.unsetenv("METHOD_JOB_RETENTION_HOURS")
    finish_recovery_test(mgr)
  })
})

# ---------------------------------------------------------------------------
# Which process gives way when the container runs out of memory: the job, not
# the service (found on the real stack; see tests/system).
# ---------------------------------------------------------------------------
testthat::test_that('a job volunteers to be stopped before its service, unless told not to', {
  target <- tempfile()
  writeLines("0", target)
  Sys.unsetenv("METHOD_JOB_OOM_SCORE_ADJ")
  testthat::expect_equal(rl_job_oom_score_adj(), 800L)
  testthat::expect_true(rl_prefer_as_oom_victim(target))
  testthat::expect_equal(readLines(target), "800")

  Sys.setenv(METHOD_JOB_OOM_SCORE_ADJ = "1000")
  testthat::expect_true(rl_prefer_as_oom_victim(target)); testthat::expect_equal(readLines(target), "1000")
  Sys.setenv(METHOD_JOB_OOM_SCORE_ADJ = "0")                               # switched off: nothing is written
  testthat::expect_false(rl_prefer_as_oom_victim(target)); testthat::expect_equal(readLines(target), "1000")
  for (bad in c("1001", "-5", "high", "12.5", " ")) {
    Sys.setenv(METHOD_JOB_OOM_SCORE_ADJ = bad); testthat::expect_equal(rl_job_oom_score_adj(), 800L)
  }
  Sys.setenv(METHOD_JOB_OOM_SCORE_ADJ = " 500 "); testthat::expect_equal(rl_job_oom_score_adj(), 500L)
  Sys.unsetenv("METHOD_JOB_OOM_SCORE_ADJ")
  # Not Linux, or /proc not writable: the job simply goes on.
  testthat::expect_false(rl_prefer_as_oom_victim(file.path(tempdir(), "no-such-dir", "oom_score_adj")))
  unlink(target)

  # Only a job does this, and before it loads the method's packages.
  runner <- readLines('/srv/job_runner.R')
  guard <- grep('rl_prefer_as_oom_victim()', runner, fixed = TRUE)
  testthat::expect_length(guard, 1)
  testthat::expect_lt(guard, grep('source(plumber_path', runner, fixed = TRUE)[1])
  testthat::expect_true(any(grepl('PHYLO_JOB_CHILD', runner[(guard - 4):guard], fixed = TRUE)))
  testthat::expect_false(any(grepl('rl_prefer_as_oom_victim', readLines('/srv/job_manager.R'), fixed = TRUE)))
})
