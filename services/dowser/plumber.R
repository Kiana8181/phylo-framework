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

# Raise PCRE limits (helps multipart parser with long headers)
options(pcre.limit.match     = 1e8)
options(pcre.limit.recursion = 2e6)
Sys.setenv(PCRE2_MATCH_LIMIT="100000000")
Sys.setenv(PCRE2_MATCH_LIMIT_RECURSION="2000000")

# ---------------------------
# Config & Contracts loading
# ---------------------------
CONTRACTS_DIR <- Sys.getenv("CONTRACTS_DIR", "packages/contracts")
METHOD_DIR    <- file.path(CONTRACTS_DIR, "methods", "dowser")

PARAM_SCHEMA_PATH   <- file.path(METHOD_DIR, "param.schema.json")
RESULT_SCHEMA_PATH  <- file.path(METHOD_DIR, "result.schema.json")
SPEC_JSON_PATH      <- file.path(METHOD_DIR, "spec.json")
UI_JSON_PATH        <- file.path(METHOD_DIR, "ui.json")
ROUTES_JSON_PATH    <- file.path(METHOD_DIR, "service.routes.json")

read_json_or <- function(path, default = NULL) {
  if (file.exists(path)) {
    tryCatch(jsonlite::fromJSON(path, simplifyVector = FALSE),
             error = function(e) default)
  } else default
}

PARAM_SCHEMA  <- read_json_or(PARAM_SCHEMA_PATH, list(type="object", properties=list(), required=list()))
RESULT_SCHEMA <- RESULT_SCHEMA_PATH  # jsonvalidate accepts a path

SPEC_JSON     <- read_json_or(SPEC_JSON_PATH, list())
UI_JSON       <- read_json_or(UI_JSON_PATH, list())
ROUTES        <- read_json_or(ROUTES_JSON_PATH, list(spec="/spec", run="/run"))

merge_list <- function(a, b) { a[names(b)] <- b; a }

DEFAULT_ACCEPTS <- c("text/csv","text/tab-separated-values","application/x-rds","application/x-rda","text/fasta")
DEFAULT_UI <- list(requiresFile = TRUE, maxFiles = 1, order = c("tree_model", "minseq", "nproc"))

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0 || (is.character(a) && !nzchar(a))) b else a
logf <- function(...) cat(sprintf(...), "\n", file=stderr())

to_newick <- function(phy) {
  tf <- tempfile(fileext = ".nwk")
  on.exit(if (file.exists(tf)) unlink(tf), add = TRUE)
  ape::write.tree(phy, file = tf)
  paste(readLines(tf, warn = FALSE), collapse = "")
}

encode_png <- function(plot, width = 900, height = 520, dpi = 100) {
  tf <- tempfile(fileext = ".png")
  on.exit(if (file.exists(tf)) unlink(tf), add = TRUE)
  ggplot2::ggsave(tf, plot = plot, width = width / 100, height = height / 100, dpi = dpi, bg = "white")
  jsonlite::base64_enc(readBin(tf, "raw", n = file.info(tf)$size))
}

get_content_type <- function(req) {
  ct <- req$HTTP_CONTENT_TYPE %||% req$CONTENT_TYPE %||% ""
  tolower(ct)
}

read_airr_from_path <- function(path) {
  ext <- tolower(tools::file_ext(path))
  if (ext %in% c("tsv", "txt")) {
    suppressMessages(readr::read_tsv(path, show_col_types = FALSE))
  } else if (ext == "csv") {
    suppressMessages(readr::read_csv(path, show_col_types = FALSE))
  } else if (ext == "rds") {
    readRDS(path)
  } else if (ext %in% c("rda","rdata")) {
    e <- new.env(); load(path, envir = e); e[[ls(e)[1]]]
  } else {
    stop(sprintf("Unsupported file extension: %s", ext))
  }
}

