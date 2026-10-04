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
