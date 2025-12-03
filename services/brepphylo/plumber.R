#* @apiTitle BrepPhylo microservice
#* @apiDescription Build BCR lineage trees with BrepPhylo::cloneLineage.

library(plumber)
SER <- plumber::serializer_json(
  auto_unbox = TRUE,
  null = "null",
  na = "null",
  dataframe = "rows"
)
plumber::register_serializer("SER", function(...) SER)

library(jsonlite)
library(BrepPhylo)
library(ape)
library(Biostrings)
library(igraph)

# ---------------------------
# Helpers
# ---------------------------
`%||%` <- function(x, y) if (!is.null(x) && !(is.character(x) && length(x) == 1 && is.na(x))) x else y
logf <- function(...) cat(sprintf(...), "\n", file = stderr())

as_bool <- function(x, default = FALSE) {
  if (is.null(x)) return(default)
  if (is.logical(x)) return(isTRUE(x))
  if (is.numeric(x)) return(x != 0)
  if (is.character(x)) return(tolower(x) %in% c("1", "true", "t", "yes", "y"))
  default
}

normalize_col <- function(val, default = NULL) {
  if (is.null(val)) return(default)
  val <- as.character(val)[1]
  if (!nzchar(val)) return(default)
  val
}

read_input_table <- function(path) {
  ext <- tolower(tools::file_ext(path))
  if (ext %in% c("csv")) {
    read.csv(path, stringsAsFactors = FALSE)
  } else if (ext %in% c("tsv", "txt")) {
    read.delim(path, stringsAsFactors = FALSE)
  } else {
    stop(sprintf("Unsupported file extension '%s'. Provide CSV/TSV.", ext))
  }
}

build_class_palette <- function(df, class_col, class_palette_param) {
  if (is.null(class_col) || length(class_col) == 0 || !nzchar(class_col)) return(list())

  if (!is.null(class_palette_param) && length(class_palette_param) > 0) {
    if (is.data.frame(class_palette_param)) {
      cols <- as.list(class_palette_param$color)
      names(cols) <- as.character(class_palette_param$level)
      return(cols)
    }
    if (is.list(class_palette_param)) {
      cols <- lapply(class_palette_param, function(x) x$color)
      names(cols) <- vapply(class_palette_param, function(x) x$level, character(1))
      return(cols)
    }
  }

  # Auto palette from data if column exists
  if (!class_col %in% names(df)) return(list())
  classes <- sort(unique(as.character(df[[class_col]])))
  classes <- classes[!is.na(classes) & nzchar(classes)]
  if (!length(classes)) return(list())

  pal <- as.list(grDevices::rainbow(length(classes)))
  names(pal) <- classes
  pal
}

make_annotations_per_clone <- function(df, clone_id, clone_col, label_col, class_col) {
  cur <- df[df[[clone_col]] == clone_id, , drop = FALSE]
  if (!nrow(cur)) return(list())

  annos <- vector("list", nrow(cur))
  for (i in seq_len(nrow(cur))) {
    row <- cur[i, , drop = FALSE]
    label <- if (!is.null(label_col) && nzchar(label_col) && label_col %in% names(row)) {
      val <- trimws(as.character(row[[label_col]]))
      if (nzchar(val)) val else as.character(i)
    } else {
      as.character(i)
    }

    a <- as.list(row[1, , drop = FALSE])
    a$label <- label
    annos[[i]] <- a
  }
  annos
}

clone_seq_counts <- function(df, clone_col, clone_ids) {
  vapply(clone_ids, function(cid) sum(df[[clone_col]] == cid, na.rm = TRUE), integer(1))
}

resolve_executable <- function(candidates) {
  for (c in candidates) {
    if (is.null(c) || !nzchar(c)) next
    p <- normalizePath(c, mustWork = FALSE)
    if (file.exists(p) && file.access(p, 1) == 0) return(p)
  }
  NULL
}

