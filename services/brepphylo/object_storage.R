# Direct upload of artifact files from the method service to MinIO/S3.
#
# Methods write their final artifact files (PNGs, ZIPs, logs, etc.) to a local
# tempdir during a job, then call `upload_artifact` to stream each file directly
# into the configured artifact bucket. The API worker never touches the file —
# it only reads the resulting {object_key, size_bytes, checksum_sha256}
# descriptor from result.json and registers a DB row.
#
# Credentials are a scoped MinIO user with `s3:PutObject` only on the artifact
# bucket. The method has no read / list / delete permission. See `minio-init`
# in docker-compose.yml for the policy.

suppressPackageStartupMessages({
  if (!requireNamespace("paws.storage", quietly = TRUE)) {
    stop("object_storage.R: paws.storage is required. Add it to the image.")
  }
  if (!requireNamespace("digest", quietly = TRUE)) {
    stop("object_storage.R: digest is required. Add it to the image.")
  }
})

# Cache the client + bucket so we don't rebuild per artifact.
.object_storage_state <- new.env(parent = emptyenv())

.sanitize_filename <- function(name, default = "artifact") {
  if (is.null(name)) return(default)
  base <- basename(gsub("\\\\", "/", as.character(name)[[1]]))
  base <- sub("^\\.+", "", base)
  safe <- gsub("[^A-Za-z0-9._-]+", "_", base)
  if (nchar(safe) > 200) safe <- substr(safe, 1, 200)
  if (!nzchar(safe)) default else safe
}

.build_client <- function() {
  if (!is.null(.object_storage_state$client)) {
    return(list(svc = .object_storage_state$client, bucket = .object_storage_state$bucket))
  }
  endpoint <- Sys.getenv("S3_ENDPOINT_URL", "")
  region <- Sys.getenv("S3_REGION", "us-east-1")
  access_key <- Sys.getenv("S3_ACCESS_KEY_ID", "")
  secret_key <- Sys.getenv("S3_SECRET_ACCESS_KEY", "")
  bucket <- Sys.getenv("S3_BUCKET_ARTIFACTS", "")
  force_path_raw <- tolower(trimws(Sys.getenv("S3_FORCE_PATH_STYLE", "true")))
  force_path <- force_path_raw %in% c("1", "true", "yes")

  if (!nzchar(endpoint) || !nzchar(access_key) || !nzchar(secret_key) || !nzchar(bucket)) {
    stop(
      "object_storage.R: env incomplete — need S3_ENDPOINT_URL, ",
      "S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_BUCKET_ARTIFACTS."
    )
  }

  svc <- paws.storage::s3(config = list(
    credentials = list(
      creds = list(
        access_key_id = access_key,
        secret_access_key = secret_key
      )
    ),
    endpoint = endpoint,
    region = region,
    s3_force_path_style = force_path
  ))

  .object_storage_state$client <- svc
  .object_storage_state$bucket <- bucket
  list(svc = svc, bucket = bucket)
}

build_object_key <- function(run_id, job_id, filename) {
  safe <- .sanitize_filename(filename)
  sprintf("artifacts/%s/%s/%s", run_id, job_id, safe)
}

# Upload one file. Returns a list(object_key, size_bytes, checksum_sha256).
# Caller composes the full descriptor by adding filename/kind/role/etc.
upload_artifact <- function(local_path, run_id, job_id,
                            filename = NULL, content_type = NULL) {
  if (is.null(local_path) || !file.exists(local_path)) {
    stop(sprintf("upload_artifact: not a file: %s", local_path))
  }
  st <- .build_client()
  fname <- if (is.null(filename)) basename(local_path) else filename
  object_key <- build_object_key(run_id, job_id, fname)
  size_bytes <- as.integer(file.info(local_path)$size)
  checksum <- digest::digest(file = local_path, algo = "sha256")

  body <- readBin(local_path, what = "raw", n = size_bytes)
  put_args <- list(Bucket = st$bucket, Key = object_key, Body = body)
  if (!is.null(content_type) && nzchar(content_type)) {
    put_args$ContentType <- content_type
  }
  do.call(st$svc$put_object, put_args)

  list(
    object_key = object_key,
    size_bytes = size_bytes,
    checksum_sha256 = checksum
  )
}
