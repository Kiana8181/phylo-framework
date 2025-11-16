#* @apiTitle BrepPhylo microservice
#* @apiDescription Build BCR lineage trees with BrepPhylo::cloneLineage.

library(plumber)

SER <- plumber::serializer_json(
  auto_unbox = TRUE,
  null = "null",
  na = "null",
  dataframe = "rows"
)

library(jsonlite)
library(BrepPhylo)
library(ape)
library(Biostrings)
library(igraph)

# ---------------------------
# Helpers
# ---------------------------

`%||%` <- function(x, y) if (!is.null(x)) x else y

as_bool <- function(x, default = FALSE) {
  if (is.null(x)) return(default)
  if (is.logical(x)) return(isTRUE(x))
  if (is.numeric(x)) return(x != 0)
  if (is.character(x)) {
    lx <- tolower(x)
    return(lx %in% c("1", "true", "t", "yes", "y"))
  }
  default
}

read_input_table <- function(path) {
  ext <- tolower(tools::file_ext(path))
  if (ext %in% c("csv")) {
    read.csv(path, stringsAsFactors = FALSE)
  } else if (ext %in% c("tsv", "txt")) {
    read.delim(path, stringsAsFactors = FALSE)
  } else {
    # Best effort
    tryCatch(
      read.csv(path, stringsAsFactors = FALSE),
      error = function(e) {
        read.delim(path, stringsAsFactors = FALSE)
      }
    )
  }
}

build_class_palette <- function(df, class_col, class_palette_param) {
  # class_palette_param will usually be a data.frame from JSON: fields 'level', 'color'
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

  # Fallback: auto-generate palette from data
  if (!class_col %in% names(df)) {
    return(list())
  }
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
      trimws(as.character(row[[label_col]]))
    } else {
      as.character(i)
    }

    a <- as.list(row[1, , drop = FALSE])
    a$label <- label
    annos[[i]] <- a
  }

  annos
}

# ---------------------------
# Config & Contracts loading
# ---------------------------

METHOD_ID <- "brepphylo"
CONTRACTS_DIR <- Sys.getenv("CONTRACTS_DIR", "packages/contracts")
METHOD_DIR <- file.path(CONTRACTS_DIR, "methods", METHOD_ID)

PARAM_SCHEMA_PATH  <- file.path(METHOD_DIR, "param.schema.json")
RESULT_SCHEMA_PATH <- file.path(METHOD_DIR, "result.schema.json")
SPEC_JSON_PATH     <- file.path(METHOD_DIR, "spec.json")
UI_JSON_PATH       <- file.path(METHOD_DIR, "ui.json")
ROUTES_JSON_PATH   <- file.path(METHOD_DIR, "service.routes.json")

.read_json <- function(path, default = list()) {
  if (!file.exists(path)) return(default)
  tryCatch(
    jsonlite::fromJSON(path, simplifyVector = FALSE),
    error = function(e) default
  )
}

PARAM_SCHEMA_JSON  <- .read_json(PARAM_SCHEMA_PATH, list())
RESULT_SCHEMA_JSON <- .read_json(RESULT_SCHEMA_PATH, list())
SPEC_JSON          <- .read_json(SPEC_JSON_PATH, list())
UI_JSON            <- .read_json(UI_JSON_PATH, list())
ROUTES_JSON        <- .read_json(ROUTES_JSON_PATH, list())

# ---------------------------
# Basic endpoints
# ---------------------------

#* Health check
#* @serializer SER
#* @get /ping
function() {
  list(
    ok = TRUE,
    method = METHOD_ID,
    brepphylo_version = as.character(utils::packageVersion("BrepPhylo"))
  )
}

#* Method spec
#* @serializer SER
#* @get /spec
function() {
  SPEC_JSON
}

#* UI hints
#* @serializer SER
#* @get /ui
function() {
  UI_JSON
}

#* Service routes
#* @serializer SER
#* @get /routes
function() {
  ROUTES_JSON
}

#* Parameter & result schema
#* @serializer SER
#* @get /schema
function() {
  list(
    params = PARAM_SCHEMA_JSON,
    result = RESULT_SCHEMA_JSON
  )
}

# ---------------------------
# Run BrepPhylo
# ---------------------------