clean_input_df <- function(df, seq_col, clone_col, germ_col) {
  warnings <- character(0)

  drop_if_blank <- function(x) is.na(x) | !nzchar(trimws(as.character(x)))

  bad_seq <- drop_if_blank(df[[seq_col]])
  if (any(bad_seq)) {
    warnings <- c(warnings, sprintf("Dropped %d rows with empty %s.", sum(bad_seq), seq_col))
    df <- df[!bad_seq, , drop = FALSE]
  }

  bad_clone <- drop_if_blank(df[[clone_col]])
  if (any(bad_clone)) {
    warnings <- c(warnings, sprintf("Dropped %d rows with empty %s.", sum(bad_clone), clone_col))
    df <- df[!bad_clone, , drop = FALSE]
  }

  bad_germ <- drop_if_blank(df[[germ_col]])
  if (any(bad_germ)) {
    warnings <- c(warnings, sprintf("Dropped %d rows with empty %s.", sum(bad_germ), germ_col))
    df <- df[!bad_germ, , drop = FALSE]
  }

  list(df = df, warnings = warnings)
}

# ---------------------------
# Config & Contracts loading
# ---------------------------
METHOD_ID <- "brepphylo"
CONTRACTS_DIR <- Sys.getenv("CONTRACTS_DIR", "packages/contracts")
METHOD_DIR <- file.path(CONTRACTS_DIR, "methods", METHOD_ID)

PARAM_SCHEMA_PATH <- file.path(METHOD_DIR, "param.schema.json")
RESULT_SCHEMA_PATH <- file.path(METHOD_DIR, "result.schema.json")
SPEC_JSON_PATH <- file.path(METHOD_DIR, "spec.json")
UI_JSON_PATH <- file.path(METHOD_DIR, "ui.json")
ROUTES_JSON_PATH <- file.path(METHOD_DIR, "service.routes.json")

read_json_or <- function(path, default = list()) {
  if (!file.exists(path)) return(default)
  tryCatch(jsonlite::fromJSON(path, simplifyVector = FALSE), error = function(e) default)
}

PARAM_SCHEMA_JSON <- read_json_or(PARAM_SCHEMA_PATH, list())
RESULT_SCHEMA_JSON <- read_json_or(RESULT_SCHEMA_PATH, list())
SPEC_JSON <- read_json_or(SPEC_JSON_PATH, list())
UI_JSON <- read_json_or(UI_JSON_PATH, list())
ROUTES_JSON <- read_json_or(ROUTES_JSON_PATH, list(spec = "/spec", run = "/run"))

DEFAULT_ACCEPTS <- c("text/csv", "text/tab-separated-values", "text/plain", "application/octet-stream")
DEFAULT_UI <- list(requiresFile = TRUE, maxFiles = 1)

spec_handler_impl <- function() {
  name <- SPEC_JSON$name %||% "BrepPhylo"
  version <- SPEC_JSON$version %||% as.character(utils::packageVersion("BrepPhylo"))
  accepts <- SPEC_JSON$accepts; if (is.null(accepts) || !length(accepts)) accepts <- DEFAULT_ACCEPTS
  ui_hints <- modifyList(DEFAULT_UI, UI_JSON)

  list(
    id = METHOD_ID,
    name = name,
    version = version,
    accepts = accepts,
    paramSchema = PARAM_SCHEMA_JSON,
    uiHints = ui_hints
  )
}

ui_handler_impl <- function() UI_JSON
routes_handler_impl <- function() ROUTES_JSON
schema_handler_impl <- function() list(params = PARAM_SCHEMA_JSON, result = RESULT_SCHEMA_JSON)

fail <- function(msg, res, status = 400, logs = NULL, warnings = NULL) {
  if (is.null(res$status) || res$status == 200) res$status <- status
  list(
    ok = FALSE,
    error = msg,
    logs = logs,
    warnings = warnings %||% list()
  )
}

