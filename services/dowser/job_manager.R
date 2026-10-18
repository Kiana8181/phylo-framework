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
#
# No job stays "running" for ever:
#   - a job may carry a time limit (sent by the worker, or
#     METHOD_JOB_TIMEOUT_SECONDS); it then runs under coreutils `timeout`, which
#     stops its whole process group when the limit passes, even if the worker is
#     away;
#   - a job whose process ended without reporting a result (killed, out of
#     memory, crashed, timed out) is reported as failed the next time anyone
#     asks (.job_settle);
#   - jobs left over from before a restart of this service are reported as
#     failed at start-up (job_manager_recover).
# Submitting the same run_id again while its job is active returns that job
# instead of starting a second one.
#
# Disk use returns to where it was after every job:
#   - each job gets its own temporary directory (<job>/tmp, exported as TMPDIR
#     to the job's whole process tree), so everything R and the tools it starts
#     write as scratch data is in one known place; it is removed as soon as the
#     job is over, however it ended;
#   - the small job record that remains (status, result, log) is removed when
#     the worker confirms it has taken the result (job_manager_delete), or by
#     itself after METHOD_JOB_RETENTION_HOURS if no confirmation ever comes;
#   - the job's log is offered and uploaded in bounded form (at most
#     METHOD_JOB_LOG_MAX_MB, keeping its beginning and its end).

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
.job_log_tail_bytes <- 4000L

.job_positive_number <- function(name, default) {
  v <- suppressWarnings(as.numeric(Sys.getenv(name, "")))
  if (length(v) != 1 || is.na(v) || v <= 0) default else v
}

# Largest log offered for download or uploaded (METHOD_JOB_LOG_MAX_MB).
job_log_max_bytes <- function() floor(.job_positive_number("METHOD_JOB_LOG_MAX_MB", 5) * 1024 * 1024)

# How long a finished job's record is kept when nobody collects it.
.job_retention_seconds <- function() .job_positive_number("METHOD_JOB_RETENTION_HOURS", 24) * 3600

# The log at `path` as raw bytes, cut to `max_bytes` when it is larger: its
# first and last parts are kept (how it started, how it ended) and a line in
# the middle says how much was left out. Returns list(content, truncated).
job_bounded_log <- function(path, max_bytes = job_log_max_bytes()) {
  size <- suppressWarnings(file.info(path)$size)
  if (length(size) != 1 || is.na(size)) return(list(content = raw(0), truncated = FALSE))
  con <- file(path, "rb")
  on.exit(close(con), add = TRUE)
  if (size <= max_bytes) return(list(content = readBin(con, what = "raw", n = size), truncated = FALSE))
  half <- max(1, floor(max_bytes / 2))
  head <- readBin(con, what = "raw", n = half)
  seek(con, size - half)
  tail <- readBin(con, what = "raw", n = half)
  note <- charToRaw(sprintf(paste0(
    "\n\n[... %.0f bytes of this log were left out: it is %.0f bytes long and logs are kept up to ",
    "%.0f bytes. The beginning and the end are shown. ...]\n\n"), size - 2 * half, size, max_bytes))
  list(content = c(head, note, tail), truncated = TRUE)
}

# Job ids are generated here (32 hex characters); anything else, such as a
# path, is not a job.
.job_is_id <- function(x) {
  is.character(x) && length(x) == 1 && !is.na(x) && grepl("^[A-Za-z0-9]{1,64}$", x)
}

# Failure codes this manager reports in status$error_code.
JOB_CODE_TIMEOUT <- "TIMEOUT"
JOB_CODE_OUT_OF_MEMORY <- "OUT_OF_MEMORY"
JOB_CODE_PROCESS_LOST <- "JOB_PROCESS_LOST"
JOB_CODE_RESTARTED <- "METHOD_RESTARTED"

# One number, or NA for anything else (NULL, empty, text).
.job_num <- function(x) {
  if (is.null(x) || length(x) != 1) return(NA_real_)
  suppressWarnings(as.numeric(x))
}