#* Run BrepPhylo cloneLineage
#* @param params JSON encoded parameters (string) or object in JSON body
#* @param file:file Input AIRR / rearrangement table (CSV/TSV)
#* @post /run
#* @serializer SER
function(req, params = NULL, file = NULL) {
  # ----- Parse params -----
  prms <- list()

  # Case 1: multipart form: params as character
  if (!is.null(params) && is.character(params) && nzchar(params)) {
    prms <- jsonlite::fromJSON(params, simplifyVector = TRUE)
  } else if (length(req$bodyRaw) > 0) {
    # Case 2: pure JSON body: { "params": { ... }, "filePath": "..."}
    body <- tryCatch(
      jsonlite::fromJSON(rawToChar(req$bodyRaw), simplifyVector = TRUE),
      error = function(e) NULL
    )
    if (!is.null(body)) {
      if (!is.null(body$params)) {
        prms <- body$params
      } else {
        prms <- body
      }
      if (is.null(file) && !is.null(body$filePath)) {
        # Optional: if runs service passes a path instead of upload
        file <- list(datapath = body$filePath, filename = basename(body$filePath))
      }
    }
  }

  # ----- Resolve file path -----
  if (is.null(file)) {
    stop("No input file provided.")
  }

  input_path <- file$datapath %||% file$filename
  if (is.null(input_path) || !file.exists(input_path)) {
    stop("Uploaded file not found on server.")
  }

  # ----- Read input table -----
  df <- read_input_table(input_path)

  # Required columns
  seq_col   <- prms$sequence_column   %||% "sequence"
  clone_col <- prms$clone_id_column   %||% "clone_id"
  germ_col  <- prms$germline_id_column %||% "V.GENE.and.allele"
  label_col <- prms$label_column      %||% NULL
  class_col <- prms$class_column      %||% "class"

  for (cname in c(seq_col, clone_col, germ_col, class_col)) {
    if (!cname %in% names(df)) {
      stop(sprintf("Required column '%s' not found in input table.", cname))
    }
  }

  # ----- Colour specification -----
  pal <- build_class_palette(df, class_col, prms$class_palette)
  colourSpecification <- list(
    colours = pal,
    coloursColumn = class_col,
    germlineColour = prms$germline_colour %||% "#808080"
  )

  # ----- Tree construction config -----
  tree_type <- prms$tree_type %||% "dnapars"
  tc_params <- list()

  if (identical(tree_type, "dnapars")) {
    tc_params$collapseAndReplace <- as_bool(prms$collapse_and_replace, TRUE)
    dnapars_path <- Sys.getenv("DNAPARS_PATH", "")
    if (nzchar(dnapars_path)) {
      tc_params$executable <- dnapars_path
    }
  } else if (identical(tree_type, "igphyml")) {
    tc_params$accuracy <- prms$igphyml_accuracy %||% "basic"
    igphyml_exec <- Sys.getenv("IGPHYML_BIN", "igphyml")
    tc_params$executable <- igphyml_exec
  }

  treeConstruction <- list(
    type = tree_type,
    parameters = tc_params
  )

  makeAlignmentPDFConstruction <- list(
    makeAlignmentPDF = as_bool(prms$make_alignment_pdf, FALSE)
  )

  # ----- Output directory -----
  out_dir <- tempfile("brepphylo_", tmpdir = tempdir())
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

  # ----- Run cloneLineage with captured log -----
  log_vec <- character(0)
  err <- NULL

  min_clone_size <- as.integer(prms$min_clone_size %||% 10L)
  species <- prms$species %||% "Homo_sapiens"
  algorithm <- prms$algorithm %||% "ClustalOmega"
  plot_type <- prms$plot_type %||% "phylogram"
  plot_format <- prms$plot_format %||% "png"
  gather_plots <- as_bool(prms$gather_plots, TRUE)
  use_temp_dir <- as_bool(prms$use_temp_dir, TRUE)

  # The function writes output into out_dir and returns invisibly.
  err <- tryCatch(
    {
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
    },
    error = function(e) e
  )

  log_text <- paste(log_vec, collapse = "\n")

  if (inherits(err, "error")) {
    return(list(
      success = FALSE,
      method = METHOD_ID,
      error = conditionMessage(err),
      log = log_text
    ))
  }

  # ----- Collect tree files -----
  tree_files <- list.files(
    out_dir,
    pattern = "^clone_.*\\.tree$",
    recursive = TRUE,
    full.names = TRUE
  )

  if (!length(tree_files)) {
    return(list(
      success = FALSE,
      method = METHOD_ID,
      error = "BrepPhylo did not produce any .tree files.",
      log = log_text
    ))
  }

  tree_files <- sort(tree_files)
  trees <- vapply(
    tree_files,
    function(p) paste(readLines(p, warn = FALSE), collapse = ""),
    FUN.VALUE = character(1)
  )

  clone_ids <- sub("^clone_", "", basename(tree_files))
  clone_ids <- sub("\\.tree$", "", clone_ids)

  # ----- Collect figures -----
  plot_files <- list.files(
    out_dir,
    pattern = paste0("\\.", plot_format, "$"),
    recursive = TRUE,
    full.names = TRUE
  )
  # Heuristic: keep only 'clone_' plots
  plot_files <- plot_files[grepl("clone_", basename(plot_files), fixed = TRUE)]

  png_data <- list()
  pdf_data <- list()

  for (cid in clone_ids) {
    candidates <- plot_files[grepl(paste0("clone_", cid, "\\."), basename(plot_files))]
    if (!length(candidates)) {
      png_data[[cid]] <- NULL
      pdf_data[[cid]] <- NULL
      next
    }
    # Take the first match
    f <- candidates[[1]]
    sz <- file.info(f)$size
    if (is.na(sz) || sz <= 0) {
      png_data[[cid]] <- NULL
      pdf_data[[cid]] <- NULL
      next
    }
    raw <- readBin(f, what = "raw", n = sz)
    if (grepl("\\.png$", f, ignore.case = TRUE)) {
      png_data[[cid]] <- paste0("data:image/png;base64,", jsonlite::base64_enc(raw))
    } else if (grepl("\\.pdf$", f, ignore.case = TRUE)) {
      pdf_data[[cid]] <- jsonlite::base64_enc(raw)
    }
  }

  phylogeny_png <- unname(png_data[clone_ids])
  phylogeny_pdf <- unname(pdf_data[clone_ids])

  # ----- Build annotations -----
  annotations <- lapply(clone_ids, function(cid) {
    make_annotations_per_clone(df, cid, clone_col, label_col, class_col)
  })

  # ----- Assemble result -----
  result <- list(
    success = TRUE,
    method = METHOD_ID,
    clone_ids = unname(clone_ids),
    trees = unname(trees),
    figures = list(
      phylogeny = phylogeny_png,
      phylogeny_pdf = phylogeny_pdf
    ),
    annotations = annotations,
    log = log_text
  )

  result
}