# ---------------------------
# Run BrepPhylo
# ---------------------------
run_handler_impl <- function(req, res) {
  tryCatch({
    body_raw <- req$postBody
    if (is.raw(body_raw)) body_raw <- rawToChar(body_raw)
    if (is.null(body_raw) || !nzchar(body_raw)) return(fail("Empty JSON body. Expected {\"file_path\": \"...\", \"params\": {...}}.", res))

    body <- tryCatch(jsonlite::fromJSON(body_raw, simplifyVector = FALSE), error = function(e) e)
    if (inherits(body, "error")) return(fail(paste0("Invalid JSON body: ", body$message), res))

    file_path <- body$file_path %||% NULL
    params <- body$params %||% list()

    if (is.null(file_path) || !nzchar(file_path)) return(fail("file_path is required.", res))
    if (!file.exists(file_path) || isTRUE(file.info(file_path)$isdir)) {
      return(fail(sprintf("file_path does not exist or is not a file: %s", file_path), res))
    }
    if (file.access(file_path, 4) != 0) {
      return(fail(sprintf("file_path is not readable: %s", file_path), res))
    }

    ext <- tolower(tools::file_ext(file_path))
    if (!ext %in% c("csv", "tsv", "txt")) {
      return(fail(sprintf("Unsupported file extension '%s'. Provide CSV/TSV.", ext), res))
    }

    df <- tryCatch(read_input_table(file_path), error = function(e) e)
    if (inherits(df, "error")) return(fail(paste("Failed to read input table:", df$message), res))
    if (!is.data.frame(df) || !nrow(df)) return(fail("Input table is empty.", res))

    warnings <- character(0)

    seq_col <- normalize_col(params$sequence_column, "sequence")
    clone_col <- normalize_col(params$clone_id_column, "clone_id")
    germ_col <- normalize_col(params$germline_id_column, "V.GENE.and.allele")
    class_col <- normalize_col(params$class_column, NULL)
    label_col <- normalize_col(params$label_column, NULL)

    required_cols <- c(seq_col, clone_col, germ_col)
    missing <- required_cols[!required_cols %in% names(df)]
    if (length(missing)) {
      return(fail(sprintf("Missing required column(s): %s", paste(missing, collapse = ", ")), res))
    }

    cleaned <- clean_input_df(df, seq_col, clone_col, germ_col)
    df <- cleaned$df
    warnings <- c(warnings, cleaned$warnings)
    if (!nrow(df)) {
      return(fail("All rows were dropped during preprocessing (empty sequence/clone/germline).", res))
    }

    if (!is.null(class_col) && !class_col %in% names(df)) {
      warnings <- c(warnings, sprintf("Class column '%s' not found; colouring disabled.", class_col))
      class_col <- NULL
    }
    if (!is.null(label_col) && !label_col %in% names(df)) {
      warnings <- c(warnings, sprintf("Label column '%s' not found; falling back to sequence order.", label_col))
      label_col <- NULL
    }

    # ----- Colour specification -----
    pal <- build_class_palette(df, class_col, params$class_palette)
    colourSpecification <- list(
      colours = pal,
      coloursColumn = class_col,
      germlineColour = params$germline_colour %||% "#808080"
    )

    # ----- Tree construction -----
    tree_type <- params$tree_type %||% "dnapars"
    tc_params <- list()

    if (identical(tree_type, "dnapars")) {
      tc_params$collapseAndReplace <- as_bool(params$collapse_and_replace, TRUE)

      # Prefer explicit DNAPARS_PATH, otherwise fall back to PATH.
      dnapars_exec <- Sys.getenv("DNAPARS_PATH", "")
      if (!nzchar(dnapars_exec)) {
        dnapars_exec <- Sys.which("dnapars")
      }
      if (nzchar(dnapars_exec)) {
        tc_params$executable <- dnapars_exec
      } else {
        warnings <- c(
          warnings,
          "DNAPARS executable not found in DNAPARS_PATH or PATH; BrepPhylo/treeConstruction will rely on its own defaults and may fail at runtime."
        )
      }
    } else if (identical(tree_type, "igphyml")) {
      # Accuracy preset for IgPhyML.
      acc <- params$igphyml_accuracy %||% "basic"
      if (nzchar(acc)) {
        tc_params$accuracy <- acc
      }

      # Get IgPhyML executable from env or fall back to 'igphyml' (like Dowser).
      igphyml_exec <- Sys.getenv("IGPHYML_BIN", "igphyml")
      if (!nzchar(igphyml_exec)) {
        igphyml_exec <- "igphyml"
      }
      tc_params$executable <- igphyml_exec
    }

    treeConstruction <- list(
      type = tree_type,
      parameters = tc_params
    )

    makeAlignmentPDFConstruction <- list(
      makeAlignmentPDF = as_bool(params$make_alignment_pdf, FALSE)
    )

    out_dir <- tempfile("brepphylo_", tmpdir = tempdir())
    dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

    log_vec <- character(0)
    min_clone_size <- as.integer(params$min_clone_size %||% 10L)
    species <- params$species %||% "Homo_sapiens"
    algorithm <- params$algorithm %||% "ClustalOmega"
    plot_type <- params$plot_type %||% "phylogram"
    plot_format <- params$plot_format %||% "png"
    if (!nzchar(species)) return(fail("species is required.", res))
    if (!nzchar(algorithm)) return(fail("algorithm is required.", res))
    if (!nzchar(plot_type)) return(fail("plot_type is required.", res))
    if (!nzchar(plot_format)) return(fail("plot_format is required.", res))
    allowed_alg <- c("ClustalOmega", "ClustalW")
    if (!algorithm %in% allowed_alg) {
      return(fail(sprintf("algorithm must be one of: %s", paste(allowed_alg, collapse = ", ")), res))
    }
    gather_plots <- as_bool(params$gather_plots, TRUE)
    use_temp_dir <- as_bool(params$use_temp_dir, TRUE)

    err <- tryCatch({
      log_vec <- capture.output({
        BrepPhylo::cloneLineage(
          input = df,
          outputFolder = out_dir,
          species = species,
          minCloneSize = min_clone_size,
          sequenceColumn = seq_col,
          cloneIdColumn = clone_col,
          germlineIdColumn = germ_col,
          labelColumn = if (!is.null(label_col) && nzchar(label_col)) label_col else NULL,
          algorithm = algorithm,
          whichClones = NULL,
          ignoreClones = NULL,
          colourSpecification = colourSpecification,
          plotType = plot_type,
          plotFormat = plot_format,
          gatherPlots = gather_plots,
          useTempDir = use_temp_dir,
          germlineSet = NULL,
          treeConstruction = treeConstruction,
          makeAlignmentPDFConstruction = makeAlignmentPDFConstruction
        )
      })
      NULL
    }, error = function(e) e)

    log_text <- paste(log_vec, collapse = "\n")
    log_entry <- list(list(step = "brepphylo.cloneLineage", ok = !inherits(err, "error"), out = log_text))

    if (inherits(err, "error")) {
      res$status <- 400
      return(list(ok = FALSE, error = conditionMessage(err), logs = log_entry, warnings = as.list(warnings)))
    }

    tree_files <- list.files(out_dir, pattern = "^clone_.*\\.tree$", recursive = TRUE, full.names = TRUE)
    if (!length(tree_files)) {
      res$status <- 500
      return(list(ok = FALSE, error = "BrepPhylo did not produce any .tree files.", logs = log_entry, warnings = as.list(warnings)))
    }

    tree_files <- sort(tree_files)
    trees <- vapply(tree_files, function(p) paste(readLines(p, warn = FALSE), collapse = ""), FUN.VALUE = character(1))
    clone_ids <- sub("^clone_", "", basename(tree_files))
    clone_ids <- sub("\\.tree$", "", clone_ids)

    plot_files <- list.files(out_dir, pattern = paste0("\\.", plot_format, "$"), recursive = TRUE, full.names = TRUE)
    plot_files <- plot_files[grepl("clone_", basename(plot_files), fixed = TRUE)]

    png_data <- list(); pdf_data <- list()
    for (cid in clone_ids) {
      candidates <- plot_files[grepl(paste0("clone_", cid, "\\."), basename(plot_files))]
      if (!length(candidates)) {
        png_data[[cid]] <- NULL; pdf_data[[cid]] <- NULL; next
      }
      f <- candidates[[1]]
      sz <- file.info(f)$size
      if (is.na(sz) || sz <= 0) { png_data[[cid]] <- NULL; pdf_data[[cid]] <- NULL; next }
      raw <- readBin(f, what = "raw", n = sz)
      if (grepl("\\.png$", f, ignore.case = TRUE)) png_data[[cid]] <- paste0("data:image/png;base64,", jsonlite::base64_enc(raw))
      if (grepl("\\.pdf$", f, ignore.case = TRUE)) pdf_data[[cid]] <- jsonlite::base64_enc(raw)
    }

    phylogeny_png <- unname(png_data[clone_ids])
    phylogeny_pdf <- unname(pdf_data[clone_ids])
    annotations <- lapply(clone_ids, function(cid) make_annotations_per_clone(df, cid, clone_col, label_col, class_col))

    clone_counts <- clone_seq_counts(df, clone_col, clone_ids)
    clones_meta <- list(clone_id = unname(clone_ids), seqs = unname(clone_counts))

    stats <- list(
      method = METHOD_ID,
      tree_type = tree_type,
      species = species,
      algorithm = algorithm,
      plot_type = plot_type,
      plot_format = plot_format,
      min_clone_size = min_clone_size,
      gather_plots = gather_plots,
      use_temp_dir = use_temp_dir,
      sequence_column = seq_col,
      clone_id_column = clone_col,
      germline_id_column = germ_col,
      class_column = class_col,
      label_column = label_col,
      n_clones = length(clone_ids),
      n_trees = length(trees)
    )

    result <- list(
      ok = TRUE,
      trees = unname(trees),
      figures = list(
        phylogeny = phylogeny_png,
        phylogeny_pdf = phylogeny_pdf
      ),
      annotations = annotations,
      clones = clones_meta,
      stats = stats,
      warnings = unname(as.list(warnings)),
      logs = log_entry,
      render = "phylogeny",
      error = NULL
    )

    return(result)
  }, error = function(e) {
    logf("[brepphylo][ERROR] %s", as.character(e))
    fail(as.character(e), res, status = ifelse(is.null(res$status) || res$status == 200, 500, res$status))
  })
}

