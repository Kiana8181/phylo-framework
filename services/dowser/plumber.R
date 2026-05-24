#* @apiTitle Dowser microservice
#* @apiDescription Build BCR lineage trees with Dowser (requires AIRR-like input).

library(plumber)
SER <- plumber::serializer_json(
  auto_unbox = TRUE,
  null = "null",
  na = "null",
  dataframe = "rows"
)

library(jsonlite)
library(dowser)
library(alakazam)
library(ape)
library(jsonvalidate)
library(Biostrings)
library(readr)

options(pcre.limit.match = 1e8)
options(pcre.limit.recursion = 2e6)
Sys.setenv(PCRE2_MATCH_LIMIT = "100000000")
Sys.setenv(PCRE2_MATCH_LIMIT_RECURSION = "2000000")

IG_EXEC_DEFAULT <- Sys.getenv("IGPHYML_BIN", Sys.getenv("IG_EXEC_DEFAULT", "igphyml"))
IG_MOTIFS_DEFAULT <- Sys.getenv("IGPHYML_MOTIFS", "")
CONTRACTS_DIR <- Sys.getenv("CONTRACTS_DIR", "packages/contracts")
METHOD_DIR <- file.path(CONTRACTS_DIR, "methods", "dowser")

PARAM_SCHEMA_PATH <- file.path(METHOD_DIR, "param.schema.json")
RESULT_SCHEMA_PATH <- file.path(METHOD_DIR, "result.schema.json")
SPEC_JSON_PATH <- file.path(METHOD_DIR, "spec.json")
UI_JSON_PATH <- file.path(METHOD_DIR, "ui.json")
ROUTES_JSON_PATH <- file.path(METHOD_DIR, "service.routes.json")

read_json_or <- function(path, default = NULL) {
  if (file.exists(path)) {
    tryCatch(jsonlite::fromJSON(path, simplifyVector = FALSE), error = function(e) default)
  } else default
}

PARAM_SCHEMA <- read_json_or(PARAM_SCHEMA_PATH, list(type = "object", properties = list(), required = list()))
RESULT_SCHEMA <- RESULT_SCHEMA_PATH
SPEC_JSON <- read_json_or(SPEC_JSON_PATH, list())
UI_JSON <- read_json_or(UI_JSON_PATH, list())
ROUTES <- read_json_or(ROUTES_JSON_PATH, list(spec = "/spec", run = "/run"))

merge_list <- function(a, b) {
  a[names(b)] <- b
  a
}

DEFAULT_ACCEPTS <- c(
  "text/csv", "text/tab-separated-values",
  "application/x-rds", "application/x-rda"
)
DEFAULT_UI <- list(
  requiresFile = TRUE,
  maxFiles = 1,
  order = c(
    "analysis_mode", "tree_build", "minseq", "nproc",
    "label_field", "tip_color_by", "unknown_value"
  )
)

logf <- function(...) cat(sprintf(...), "\n", file = stderr())

get_content_type <- function(req) {
  ct <- req$HTTP_CONTENT_TYPE %||% req$CONTENT_TYPE %||% ""
  tolower(ct)
}

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0 || (is.character(a) && !nzchar(a))) b else a

source_dowser_modules <- function() {
  mod_env <- parent.frame()
  modules <- c(
    "validators.R", "data_io.R", "format_clones.R", "tree_build.R",
    "dta.R", "time_evolution.R", "internal_seqs.R", "exports.R", "handlers.R"
  )
  for (mod in modules) {
    found <- FALSE
    for (base in c("/srv", getwd())) {
      path <- file.path(base, mod)
      if (file.exists(path)) {
        source(path, local = mod_env)
        found <- TRUE
        break
      }
    }
    if (!found) stop(sprintf("Required module not found: %s", mod))
  }
}

source_dowser_modules()

log_dependency_versions()

spec_handler_impl <- function() {
  pkg_ver <- as.character(utils::packageVersion("dowser"))
  name <- SPEC_JSON$name %||% "Dowser"
  version <- SPEC_JSON$version %||% pkg_ver
  accepts <- SPEC_JSON$accepts
  if (is.null(accepts) || !length(accepts)) accepts <- DEFAULT_ACCEPTS
  ui_hints <- merge_list(DEFAULT_UI, UI_JSON)
  list(
    id = "dowser",
    name = name,
    version = version,
    accepts = accepts,
    paramSchema = PARAM_SCHEMA,
    uiHints = ui_hints
  )
}

STRICT_CONTRACT <- tolower(Sys.getenv("STRICT_CONTRACT_ROUTES", "true")) %in% c("1", "true", "yes")

#* @plumber
function(pr) {
  if (!STRICT_CONTRACT) {
    pr$handle("GET", "/spec", serializer = SER, function(req, res) spec_handler_impl())
    pr$handle("POST", "/run", serializer = SER, function(req, res) run_handler_impl(req, res))
  }
  pr$handle("GET", ROUTES$spec, serializer = SER, function(req, res) spec_handler_impl())
  pr$handle("POST", ROUTES$run, serializer = SER, function(req, res) run_handler_impl(req, res))

  pr_set_error(pr, function(req, res, err) {
    res$status <- 500
    list(ok = FALSE, error = as.character(err))
  })
  pr
}
