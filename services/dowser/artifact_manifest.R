# Convert a method result's artifact_files list into the persisted manifest
# expected by the worker. Each input entry references a local file the handler
# wrote to its tempdir; this helper uploads each file directly to the artifact
# bucket (no shared filesystem with the worker) and replaces the list with a
# manifest of {object_key, size_bytes, checksum_sha256, ...} descriptors.
#
# Run in the job child process via job_runner.R after the handler completes.
# Never copies files into the run state dir — that whole shared-volume hop is
# gone. No base64 anywhere in the pipeline.
#
# A file that cannot be uploaded is never dropped silently: it is listed under
# artifact_upload_failures and storage_failure() turns that into the reason the
# job did not complete. A result whose files are not stored is not a finished
# result.
#
# manifest_version: 1

suppressWarnings(suppressMessages(library(jsonlite)))

source("/srv/object_storage.R")

.MANIFEST_VERSION <- 1L
UPLOAD_FAILED_CODE <- "ARTIFACT_UPLOAD_FAILED"

.sanitize_name <- function(name, default) {
  base <- basename(gsub("\\\\", "/", as.character(name)))
  base <- gsub("[^A-Za-z0-9._-]+", "_", base)
  if (!nzchar(base)) default else base
}

`%||%` <- function(a, b) if (is.null(a)) b else a

# Walk the artifact_files list, upload each referenced file to MinIO, build the
# manifest. run_id + job_id are required for object-key namespacing.
materialize_artifacts <- function(result, run_id, job_id) {
  if (!is.list(result)) return(result)
  run_id <- as.character(run_id)
  job_id <- as.character(job_id)
  if (!nzchar(run_id) || !nzchar(job_id)) {
    stop("materialize_artifacts: run_id + job_id are required for object-key namespacing.")
  }

  artifacts <- list()
  failures <- list()
  af <- result$artifact_files
  if (!is.null(af) && is.list(af)) {
    for (entry in af) {
      if (!is.list(entry)) next
      src <- entry$path
      if (is.null(src) || !nzchar(as.character(src)[1])) next
      src <- as.character(src)[1]
      if (!file.exists(src)) {
        warning(sprintf("materialize_artifacts: skipped missing file %s", src))
        next
      }
      default_name <- basename(src)
      filename <- as.character(entry$filename %||% default_name)[1]
      safe_name <- .sanitize_name(filename, default_name)
      content_type <- if (is.null(entry$content_type)) NULL else as.character(entry$content_type)[1]
      upload_error <- NULL
      uploaded <- tryCatch(
        upload_artifact(
          local_path = src,
          run_id = run_id,
          job_id = job_id,
          filename = safe_name,
          content_type = content_type
        ),
        error = function(e) {
          upload_error <<- conditionMessage(e)
          NULL
        }
      )
      if (is.null(uploaded)) {
        # Keep uploading the rest, but remember the failure: the job must not
        # be reported as complete without this file.
        message(sprintf("materialize_artifacts: upload failed for %s: %s", safe_name, upload_error))
        failures[[length(failures) + 1L]] <- list(
          filename = safe_name,
          error = substr(as.character(upload_error %||% "upload failed"), 1L, 300L)
        )
        next
      }
      desc <- list(
        object_key = uploaded$object_key,
        size_bytes = uploaded$size_bytes,
        checksum_sha256 = uploaded$checksum_sha256,
        filename = safe_name,
        kind = entry$kind %||% "other",
        role = entry$role,
        content_type = content_type,
        previewable = isTRUE(entry$previewable)
      )
      if (!is.null(entry$tree_index)) desc$tree_index <- as.integer(entry$tree_index)
      artifacts[[length(artifacts) + 1L]] <- desc
    }
  }

  # Strip the source-side list + any deprecated base64 keys before persisting.
  strip <- c(
    "figures", "artifact_zip_b64", "artifact_name", "visualizations",
    "render", "artifact_files"
  )
  for (k in names(result)) {
    if (k %in% strip || grepl("_b64$", k)) result[[k]] <- NULL
  }
  result$manifest_version <- .MANIFEST_VERSION
  result$artifacts <- artifacts
  if (length(failures) > 0L) result$artifact_upload_failures <- failures
  result
}

# Why the job's result files are not all in storage, or NULL if they are.
# materialize_error is the message of an error that stopped
# materialize_artifacts altogether.
storage_failure <- function(result, materialize_error = NULL) {
  if (!is.null(materialize_error) && nzchar(as.character(materialize_error)[1])) {
    return("The analysis finished, but its result files could not be saved to storage.")
  }
  failures <- if (is.list(result)) result$artifact_upload_failures else NULL
  if (is.null(failures) || length(failures) == 0L) return(NULL)
  names_ <- vapply(failures, function(f) {
    n <- if (is.list(f)) f$filename else NULL
    if (is.null(n) || !nzchar(as.character(n)[1])) "artifact" else as.character(n)[1]
  }, character(1))
  shown <- paste(utils::head(names_, 5L), collapse = ", ")
  if (length(names_) > 5L) shown <- sprintf("%s, and %d more", shown, length(names_) - 5L)
  sprintf(
    "The analysis finished, but %d result file(s) could not be saved to storage (%s).",
    length(failures), shown
  )
}

# The payload of a job that computed a result but could not store it.
mark_storage_failure <- function(result, message) {
  if (!is.list(result)) result <- list()
  result$ok <- FALSE
  result$error <- as.character(message)
  result$error_code <- UPLOAD_FAILED_CODE
  if (is.null(result$manifest_version)) result$manifest_version <- .MANIFEST_VERSION
  if (is.null(result$artifacts)) result$artifacts <- list()
  result
}
