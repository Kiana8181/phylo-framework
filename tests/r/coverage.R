# covr instruments all function definitions loaded in an environment. Existing
# suites are run in that environment without sourcing over the instrumentation.
method <- Sys.getenv('TEST_METHOD')
stopifnot(method %in% c('dowser', 'brepphylo'))
root <- '/srv'
source_files <- list.files(root, pattern='[.]R$', full.names=TRUE)
source_files <- source_files[!basename(source_files) %in% c('job_runner.R', 'plumber.R')]
# plumber.R is an executable endpoint module; exercised by full HTTP E2E tests.
# job_runner.R is a child entrypoint; covered behaviorally by E2E, not by covr.
test_files <- c('/srv/tests/run_validators.R', '/tests/run_contracts.R')
if (method == 'dowser') test_files <- c(test_files, '/srv/tests/run_orchestration.R')
# Legacy standalone test scripts locate sources from --file. Replace only their
# bootstrap and redundant source statements in ephemeral test copies.
test_copies <- vapply(test_files, function(path) {
  code <- readLines(path, warn=FALSE)
  code <- gsub('root <- root_dir()', 'root <- "/srv"', code, fixed=TRUE)
  code <- code[!grepl('^source\\(', code)]
  # Dowser orchestration sources its modules in a for loop.
  code <- gsub('source(file.path(root, mod))', 'invisible(NULL)', code, fixed=TRUE)
  copy <- tempfile(fileext='.R')
  writeLines(code, copy)
  copy
}, character(1))
coverage <- covr::file_coverage(source_files, test_copies)
output <- paste0('/coverage/', method)
dir.create(output, recursive=TRUE, showWarnings=FALSE)
covr::to_cobertura(coverage, filename=file.path(output, 'cobertura.xml'))
write.csv(as.data.frame(coverage), file.path(output, 'coverage.csv'), row.names=FALSE)
summary <- covr::percent_coverage(coverage)
cat(method, 'R line coverage:', summary, '\n')
writeLines(as.character(summary), file.path(output, 'percent.txt'))
stopifnot(length(coverage) > 0, summary > 0)
