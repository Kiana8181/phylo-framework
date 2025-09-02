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

# Merge helpers (shallow)
merge_list <- function(a, b) { # values in b override a
  a[names(b)] <- b
  a
}

# Default accepts (only used if not provided in contracts/spec.json)
DEFAULT_ACCEPTS <- c(
  "text/csv",
  "text/tab-separated-values",
  "application/x-rds",
  "application/x-rda",
  "text/fasta"
)

# Default UI hints (only used if not provided in contracts/ui.json)
DEFAULT_UI <- list(
  requiresFile = TRUE,
  maxFiles = 1,
  order = c("tree_model", "minseq", "nproc")
)

# ---------------------------
# Shared helpers
# ---------------------------
`%||%` <- function(a, b) if (is.null(a) || length(a) == 0 || (is.character(a) && !nzchar(a))) b else a

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

# ---------------------------
# Handlers (impl)
# ---------------------------
spec_handler_impl <- function() {
  # name/version: prefer contracts/spec.json, fall back to package version for dowser
  pkg_ver <- as.character(utils::packageVersion("dowser"))
  name    <- SPEC_JSON$name %||% "Dowser"
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

run_handler_impl <- function(req, res) {
  # ---- libs ----
  library(jsonlite)
  library(readr)
  library(dowser)
  library(ape)

  tryCatch(
    {
      # ---- parse multipart ----
      mp <- mime::parse_multipart(req)

      raw_params <- mp$params %||% mp$config %||% "{}"
      if (is.list(raw_params) && !is.null(raw_params$value)) raw_params <- raw_params$value
      if (length(raw_params) > 1) raw_params <- raw_params[[1]]
      p <- tryCatch(jsonlite::fromJSON(raw_params), error = function(e) list())
      if (is.null(p$minseq)) p$minseq <- 3L
      if (is.null(p$nproc))  p$nproc  <- 1L

      # ---- find file part ----
      f <- NULL
      if (!is.null(mp$file) && is.list(mp$file) && !is.null(mp$file$datapath)) f <- mp$file
      if (is.null(f)) {
        idx <- which(vapply(mp, function(x) is.list(x) && !is.null(x$datapath), logical(1)))
        if (length(idx)) f <- mp[[idx[1]]]
      }
      if (is.null(f) || is.null(f$datapath) || !nzchar(f$datapath)) {
        res$status <- 400
        return(list(ok = FALSE, error = "file is required (AIRR TSV/CSV/RDS/RDA)"))
      }

      filename <- f$filename %||% f$name %||% basename(f$datapath) %||% "upload.bin"
      ctype <- f$content_type %||% f$type %||% ""
      ext <- tolower(tools::file_ext(filename))

      # infer from content-type if missing
      if (ext == "" && nzchar(ctype)) {
        if (grepl("csv", ctype, ignore.case = TRUE)) {
          ext <- "csv"
        } else if (grepl("tab|tsv", ctype, ignore.case = TRUE)) {
          ext <- "tsv"
        } else if (grepl("rds", ctype, ignore.case = TRUE)) {
          ext <- "rds"
        } else if (grepl("rda|rdata", ctype, ignore.case = TRUE)) ext <- "rda"
      }
      # sniff delimiter if still unknown
      if (ext == "") {
        head1 <- try(readLines(f$datapath, n = 1, warn = FALSE), silent = TRUE)
        if (!inherits(head1, "try-error") && length(head1)) {
          if (grepl("\t", head1)) {
            ext <- "tsv"
          } else if (grepl(",", head1)) ext <- "csv"
        }
      }

      # ---- read data ----
      db <- NULL
      load_ok <- FALSE
      if (ext %in% c("tsv", "txt")) {
        db <- suppressMessages(readr::read_tsv(f$datapath, show_col_types = FALSE))
      } else if (ext == "csv") {
        db <- suppressMessages(readr::read_csv(f$datapath, show_col_types = FALSE))
      } else if (ext == "rds") {
        db <- readRDS(f$datapath)
        load_ok <- TRUE
      } else if (ext %in% c("rda", "rdata")) {
        e <- new.env()
        load(f$datapath, envir = e)
        db <- e[[ls(e)[1]]]
        load_ok <- TRUE
      } else {
        # last-resort guesses
        try({ db <- readRDS(f$datapath); load_ok <- TRUE }, silent = TRUE)
        if (!load_ok) {
          try({
            e <- new.env(); load(f$datapath, envir = e)
            db <- e[[ls(e)[1]]]; load_ok <- TRUE
          }, silent = TRUE)
        }
        if (is.null(db)) {
          try({ db <- suppressMessages(readr::read_tsv(f$datapath, show_col_types = FALSE)) }, silent = TRUE)
        }
        if (is.null(db)) {
          try({ db <- suppressMessages(readr::read_csv(f$datapath, show_col_types = FALSE)) }, silent = TRUE)
        }
      }

      if (is.null(db)) {
        res$status <- 400
        return(list(
          ok = FALSE,
          error = sprintf("Unsupported file type: filename='%s' content_type='%s'. Expect AIRR TSV/CSV or RDS/RDA.", filename, ctype)
        ))
      }

      # ---- sanity ----
      req_cols <- c("clone_id", "sequence_id")
      if (!all(req_cols %in% names(db))) {
        res$status <- 400
        return(list(
          ok = FALSE,
          error = paste0(
            "Input missing required columns: ",
            paste(setdiff(req_cols, names(db)), collapse = ", "),
            ". Expect AIRR columns including clone_id and sequence_id."
          )
        ))
      }
      if (!"c_call" %in% names(db)) db$c_call <- "unknown"

      # ---- clones & trees ----
      clones <- dowser::formatClones(db, traits = "c_call", minseq = as.integer(p$minseq))
      trees_tbl <- dowser::getTrees(clones, nproc = as.integer(p$nproc))

      # ---- outputs ----
      newicks <- lapply(trees_tbl$trees, to_newick)

      figures_b64 <- NULL
      if (requireNamespace("ggtree", quietly = TRUE) && requireNamespace("ggplot2", quietly = TRUE)) {
        plots <- dowser::plotTrees(trees_tbl, tips = "c_call", tipsize = 2)
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
        clone_id = as.character(clones$clone_id),
        seqs     = as.integer(clones$seqs)
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

      # validate result with contracts schema (path)
      if (!jsonvalidate::json_validate(
        jsonlite::toJSON(result, auto_unbox = TRUE, null = "null"),
        RESULT_SCHEMA_PATH,
        verbose = TRUE
      )) {
        res$status <- 500
        return(list(ok = FALSE, error = "Result does not match schema"))
      }

      return(result)
    },
    error = function(e) {
      res$status <- 500
      list(ok = FALSE, error = as.character(e))
    }
  )
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
  pr
}

