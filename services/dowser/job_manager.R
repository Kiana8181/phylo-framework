# Per-job child-process manager for the async /jobs contract (R/plumber).
# Each job runs in its own Rscript child (job_runner.R); state lives on disk
# under METHOD_JOBS_DIR/<method_id>/<job_id>/. Cancellation kills the child's
# process group only; the shared plumber container keeps running.

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
  list(method_id = method_id, root = root)
}

.job_state_dir <- function(mgr, job_id) file.path(mgr$root, job_id)

job_manager_submit <- function(mgr, file_path, params, run_id) {
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
      started_at = NULL, finished_at = NULL, error = NULL
    )
  )
  runner <- .job_find_runner()
  log_path <- file.path(sd, "job.log")
  # Use system(wait=FALSE): system2("sh","-c",...) mangles setsid quoting; system()
  # appends its own "&" so do not add a trailing ampersand here.
  cmd <- paste0(
    "setsid -- Rscript ", shQuote(runner),
    " --job-id ", shQuote(job_id),
    " --state-dir ", shQuote(sd),
    " >>", shQuote(log_path), " 2>&1 </dev/null"
  )
  system(cmd, wait = FALSE)
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
