# Per-job child-process manager for the async /jobs contract (R/plumber).
# Each job runs in its own Rscript child (job_runner.R); state lives on disk
# under METHOD_JOBS_DIR/<method_id>/<job_id>/. Cancellation kills the child's
# process group only; the shared plumber container keeps running.
#
# Admission control: a job is only started while a job slot is free and its
# estimated memory still fits inside the container's limit (resource_limits.R).
# Otherwise job_manager_submit returns a rejection and the caller keeps the job
# queued. Each job's process tree gets a thread budget through its environment,
# so jobs x threads stays inside the container's CPU allowance.

suppressWarnings(suppressMessages(library(jsonlite)))

.job_now_iso <- function() format(as.POSIXct(Sys.time(), tz = "UTC"), "%Y-%m-%dT%H:%M:%SZ")

.job_write_json_atomic <- function(path, x) {
  tmp <- paste0(path, ".tmp")
  writeLines(jsonlite::toJSON(x, auto_unbox = TRUE, null = "null", na = "null"), tmp)
  file.rename(tmp, path)
}

.job_read_json <- function(path, simplify = TRUE) {
  if (!file.exists(path)) return(NULL)
  tryCatch(jsonlite::fromJSON(path, simplifyVector = simplify), error = function(e) NULL)
}

.job_terminal <- c("DONE", "ERROR", "CANCELLED")
# A freshly started job has no pid in status.json until its Rscript is up.
.job_start_grace_seconds <- 300

.job_source_resource_limits <- function() {
  if (exists("rl_plan_capacity", mode = "function")) return(invisible(TRUE))
  for (base in c("/srv", getwd())) {
    p <- file.path(base, "resource_limits.R")
    if (file.exists(p)) { source(p, local = FALSE); return(invisible(TRUE)) }
  }
  stop("resource_limits.R not found")
}

# TRUE while a process exists and is not a zombie (a finished child nobody has
# reaped yet still has a /proc entry).
.job_pid_running <- function(pid) {
  pid <- suppressWarnings(as.integer(pid))
  if (length(pid) == 0 || is.na(pid) || pid < 1L) return(FALSE)
  proc <- sprintf("/proc/%d", pid)
  if (dir.exists("/proc/self")) {
    if (!dir.exists(proc)) return(FALSE)
    stat <- tryCatch(suppressWarnings(readLines(file.path(proc, "stat"), n = 1L, warn = FALSE)), error = function(e) "")
    state <- sub("^.*\\) ([A-Za-z]).*$", "\\1", stat)
    return(!identical(state, "Z"))
  }
  isTRUE(tryCatch(tools::pskill(pid, 0L), error = function(e) FALSE))  # no /proc (macOS dev)
}

.job_gen_id <- function() paste(sample(c(0:9, letters[1:6]), 32, replace = TRUE), collapse = "")

.job_find_runner <- function() {
  for (base in c("/srv", getwd())) {
    p <- file.path(base, "job_runner.R")
    if (file.exists(p)) return(p)
  }
  stop("job_runner.R not found")
}

job_manager_new <- function(method_id) {
  jobs_dir <- Sys.getenv("METHOD_JOBS_DIR", "/runtime/method-jobs")
  root <- file.path(jobs_dir, method_id)
  dir.create(root, recursive = TRUE, showWarnings = FALSE)
  .job_source_resource_limits()
  # Jobs started by this process, kept in an environment so the registry is
  # shared by every request handler (lists are copied in R).
  state <- new.env(parent = emptyenv())
  state$active <- character(0)
  state$submitted <- list()
  # Limits are fixed for the lifetime of the container, so plan once.
  list(method_id = method_id, root = root, capacity = rl_plan_capacity(method_id), state = state)
}

# Number of jobs that are still running. Finished ones drop out of the registry.
job_manager_running <- function(mgr) {
  keep <- character(0)
  for (id in mgr$state$active) {
    st <- .job_read_json(file.path(mgr$root, id, "status.json"))
    if (is.null(st)) next
    if (as.character(st$status) %in% .job_terminal) next
    pid <- st$pid
    if (is.null(pid) || length(pid) == 0 || is.na(pid)) {
      started <- mgr$state$submitted[[id]]
      age <- if (is.null(started)) Inf else as.numeric(difftime(Sys.time(), started, units = "secs"))
      if (age < .job_start_grace_seconds) keep <- c(keep, id)
      next
    }
    if (.job_pid_running(pid)) keep <- c(keep, id)
  }
  mgr$state$active <- keep
  for (id in setdiff(names(mgr$state$submitted), keep)) mgr$state$submitted[[id]] <- NULL
  length(keep)
}

job_manager_admission <- function(mgr) {
  rl_admit(mgr$capacity, job_manager_running(mgr), rl_memory_in_use_bytes())
}