.job_status_of <- function(st) {
  if (is.null(st) || is.null(st$status) || length(st$status) == 0) return("")
  as.character(st$status)[1]
}

# Time limit for jobs submitted without one (0 = none).
.job_default_timeout_seconds <- function() {
  v <- suppressWarnings(as.numeric(Sys.getenv("METHOD_JOB_TIMEOUT_SECONDS", "")))
  if (length(v) != 1 || is.na(v) || v <= 0) 0 else v
}

.job_describe_duration <- function(seconds) {
  seconds <- max(0, round(as.numeric(seconds)))
  if (seconds >= 7200) {
    hours <- seconds / 3600
    return(if (seconds %% 3600 == 0) sprintf("%d hours", as.integer(hours)) else sprintf("%.1f hours", hours))
  }
  if (seconds >= 120) return(sprintf("%d minutes", as.integer(round(seconds / 60))))
  sprintf("%d second%s", as.integer(seconds), if (seconds == 1) "" else "s")
}

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

# Process group of a pid (NA when unknown). A job started under `timeout` is
# not its own group leader, so signals for "the whole job" go to this group.
.job_pgid <- function(pid) {
  pid <- suppressWarnings(as.integer(pid))
  if (length(pid) == 0 || is.na(pid) || pid < 1L) return(NA_integer_)
  stat <- tryCatch(
    suppressWarnings(readLines(sprintf("/proc/%d/stat", pid), n = 1L, warn = FALSE)),
    error = function(e) character(0)
  )
  if (length(stat) != 1 || !nzchar(stat)) return(NA_integer_)
  # "pid (comm) state ppid pgrp ...": comm may contain spaces, so cut after ")".
  fields <- strsplit(trimws(sub("^.*\\)", "", stat)), "[[:space:]]+")[[1]]
  if (length(fields) < 3) return(NA_integer_)
  pg <- suppressWarnings(as.integer(fields[3]))
  if (is.na(pg) || pg < 1L) NA_integer_ else pg
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
  state$runs <- list()   # job id -> run id, for jobs that are still active
  state$exiting <- character(0)   # finished, process not gone yet: scratch still to remove
  # Limits are fixed for the lifetime of the container, so plan once.
  list(method_id = method_id, root = root, capacity = rl_plan_capacity(method_id), state = state)
}

.job_state_dir <- function(mgr, job_id) file.path(mgr$root, job_id)

# The job's own temporary directory (its TMPDIR).
.job_work_dir <- function(mgr, job_id) file.path(.job_state_dir(mgr, job_id), "tmp")

.job_remove_work_dir <- function(mgr, job_id) {
  unlink(.job_work_dir(mgr, job_id), recursive = TRUE, force = TRUE)
  invisible(NULL)
}

# The end of the job's own output, for the failure report.
.job_log_tail <- function(mgr, job_id) {
  p <- file.path(.job_state_dir(mgr, job_id), "job.log")
  size <- suppressWarnings(file.info(p)$size)
  if (length(size) != 1 || is.na(size) || size <= 0) return("")
  out <- tryCatch({
    con <- file(p, "rb")
    on.exit(close(con), add = TRUE)
    if (size > .job_log_tail_bytes) seek(con, size - .job_log_tail_bytes)
    bytes <- readBin(con, what = "raw", n = .job_log_tail_bytes)
    txt <- rawToChar(bytes[bytes != as.raw(0)])
    trimws(iconv(txt, from = "UTF-8", to = "UTF-8", sub = "?"))
  }, error = function(e) "")
  if (length(out) != 1 || is.na(out)) "" else out
}

