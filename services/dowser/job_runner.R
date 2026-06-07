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
write_json_atomic(status_path, st)

finish_error <- function(msg, payload = NULL) {
  body <- if (!is.null(payload)) payload else list(ok = FALSE, error = as.character(msg), logs = list())
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

write_result(result)

if (ok_flag) {
  st$status <- "DONE"; st$stage <- "COMPLETED"; st$message <- "Completed"
  st$progress <- 100; st$finished_at <- now_iso(); st$ok <- TRUE; st$error <- NULL
} else {
  err_msg <- result$error %||% sprintf("Method returned HTTP %d", status_code)
  st$status <- "ERROR"; st$stage <- "ERROR"; st$message <- as.character(err_msg)
  st$error <- result; st$progress <- 100; st$finished_at <- now_iso(); st$ok <- FALSE
}
write_json_atomic(status_path, st)