# Snapshot for GET /capacity: what the service may use and what is free.
job_manager_capacity <- function(mgr) {
  running <- job_manager_running(mgr)
  decision <- job_manager_admission(mgr)
  in_use <- rl_memory_in_use_bytes()
  c(mgr$capacity, list(
    ok = TRUE,
    running_jobs = running,
    free_slots = max(0L, mgr$capacity$job_slots - running),
    memory_in_use_mb = if (is.na(in_use)) NULL else as.integer(floor(in_use / (1024 * 1024))),
    accepting = identical(decision$code, RL_ACCEPT),
    code = decision$code,
    reason = decision$reason
  ))
}

.job_state_dir <- function(mgr, job_id) file.path(mgr$root, job_id)

# Returns the new job id, or list(rejected = TRUE, admission = ...) when the job
# was not started (plumber handles one request at a time, so the admission
# check and the start cannot interleave with another submit).
job_manager_submit <- function(mgr, file_path, params, run_id) {
  decision <- job_manager_admission(mgr)
  if (!identical(decision$code, RL_ACCEPT)) {
    return(list(rejected = TRUE, admission = decision))
  }
  job_id <- .job_gen_id()
  sd <- .job_state_dir(mgr, job_id)
  dir.create(sd, recursive = TRUE, showWarnings = FALSE)
  .job_write_json_atomic(
    file.path(sd, "request.json"),
    list(file_path = file_path, params = params, run_id = run_id)
  )
  .job_write_json_atomic(
    file.path(sd, "status.json"),
    list(
      ok = TRUE, job_id = job_id, status = "QUEUED", stage = "QUEUED",
      message = "Queued", progress = 0, pid = NULL, run_id = run_id,
      started_at = NULL, finished_at = NULL, error = NULL,
      threads = mgr$capacity$threads_per_job
    )
  )
  runner <- .job_find_runner()
  log_path <- file.path(sd, "job.log")
  # Use system(wait=FALSE): system2("sh","-c",...) mangles setsid quoting; system()
  # appends its own "&" so do not add a trailing ampersand here.
  # The job's whole process tree inherits its CPU budget.
  thread_env <- rl_thread_environment(mgr$capacity$threads_per_job)
  env_prefix <- paste(sprintf("%s=%s", names(thread_env), shQuote(as.character(thread_env))), collapse = " ")
  cmd <- paste0(
    "env ", env_prefix, " setsid -- Rscript ", shQuote(runner),
    " --job-id ", shQuote(job_id),
    " --state-dir ", shQuote(sd),
    " >>", shQuote(log_path), " 2>&1 </dev/null"
  )
  system(cmd, wait = FALSE)
  mgr$state$active <- c(mgr$state$active, job_id)
  mgr$state$submitted[[job_id]] <- Sys.time()
  job_id
}

job_manager_status <- function(mgr, job_id) {
  .job_read_json(file.path(.job_state_dir(mgr, job_id), "status.json"))
}

job_manager_result <- function(mgr, job_id) {
  sp <- file.path(.job_state_dir(mgr, job_id), "status.json")
  st <- .job_read_json(sp)
  if (is.null(st)) return(list(code = 404))
  if (!identical(as.character(st$status), "DONE")) return(list(code = 409))
  rp <- file.path(.job_state_dir(mgr, job_id), "result.json")
  if (!file.exists(rp)) return(list(code = 409))
  list(code = 200, path = rp)
}

job_manager_cancel <- function(mgr, job_id) {
  sp <- file.path(.job_state_dir(mgr, job_id), "status.json")
  st <- .job_read_json(sp)
  if (is.null(st)) return(NULL)
  if (as.character(st$status) %in% c("DONE", "ERROR", "CANCELLED")) return(st)

  pid <- st$pid
  st$status <- "CANCELLING"; st$stage <- "CANCELLING"; st$message <- "Cancelling..."
  .job_write_json_atomic(sp, st)

  if (!is.null(pid) && !is.na(pid) && nzchar(as.character(pid))) {
    pidn <- suppressWarnings(as.integer(pid))
    if (!is.na(pidn)) {
      kcmd <- sprintf(
        "kill -TERM -%d 2>/dev/null; kill -TERM %d 2>/dev/null; (sleep 5; kill -KILL -%d 2>/dev/null; kill -KILL %d 2>/dev/null) &",
        pidn, pidn, pidn, pidn
      )
      system2("sh", c("-c", kcmd), wait = TRUE)
    }
  }

  st2 <- .job_read_json(sp)
  if (!is.null(st2) && as.character(st2$status) %in% c("DONE", "ERROR")) return(st2)
  st$status <- "CANCELLED"; st$stage <- "CANCELLED"; st$message <- "Cancelled"
  st$finished_at <- .job_now_iso(); st$ok <- FALSE
  .job_write_json_atomic(sp, st)
  st
}