# Record that a job failed for a reason its own process could not report.
.job_write_failure <- function(mgr, job_id, st, code, message) {
  sd <- .job_state_dir(mgr, job_id)
  logs <- list(list(step = "method.job.manager", ok = FALSE, out = message))
  tail <- .job_log_tail(mgr, job_id)
  if (nzchar(tail)) logs[[2]] <- list(step = "method.job.log_tail", ok = FALSE, out = tail)
  payload <- list(
    ok = FALSE, error = message, error_code = code, logs = logs,
    manifest_version = 1L, artifacts = list()
  )
  .job_write_json_atomic(file.path(sd, "result.json"), payload)
  st$status <- "ERROR"; st$stage <- "ERROR"; st$message <- message
  st$error <- payload; st$error_code <- code
  st$progress <- 100; st$finished_at <- .job_now_iso(); st$ok <- FALSE
  .job_write_json_atomic(file.path(sd, "status.json"), st)
  .job_remove_work_dir(mgr, job_id)
  message(sprintf("[job_manager] job %s failed: %s: %s", job_id, code, message))
  st
}

.job_write_cancelled <- function(mgr, job_id, st) {
  st$status <- "CANCELLED"; st$stage <- "CANCELLED"; st$message <- "Cancelled"
  st$finished_at <- .job_now_iso(); st$ok <- FALSE
  tail <- .job_log_tail(mgr, job_id)
  if (nzchar(tail)) st$log_tail <- tail
  .job_write_json_atomic(file.path(.job_state_dir(mgr, job_id), "status.json"), st)
  .job_remove_work_dir(mgr, job_id)
  st
}

.job_meta <- function(mgr, job_id) {
  .job_read_json(file.path(.job_state_dir(mgr, job_id), "meta.json"))
}

.job_timeout_message <- function(mgr, limit) {
  sprintf(
    "The job was stopped by the %s service because it exceeded its time limit of %s.",
    mgr$method_id, .job_describe_duration(limit)
  )
}

# Code and message for a job process that ended without reporting a result.
.job_exit_failure <- function(mgr, job_id) {
  meta <- .job_meta(mgr, job_id)
  deadline <- .job_num(meta$deadline_at)
  if (length(deadline) == 1 && !is.na(deadline) && as.numeric(Sys.time()) >= deadline - 1) {
    return(list(code = JOB_CODE_TIMEOUT, message = .job_timeout_message(mgr, meta$timeout_seconds)))
  }
  before <- .job_num(meta$oom_kills_at_start)
  now_count <- rl_oom_kill_count()
  if (length(before) == 1 && !is.na(before) && !is.na(now_count) && now_count > before) {
    limit <- mgr$capacity$memory_limit_mb
    within <- if (is.null(limit) || is.na(limit)) "" else sprintf(" (limit %d MiB)", as.integer(limit))
    return(list(code = JOB_CODE_OUT_OF_MEMORY, message = sprintf(paste0(
      "The job was stopped because the %s service ran out of memory%s. Try a smaller dataset, ",
      "or ask the administrator to raise the memory limit of this method."), mgr$method_id, within)))
  }
  list(code = JOB_CODE_PROCESS_LOST, message = paste(
    "The job's process ended unexpectedly without reporting a result.",
    "The run was not repeated automatically; please submit it again."
  ))
}

# A job stopped by its time limit may still manage to report the failure of the
# tool that was interrupted. Name the real cause.
.job_label_timeout <- function(mgr, job_id, st) {
  if (!identical(.job_status_of(st), "ERROR") || !is.null(st$error_code)) return(st)
  meta <- .job_meta(mgr, job_id)
  deadline <- .job_num(meta$deadline_at)
  if (length(deadline) != 1 || is.na(deadline)) return(st)
  finished <- suppressWarnings(as.numeric(as.POSIXct(
    if (is.null(st$finished_at)) "" else as.character(st$finished_at)[1], format = "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"
  )))
  if (length(finished) != 1 || is.na(finished) || finished < deadline - 2) return(st)
  st$error_code <- JOB_CODE_TIMEOUT
  st$message <- .job_timeout_message(mgr, meta$timeout_seconds)
  .job_write_json_atomic(file.path(.job_state_dir(mgr, job_id), "status.json"), st)
  st
}