STRICT_CONTRACT <- tolower(Sys.getenv("STRICT_CONTRACT_ROUTES", "true")) %in% c("1", "true", "yes")

#* @plumber
function(pr) {
  if (!STRICT_CONTRACT) {
    pr$handle("GET", "/spec", serializer = SER, function(req, res) spec_handler_impl())
    pr$handle("POST", "/run", serializer = SER, function(req, res) run_handler_impl(req, res))
  }
  pr$handle("GET", ROUTES_JSON$spec, serializer = SER, function(req, res) spec_handler_impl())
  pr$handle("POST", ROUTES_JSON$run, serializer = SER, function(req, res) run_handler_impl(req, res))
  pr$handle("GET", "/ui", serializer = SER, function(req, res) ui_handler_impl())
  pr$handle("GET", "/routes", serializer = SER, function(req, res) routes_handler_impl())
  pr$handle("GET", "/schema", serializer = SER, function(req, res) schema_handler_impl())
  pr$handle("GET", "/ping", serializer = SER, function(req, res) {
    list(ok = TRUE, method = METHOD_ID, brepphylo_version = as.character(utils::packageVersion("BrepPhylo")))
  })

  pr_set_error(pr, function(req, res, err) {
    res$status <- 500
    list(ok = FALSE, error = as.character(err))
  })
  pr
}
