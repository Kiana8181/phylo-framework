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