# Bring a job's stored status in line with reality and return it. A job whose
# process is alive is left alone. One whose process is gone but whose status
# still says it is running gets a terminal status: nobody else will write one.
.job_settle <- function(mgr, job_id) {
  sp <- file.path(.job_state_dir(mgr, job_id), "status.json")
  st <- .job_read_json(sp)
  if (is.null(st)) return(NULL)
  if (.job_status_of(st) %in% .job_terminal) return(.job_label_timeout(mgr, job_id, st))
  if (!(job_id %in% mgr$state$active)) {
    # Not started by this process: it belongs to an earlier life of the
    # service, and its process died with it.
    return(.job_write_failure(mgr, job_id, st, JOB_CODE_RESTARTED, sprintf(paste(
      "The %s service was restarted while this job was running, so its work was lost.",
      "The run was not repeated automatically; please submit it again."), mgr$method_id)))
  }
  pid <- st$pid
  if (is.null(pid) || length(pid) == 0 || is.na(pid)) {
    started <- mgr$state$submitted[[job_id]]
    age <- if (is.null(started)) Inf else as.numeric(difftime(Sys.time(), started, units = "secs"))
    if (age < .job_start_grace_seconds) return(st)   # its Rscript is still starting
    return(.job_write_failure(mgr, job_id, st, JOB_CODE_PROCESS_LOST,
      "The job did not start. The run was not repeated automatically; please submit it again."))
  }
  if (.job_pid_running(pid)) return(st)
  # The process has ended. Its last act is an atomic status write, so read once
  # more before concluding that it reported nothing.
  again <- .job_read_json(sp)
  if (!is.null(again)) st <- again
  if (.job_status_of(st) %in% .job_terminal) return(.job_label_timeout(mgr, job_id, st))
  if (identical(.job_status_of(st), "CANCELLING")) return(.job_write_cancelled(mgr, job_id, st))
  failure <- .job_exit_failure(mgr, job_id)
  .job_write_failure(mgr, job_id, st, failure$code, failure$message)
}

# Whether a finished job's recorded process is still alive (on its way out).
.job_process_exiting <- function(st) {
  pid <- if (is.null(st)) NULL else st$pid
  !(is.null(pid) || length(pid) == 0 || is.na(pid)) && .job_pid_running(pid)
}

# Number of jobs that are still running. Finished ones drop out of the registry;
# one that ended without reporting a result is recorded as failed first.
job_manager_running <- function(mgr) {
  # Finished jobs whose process was still exiting when they dropped out: their
  # scratch data goes as soon as the process is gone.
  exiting <- character(0)
  for (id in mgr$state$exiting) {
    st <- .job_read_json(file.path(.job_state_dir(mgr, id), "status.json"))
    if (.job_process_exiting(st)) exiting <- c(exiting, id) else .job_remove_work_dir(mgr, id)
  }
  keep <- character(0)
  for (id in mgr$state$active) {
    st <- .job_settle(mgr, id)
    if (is.null(st) || .job_status_of(st) %in% .job_terminal) {
      # Over: the scratch data is no longer needed by anyone once its process
      # has exited. A runner that has just written DONE may still be exiting.
      if (.job_process_exiting(st)) exiting <- union(exiting, id) else .job_remove_work_dir(mgr, id)
      next
    }
    keep <- c(keep, id)
  }
  mgr$state$exiting <- exiting
  mgr$state$active <- keep
  for (id in setdiff(names(mgr$state$submitted), keep)) mgr$state$submitted[[id]] <- NULL
  for (id in setdiff(names(mgr$state$runs), keep)) mgr$state$runs[[id]] <- NULL
  length(keep)
}

# Fail every job left unfinished by an earlier life of this service. Call once
# when the service starts, never from a job's own process (the job runner loads
# the service code too). Returns how many jobs were closed.
job_manager_recover <- function(mgr) {
  closed <- 0L
  for (job_id in list.dirs(mgr$root, full.names = FALSE, recursive = FALSE)) {
    if (job_id %in% mgr$state$active) next
    st <- .job_read_json(file.path(mgr$root, job_id, "status.json"))
    if (is.null(st) || .job_status_of(st) %in% .job_terminal) next
    .job_settle(mgr, job_id)
    closed <- closed + 1L
  }
  job_manager_purge_expired(mgr)
  closed
}