# Dowser wants clone+germline fields typical of *clone-pass.tsv*
validate_airr_for_dowser <- function(db) {
  req <- c("sequence_id","clone_id","sequence_alignment","germline_alignment_d_mask","v_call","j_call","junction")
  missing <- setdiff(req, names(db))
  if (length(missing)) {
    stop(paste0(
      "Input missing required columns for Dowser: ",
      paste(missing, collapse=", "),
      ". Upload a Change-O clone table (e.g. *clone-pass.tsv*)."
    ))
  }
}

spec_handler_impl <- function() {
  pkg_ver <- as.character(utils::packageVersion("dowser"))
  name    <- SPEC_JSON$name %||% "Dowser"
  version <- SPEC_JSON$version %||% pkg_ver
  accepts <- SPEC_JSON$accepts; if (is.null(accepts) || !length(accepts)) accepts <- DEFAULT_ACCEPTS
  ui_hints <- merge_list(DEFAULT_UI, UI_JSON)
  list(id="dowser", name=name, version=version, accepts=accepts, paramSchema=PARAM_SCHEMA, uiHints=ui_hints)
}

run_handler_impl <- function(req, res) {
  library(jsonlite); library(readr); library(dowser); library(ape)

  tryCatch({
    ct <- get_content_type(req)
    logf("[dowser] content-type: %s", ct)

    # ---- Accept big files via JSON { file_path, params } ----
    if (grepl("application/json", ct, fixed = TRUE)) {
      body_raw <- req$postBody
      if (is.raw(body_raw)) body_raw <- rawToChar(body_raw)
      body <- jsonlite::fromJSON(body_raw, simplifyVector = FALSE)
      file_path <- body$file_path %||% NULL
      p <- body$params %||% list()
      if (is.null(p$minseq)) p$minseq <- 3L
      if (is.null(p$nproc))  p$nproc  <- 1L

      if (is.null(file_path) || !file.exists(file_path)) {
        res$status <- 400; return(list(ok=FALSE, error="file_path is required and must exist on the server"))
      }
      db <- read_airr_from_path(file_path)

    } else {
      # ---- Fallback: multipart (for small files only) ----
      mp <- tryCatch(mime::parse_multipart(req), error = function(e) e)
      if (inherits(mp, "error")) {
        res$status <- 413
        return(list(
          ok = FALSE,
          error = paste0("Failed to parse multipart (too large?). ",
                         "Prefer JSON {\"file_path\": \"/path/to/file\", \"params\": {...}}. ",
                         mp$message)
        ))
      }

      raw_params <- mp$params %||% mp$config %||% "{}"
      if (is.list(raw_params) && !is.null(raw_params$value)) raw_params <- raw_params$value
      if (length(raw_params) > 1) raw_params <- raw_params[[1]]
      p <- tryCatch(jsonlite::fromJSON(raw_params), error = function(e) list())
      if (is.null(p$minseq)) p$minseq <- 3L
      if (is.null(p$nproc))  p$nproc  <- 1L

      f <- NULL
      if (!is.null(mp$file) && is.list(mp$file) && !is.null(mp$file$datapath)) f <- mp$file
      if (is.null(f)) {
        idx <- which(vapply(mp, function(x) is.list(x) && !is.null(x$datapath), logical(1)))
        if (length(idx)) f <- mp[[idx[1]]]
      }
      if (is.null(f) || is.null(f$datapath) || !nzchar(f$datapath)) {
        res$status <- 400; return(list(ok=FALSE, error="file is required (AIRR TSV/CSV/RDS/RDA)"))
      }
      db <- read_airr_from_path(f$datapath)
    }

    # ---- Sanity & cleaning ----
    logf("[dowser] rows=%d cols=%d", nrow(db), ncol(db))
    validate_airr_for_dowser(db)

    # enforce character IDs and drop empties
    if ("sequence_id" %in% names(db)) db$sequence_id <- as.character(db$sequence_id)
    if ("clone_id"    %in% names(db)) db$clone_id    <- as.character(db$clone_id)
    db <- db[!is.na(db$sequence_id) & nzchar(db$sequence_id) &
               !is.na(db$clone_id)    & nzchar(db$clone_id), , drop=FALSE]

    # ---- c_call: fill NAs/empties with "unknown" so Dowser doesn't error ----
    # if (!"c_call" %in% names(db)) {
    #   db$c_call <- "unknown"
    # } else {
    #   db$c_call <- as.character(db$c_call)
    #   db$c_call[is.na(db$c_call) | !nzchar(trimws(db$c_call))] <- "unknown"
    # }
    # n_non_unknown <- sum(db$c_call != "unknown", na.rm = TRUE)
    # logf("[dowser] c_call non-empty values: %d (unknown filled for %d)", n_non_unknown, nrow(db) - n_non_unknown)

    # ---- Build clones & trees ----
    p$minseq <- as.integer(p$minseq); p$nproc <- as.integer(p$nproc)
    clones   <- dowser::formatClones(db, traits = NULL, minseq = p$minseq)
    if (nrow(clones) == 0) {
      res$status <- 400
      return(list(ok=FALSE, error=sprintf(
        "No clones met the criteria (minseq=%d). Check that clone_id is present and c_call is not entirely empty.", p$minseq)))
    }

    trees_tbl <- dowser::getTrees(clones, nproc = p$nproc)

    # ---- Outputs ----
    newicks <- lapply(trees_tbl$trees, to_newick)

    figures_b64 <- NULL
    if (requireNamespace("ggtree", quietly = TRUE) && requireNamespace("ggplot2", quietly = TRUE)) {
      plots <- dowser::plotTrees(trees_tbl, tips = NULL, tipsize = 2)
      figures_b64 <- lapply(plots, encode_png)
    }

    annos <- lapply(trees_tbl$trees, function(phy) {
      tips <- phy$tip.label
      jj <- match(tips, db$sequence_id)
      data.frame(
        label = tips,
        c_call = ifelse(is.na(jj), "Germline", as.character(db$c_call[jj])),
        stringsAsFactors = FALSE
      )
    })

    clones_meta <- list(
      clone_id = unname(as.list(as.character(clones$clone_id))),
      seqs     = unname(as.list(as.integer(clones$seqs)))
    )

    stats <- list(
      n_clones   = length(unique(db$clone_id)),
      n_trees    = length(trees_tbl$trees),
      total_seqs = nrow(db)
    )

    result <- list(
      ok = TRUE,
      trees = unname(newicks),
      clones = clones_meta,
      annotations = annos,
      figures = if (is.null(figures_b64)) NULL else list(png_base64 = unname(figures_b64)),
      stats = stats,
      render = if (is.null(figures_b64)) NULL else "plotTrees_c_call_tipsize2"
    )

    if (!jsonvalidate::json_validate(
      jsonlite::toJSON(result, auto_unbox = TRUE, null = "null"),
      RESULT_SCHEMA_PATH, verbose = TRUE
    )) {
      res$status <- 500
      return(list(ok = FALSE, error = "Result does not match schema"))
    }

    return(result)
  }, error = function(e) {
    logf("[dowser][ERROR] %s", as.character(e))
    res$status <- 500
    list(ok = FALSE, error = as.character(e))
  })
}

STRICT_CONTRACT <- tolower(Sys.getenv("STRICT_CONTRACT_ROUTES", "true")) %in% c("1","true","yes")

#* @plumber
function(pr) {
  if (!STRICT_CONTRACT) {
    pr$handle("GET",  "/spec", serializer = SER, function(req, res) spec_handler_impl())
    pr$handle("POST", "/run",  serializer = SER, function(req, res) run_handler_impl(req, res))
  }
  pr$handle("GET",  ROUTES$spec, serializer = SER, function(req, res) spec_handler_impl())
  pr$handle("POST", ROUTES$run,  serializer = SER, function(req, res) run_handler_impl(req, res))

  pr_set_error(pr, function(req, res, err){
    res$status <- 500
    list(ok = FALSE, error = as.character(err))
  })
  pr
}
