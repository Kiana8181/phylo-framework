#!/usr/bin/env Rscript
# Child-process entrypoint for a single method job (R/plumber services).
# Reuses the existing run_handler_impl unchanged by sourcing plumber.R, then
# writes stage-based status.json + result.json atomically. Spawned by
# job_manager_submit. Killing this process group cancels the job.

suppressWarnings(suppressMessages(library(jsonlite)))

args <- commandArgs(trailingOnly = TRUE)
get_arg <- function(flag) {
  i <- which(args == flag)
  if (length(i) >= 1 && i[1] < length(args)) args[i[1] + 1] else NA_character_
}
job_id <- get_arg("--job-id")
state_dir <- get_arg("--state-dir")
if (is.na(job_id) || is.na(state_dir)) quit(status = 2)

# Before the method's packages are loaded and memory use starts to grow: if the
# container runs out of memory, this job is what the kernel should stop, not
# the service that started it (see rl_prefer_as_oom_victim).
if (identical(Sys.getenv("PHYLO_JOB_CHILD", ""), "1")) {
  for (base in c("/srv", getwd())) {
    limits <- file.path(base, "resource_limits.R")
    if (file.exists(limits)) {
      tryCatch({ source(limits, local = FALSE); rl_prefer_as_oom_victim() }, error = function(e) NULL)
      break
    }
  }
}

status_path <- file.path(state_dir, "status.json")
result_path <- file.path(state_dir, "result.json")
request_path <- file.path(state_dir, "request.json")

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0 || (is.character(a) && !nzchar(a))) b else a
now_iso <- function() format(as.POSIXct(Sys.time(), tz = "UTC"), "%Y-%m-%dT%H:%M:%SZ")
write_json_atomic <- function(path, x) {
  tmp <- paste0(path, ".tmp")
  writeLines(jsonlite::toJSON(x, auto_unbox = TRUE, null = "null", na = "null"), tmp)
  file.rename(tmp, path)
}
read_json_file <- function(path, simplify = TRUE) {
  if (!file.exists(path)) return(NULL)
  tryCatch(jsonlite::fromJSON(path, simplifyVector = simplify), error = function(e) NULL)
}
serialize_like_ser <- function(x) {
  jsonlite::toJSON(x, auto_unbox = TRUE, null = "null", na = "null", dataframe = "rows", digits = 10, force = TRUE)
}
write_result <- function(x) {
  tmp <- paste0(result_path, ".tmp")
  writeLines(serialize_like_ser(x), tmp)
  file.rename(tmp, result_path)
}

# Upload state_dir/job.log to MinIO and append the descriptor to
# result$artifacts so the worker registers it like any other artifact. Called
# both from the success path (after materialize_artifacts) and the error path
# (before quit). Robust to NULL result / missing log / failed upload.
log_path <- file.path(state_dir, "job.log")
finalize_with_log <- function(result) {
  if (!is.list(result)) return(result)
  if (is.null(result$manifest_version)) result$manifest_version <- 1L
  if (is.null(result$artifacts)) result$artifacts <- list()
  if (!file.exists(log_path)) return(result)
  tryCatch({ flush(stdout()); flush(stderr()) }, error = function(e) NULL)
  src_loaded <- tryCatch({
    if (!exists("upload_artifact", mode = "function")) {
      source("/srv/object_storage.R", local = FALSE)
    }
    TRUE
  }, error = function(e) FALSE)
  if (!isTRUE(src_loaded) || !exists("upload_artifact", mode = "function")) return(result)
  # Logs are stored in bounded form: a very long one keeps its beginning and
  # its end (METHOD_JOB_LOG_MAX_MB).
  upload_path <- log_path
  if (exists("job_bounded_log", mode = "function")) {
    bounded <- tryCatch(job_bounded_log(log_path), error = function(e) NULL)
    if (!is.null(bounded) && isTRUE(bounded$truncated)) {
      upload_path <- file.path(state_dir, "job.log.bounded")
      writeBin(bounded$content, upload_path)
    }
  }
  uploaded <- tryCatch(
    upload_artifact(
      local_path = upload_path,
      run_id = run_id, job_id = job_id,
      filename = "job.log", content_type = "text/plain"
    ),
    error = function(e) {
      message(sprintf("job.log upload failed: %s", conditionMessage(e)))
      NULL
    }
  )
  if (is.null(uploaded)) {
    result$log_upload_failed <- TRUE
    return(result)
  }
  result$artifacts[[length(result$artifacts) + 1L]] <- list(
    object_key = uploaded$object_key,
    size_bytes = uploaded$size_bytes,
    checksum_sha256 = uploaded$checksum_sha256,
    filename = "job.log",
    kind = "log",
    role = "log",
    content_type = "text/plain",
    previewable = TRUE
  )
  result
}

req_json <- read_json_file(request_path, simplify = FALSE)
file_path <- req_json$file_path %||% NULL
params <- req_json$params %||% list()
run_id <- req_json$run_id %||% NULL

# Respect a cancel that landed before we started.
pre <- read_json_file(status_path)
if (!is.null(pre) && identical(as.character(pre$status), "CANCELLED")) quit(status = 0)

