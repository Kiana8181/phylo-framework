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
# manifest_version: 1

suppressWarnings(suppressMessages(library(jsonlite)))

source("/srv/object_storage.R")

.MANIFEST_VERSION <- 1L

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
      uploaded <- tryCatch(
        upload_artifact(
          local_path = src,
          run_id = run_id,
          job_id = job_id,
          filename = safe_name,
          content_type = content_type
        ),
        error = function(e) {
          warning(sprintf(
            "materialize_artifacts: upload failed for %s: %s", src, conditionMessage(e)
          ))
          NULL
        }
      )
      if (is.null(uploaded)) next
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
  result
}