# The job's log in bounded form, or NULL for an unknown job.
job_manager_log <- function(mgr, job_id) {
  if (!.job_is_id(job_id)) return(NULL)
  sd <- .job_state_dir(mgr, job_id)
  if (!file.exists(file.path(sd, "status.json"))) return(NULL)
  job_bounded_log(file.path(sd, "job.log"))
}

.job_purge <- function(mgr, job_id) {
  mgr$state$active <- setdiff(mgr$state$active, job_id)
  mgr$state$submitted[[job_id]] <- NULL
  mgr$state$runs[[job_id]] <- NULL
  unlink(.job_state_dir(mgr, job_id), recursive = TRUE, force = TRUE)
  200L
}

# Remove everything kept for a finished job. HTTP-style result: 200 removed,
# 404 unknown, 409 still running (nothing is removed).
job_manager_delete <- function(mgr, job_id) {
  if (!.job_is_id(job_id)) return(404L)
  sd <- .job_state_dir(mgr, job_id)
  st <- .job_settle(mgr, job_id)
  if (is.null(st)) return(if (dir.exists(sd)) .job_purge(mgr, job_id) else 404L)
  if (!(.job_status_of(st) %in% .job_terminal)) return(409L)
  .job_purge(mgr, job_id)
}

# Remove the records of finished jobs nobody collected in time, and the scratch
# data of any finished job. Returns how many records went.
job_manager_purge_expired <- function(mgr, now = Sys.time()) {
  removed <- 0L
  keep_for <- .job_retention_seconds()
  for (job_id in list.dirs(mgr$root, full.names = FALSE, recursive = FALSE)) {
    sd <- .job_state_dir(mgr, job_id)
    st <- .job_read_json(file.path(sd, "status.json"))
    if (!is.null(st)) {
      if (!(.job_status_of(st) %in% .job_terminal)) next          # running or not settled yet
      pid <- st$pid
      if (!is.null(pid) && length(pid) == 1 && !is.na(pid) && job_id %in% mgr$state$active && .job_pid_running(pid)) next
    } else if (job_id %in% mgr$state$active) {
      next
    }
    # Age first: removing the scratch data touches the directory.
    mtimes <- suppressWarnings(file.info(c(sd, list.files(sd, full.names = TRUE)))$mtime)
    newest <- suppressWarnings(max(mtimes, na.rm = TRUE))
    age <- as.numeric(difftime(now, newest, units = "secs"))
    .job_remove_work_dir(mgr, job_id)
    if (is.finite(age) && age > keep_for) {
      .job_purge(mgr, job_id)
      removed <- removed + 1L
    }
  }
  removed
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

# Returns the new job id, or list(rejected = TRUE, admission = ...) when the job
# was not started (plumber handles one request at a time, so the admission
# check and the start cannot interleave with another submit).
job_manager_submit <- function(mgr, file_path, params, run_id, timeout_seconds = NULL) {
  run_key <- if (is.null(run_id) || length(run_id) == 0) "" else as.character(run_id)[1]
  if (nzchar(run_key)) {
    # The caller may repeat a submit whose answer it never received.
    job_manager_running(mgr)
    for (id in mgr$state$active) {
      if (identical(mgr$state$runs[[id]], run_key)) return(id)
    }
  }
  decision <- job_manager_admission(mgr)
  if (!identical(decision$code, RL_ACCEPT)) {
    return(list(rejected = TRUE, admission = decision))
  }
  # A good moment to drop what earlier jobs left behind.
  job_manager_purge_expired(mgr)
  job_id <- .job_gen_id()
  sd <- .job_state_dir(mgr, job_id)
  dir.create(sd, recursive = TRUE, showWarnings = FALSE)
  # Everything the job writes as scratch data goes into its own directory,
  # which is removed when the job is over.
  work_dir <- .job_work_dir(mgr, job_id)
  dir.create(work_dir, recursive = TRUE, showWarnings = FALSE)
  .job_write_json_atomic(
    file.path(sd, "request.json"),
    list(file_path = file_path, params = params, run_id = run_id)
  )
  limit <- .job_num(timeout_seconds)
  if (is.na(limit)) limit <- .job_default_timeout_seconds()
  if (limit <= 0) limit <- 0
  # Only enforceable with coreutils `timeout` (present in the service images).
  timeout_bin <- if (limit > 0) unname(Sys.which("timeout")) else ""
  if (limit > 0 && !nzchar(timeout_bin)) {
    message("[job_manager] `timeout` not found: this job runs without a time limit of its own")
    limit <- 0
  }
  oom_kills <- rl_oom_kill_count()
  .job_write_json_atomic(
    file.path(sd, "meta.json"),
    list(
      run_id = if (nzchar(run_key)) run_key else NULL,
      submitted_at = as.numeric(Sys.time()),
      timeout_seconds = if (limit > 0) limit else NULL,
      deadline_at = if (limit > 0) as.numeric(Sys.time()) + limit else NULL,
      oom_kills_at_start = if (is.na(oom_kills)) NULL else oom_kills
    )
  )
  status <- list(
    ok = TRUE, job_id = job_id, status = "QUEUED", stage = "QUEUED",
    message = "Queued", progress = 0, pid = NULL, run_id = run_id,
    started_at = NULL, finished_at = NULL, error = NULL,
    threads = mgr$capacity$threads_per_job
  )
  if (limit > 0) status$timeout_seconds <- limit
  .job_write_json_atomic(file.path(sd, "status.json"), status)
  runner <- .job_find_runner()
  log_path <- file.path(sd, "job.log")
  # Use system(wait=FALSE): system2("sh","-c",...) mangles setsid quoting; system()
  # appends its own "&" so do not add a trailing ampersand here.
  # The job's whole process tree inherits its CPU budget. PHYLO_JOB_CHILD marks
  # the tree as a job (not the service); the memory-kill count at start lets the
  # job tell an out-of-memory kill of one of its tools from another failure.
  job_env <- c(rl_thread_environment(mgr$capacity$threads_per_job),
               list(PHYLO_JOB_CHILD = "1", TMPDIR = work_dir, TMP = work_dir, TEMP = work_dir))
  if (!is.na(oom_kills)) job_env$PHYLO_JOB_OOM_BASELINE <- as.character(oom_kills)
  env_prefix <- paste(sprintf("%s=%s", names(job_env), shQuote(as.character(job_env))), collapse = " ")
  # `timeout` signals the job's whole process group when the limit passes
  # (TERM, then KILL 10 s later), so tools started by the job stop with it.
  limiter <- if (limit > 0) {
    sprintf("%s --signal=TERM --kill-after=10 %d ", shQuote(timeout_bin), as.integer(ceiling(limit)))
  } else ""
  cmd <- paste0(
    "env ", env_prefix, " setsid -- ", limiter, "Rscript ", shQuote(runner),
    " --job-id ", shQuote(job_id),
    " --state-dir ", shQuote(sd),
    " >>", shQuote(log_path), " 2>&1 </dev/null"
  )
  system(cmd, wait = FALSE)
  mgr$state$active <- c(mgr$state$active, job_id)
  mgr$state$submitted[[job_id]] <- Sys.time()
  if (nzchar(run_key)) mgr$state$runs[[job_id]] <- run_key
  job_id
}

job_manager_status <- function(mgr, job_id) {
  .job_settle(mgr, job_id)
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
      # Signal the job's process group. Under `timeout` the job is not the group
      # leader, so look the group up instead of assuming it equals the pid.
      pg <- .job_pgid(pidn)
      if (is.na(pg)) pg <- pidn
      kcmd <- sprintf(
        "kill -TERM -%d 2>/dev/null; kill -TERM %d 2>/dev/null; (sleep 5; kill -KILL -%d 2>/dev/null; kill -KILL %d 2>/dev/null) &",
        pg, pidn, pg, pidn
      )
      system2("sh", c("-c", kcmd), wait = TRUE)
    }
  }

  st2 <- .job_read_json(sp)
  if (!is.null(st2) && as.character(st2$status) %in% c("DONE", "ERROR")) return(st2)
  .job_write_cancelled(mgr, job_id, st)
}