st <- list(
  ok = TRUE, job_id = job_id, status = "RUNNING", stage = "RUNNING_METHOD",
  message = "Running method", progress = 45, pid = Sys.getpid(), run_id = run_id,
  started_at = now_iso(), finished_at = NULL, error = NULL
)
# Keep what the job manager recorded at submit.
for (kept in c("threads", "timeout_seconds")) {
  if (!is.null(pre) && !is.null(pre[[kept]])) st[[kept]] <- pre[[kept]]
}
write_json_atomic(status_path, st)

# TRUE when the kernel killed a process of this container for lack of memory
# since this job started (the job manager passes the count at start).
out_of_memory_during_job <- function() {
  baseline <- suppressWarnings(as.numeric(Sys.getenv("PHYLO_JOB_OOM_BASELINE", "")))
  if (length(baseline) != 1 || is.na(baseline)) return(FALSE)
  if (!exists("rl_oom_kill_count", mode = "function")) return(FALSE)
  current <- tryCatch(rl_oom_kill_count(), error = function(e) NA_real_)
  !is.na(current) && current > baseline
}
out_of_memory_message <- function(original) {
  paste0(
    "The analysis ran out of memory and could not finish. Try a smaller dataset, or ask ",
    "the administrator to raise the memory limit of this method. ",
    "(Reported by the method: ", as.character(original), ")"
  )
}

finish_error <- function(msg, payload = NULL) {
  body <- if (!is.null(payload)) payload else list(ok = FALSE, error = as.character(msg), logs = list())
  body <- finalize_with_log(body)
  write_result(body)
  st$status <- "ERROR"; st$stage <- "ERROR"; st$message <- as.character(msg)
  st$error <- body; st$progress <- 100; st$finished_at <- now_iso(); st$ok <- FALSE
  write_json_atomic(status_path, st)
  quit(status = 0)
}

plumber_path <- NA_character_
for (base in c("/srv", getwd())) {
  p <- file.path(base, "plumber.R")
  if (file.exists(p)) { plumber_path <- p; break }
}
if (is.na(plumber_path)) finish_error("plumber.R not found")

src <- tryCatch({ source(plumber_path, local = FALSE); TRUE }, error = function(e) e)
if (inherits(src, "error")) finish_error(sprintf("Failed to load service: %s", conditionMessage(src)))
if (!exists("run_handler_impl", mode = "function")) finish_error("run_handler_impl unavailable after loading service")

req <- new.env()
req$postBody <- jsonlite::toJSON(list(file_path = file_path, params = params), auto_unbox = TRUE, null = "null")
req$HTTP_CONTENT_TYPE <- "application/json"
res <- new.env()
res$status <- 200L
res$setHeader <- function(...) invisible(NULL)

result <- tryCatch(run_handler_impl(req, res), error = function(e) list(ok = FALSE, error = conditionMessage(e)))
status_code <- tryCatch(as.integer(res$status %||% 200L), error = function(e) 200L)
ok_flag <- isTRUE(result$ok) && !is.na(status_code) && status_code < 400

# Upload artifact files directly to MinIO and replace the source-side
# artifact_files list with a {object_key, size_bytes, checksum_sha256, ...}
# manifest. Nothing crosses the service -> API boundary as base64 or via a
# shared volume.
for (base in c("/srv", getwd())) {
  am <- file.path(base, "artifact_manifest.R")
  if (file.exists(am)) { source(am, local = FALSE); break }
}
materialize_error <- NULL
if (exists("materialize_artifacts", mode = "function")) {
  result <- tryCatch(
    materialize_artifacts(result, run_id = run_id, job_id = job_id),
    error = function(e) {
      materialize_error <<- conditionMessage(e)
      message(sprintf("materialize_artifacts failed: %s", conditionMessage(e)))
      result
    }
  )
} else if (ok_flag) {
  materialize_error <- "artifact_manifest.R not found"
}

# A successful analysis whose files are not in storage is not a finished job:
# report it as a failure instead of as DONE.
if (ok_flag && exists("storage_failure", mode = "function")) {
  not_stored <- storage_failure(result, materialize_error)
  if (!is.null(not_stored)) {
    message(not_stored)
    result <- mark_storage_failure(result, not_stored)
    ok_flag <- FALSE
  }
}

result <- finalize_with_log(result)
write_result(result)

if (ok_flag) {
  st$status <- "DONE"; st$stage <- "COMPLETED"; st$message <- "Completed"
  st$progress <- 100; st$finished_at <- now_iso(); st$ok <- TRUE; st$error <- NULL
} else {
  err_msg <- as.character(result$error %||% sprintf("Method returned HTTP %d", status_code))[1]
  error_code <- if (is.null(result$error_code)) NULL else as.character(result$error_code)[1]
  if (is.null(error_code) && out_of_memory_during_job()) {
    err_msg <- out_of_memory_message(err_msg)
    error_code <- "OUT_OF_MEMORY"
  }
  st$status <- "ERROR"; st$stage <- "ERROR"; st$message <- err_msg
  st$error <- result; st$progress <- 100; st$finished_at <- now_iso(); st$ok <- FALSE
  if (!is.null(error_code)) st$error_code <- error_code
}
write_json_atomic(status_path, st)
