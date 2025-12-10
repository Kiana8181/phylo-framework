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
`%||%` <- function(x, y) {
  if (!is.null(x) && !(is.character(x) && length(x) == 1 && is.na(x))) x else y
}

logf <- function(...) {
  cat(sprintf(...), "\n", file = stderr())
}

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

# Parse vectors from JSON / string ("a,b c;d") – same idea as Dowser
parse_vec <- function(x) {
  if (is.null(x)) return(character(0))
  if (is.list(x)) x <- unlist(x, use.names = FALSE)
  x <- as.character(x)
  if (length(x) == 1L) {
    s <- trimws(x)
    if (nzchar(s)) {
      x <- unlist(strsplit(s, "[,;\\s]+", perl = TRUE), use.names = FALSE)
    } else {
      x <- character(0)
    }
  }
  x <- trimws(x)
  unique(x[nzchar(x)])
}

# build a palette from a class column only (no user-supplied palette)
build_class_palette <- function(df, class_col) {
  if (is.null(class_col) || !nzchar(class_col)) return(list())
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
# Sequence / IgPhyML helpers (Dowser-style, adapted)
# ---------------------------
IUPAC        <- "ACGTRYSWKMBDHVN"
gap_re       <- "[-\\.\\s]"
non_iupac_re <- "[^ACGTRYSWKMBDHVN]"

apply_text_filters <- function(df, seq_col, p) {
  if (!seq_col %in% names(df)) {
    return(list(
      df    = df,
      stats = list(upper = 0L, gap_rows = 0L, noniupac_rows = 0L),
      dropped = integer(0)
    ))
  }

  s <- as.character(df[[seq_col]])
  s[is.na(s)] <- ""
  stats <- list(upper = 0L, gap_rows = 0L, noniupac_rows = 0L)
  drop_mask <- rep(FALSE, nrow(df))

  # Uppercase
  if (isTRUE(p$uppercase)) {
    s2 <- toupper(s)
    stats$upper <- sum(s2 != s, na.rm = TRUE)
    s <- s2
  }

  # Gap policy
  has_gap <- grepl(gap_re, s, perl = TRUE)
  stats$gap_rows <- sum(has_gap, na.rm = TRUE)
  if (p$gap_policy == "remove") {
    s <- gsub(gap_re, "", s, perl = TRUE)
  } else if (p$gap_policy == "replace_N") {
    s <- gsub(gap_re, "N", s, perl = TRUE)
  } else if (p$gap_policy == "replace_NNN") {
    s <- gsub(gap_re, "NNN", s, perl = TRUE)
  } else if (p$gap_policy == "drop_row") {
    drop_mask <- drop_mask | has_gap
  }

  # Non-IUPAC policy
  bad_non <- grepl(non_iupac_re, s, perl = TRUE)
  stats$noniupac_rows <- sum(bad_non, na.rm = TRUE)
  if (p$noniupac_policy == "replace_N") {
    s <- gsub(noniupac_re, "N", s, perl = TRUE)
  } else if (p$noniupac_policy == "drop_row") {
    drop_mask <- drop_mask | bad_non
  }

  df[[seq_col]] <- s
  if (any(drop_mask)) df <- df[!drop_mask, , drop = FALSE]

  list(df = df, stats = stats, dropped = which(drop_mask))
}

detect_stops_and_frame <- function(seq_vec) {
  x <- toupper(gsub(gap_re, "", as.character(seq_vec), perl = TRUE))
  x[is.na(x)] <- ""
  frame_bad <- (nchar(x) %% 3) != 0
  stop_bad  <- logical(length(x))
  ok <- !frame_bad & nzchar(x)
  if (any(ok)) {
    aa <- translate(DNAStringSet(x[ok]), if.fuzzy.codon = "X")
    stop_bad[ok] <- grepl("\\*", as.character(aa))
  }
  list(stop = stop_bad, frame_bad = frame_bad)
}

# ---------------------------
# IgPhyML exec + motifs (Dowser-style, env-driven)
# ---------------------------
IG_EXEC_DEFAULT   <- Sys.getenv("IGPHYML_BIN", "igphyml")
IG_MOTIFS_DEFAULT <- Sys.getenv("IGPHYML_MOTIFS", "")

validate_motifs_dir <- function(path) {
  if (!nzchar(path)) return(FALSE)
  if (!dir.exists(path)) return(FALSE)
  length(list.files(path, all.files = FALSE)) > 0
}

check_igphyml_exec <- function(user_exec = NULL) {
  # We don't take user path from params, only env/ PATH.
  cand <- user_exec %||% Sys.which("igphyml")
  if (!nzchar(cand)) {
    # Try a common default
    default <- "/usr/local/share/igphyml/src/igphyml"
    if (file.exists(default) && file.access(default, 1) == 0) cand <- default
  }
  if (!nzchar(cand)) {
    stop("IgPhyML executable not found. Set IGPHYML_BIN or put 'igphyml' on PATH.")
  }
  path <- normalizePath(cand, mustWork = FALSE)
  if (!file.exists(path)) {
    stop(sprintf("IgPhyML path does not exist: %s", path))
  }
  if (file.access(path, 1) != 0) {
    stop(sprintf("IgPhyML path is not executable: %s (chmod +x?)", path))
  }
  # Optional version logging
  try({
    v <- suppressWarnings(system2(path, "--version", stdout = TRUE, stderr = TRUE))
    logf("[brepphylo] igphyml --version: %s", paste(v, collapse = " | "))
  }, silent = TRUE)
  path
}

resolve_igphyml <- function(require_ok = TRUE) {
  exec_path <- tryCatch(
    check_igphyml_exec(IG_EXEC_DEFAULT),
    error = function(e) if (require_ok) stop(e) else NULL
  )
  if (is.null(exec_path)) {
    return(list(
      ok    = FALSE,
      error = "IgPhyML executable not found. Set IGPHYML_BIN or install 'igphyml' on PATH."
    ))
  }

  candidates <- unique(c(
    Sys.getenv("IGPHYML_MOTIFS", ""),
    Sys.getenv("IGPHYML_PATH", ""),
    IG_MOTIFS_DEFAULT,
    file.path(dirname(dirname(exec_path)), "share", "igphyml", "src", "motifs"),
    "/usr/local/share/igphyml/src/motifs",
    "/usr/share/igphyml/src/motifs",
    "/opt/igphyml/src/motifs"
  ))

  motifs_dir <- NULL
  for (d in candidates) {
    if (validate_motifs_dir(d)) {
      motifs_dir <- d
      break
    }
  }

  if (is.null(motifs_dir)) {
    if (require_ok) {
      tried <- paste(Filter(nzchar, candidates), collapse = " | ")
      return(list(
        ok    = FALSE,
        error = paste0(
          "IgPhyML hotspot motif tables not found. ",
          "Set IGPHYML_MOTIFS or IGPHYML_PATH to the directory containing motif tables ",
          "(e.g., '/usr/local/share/igphyml/src/motifs'). ",
          "Tried: ", if (nzchar(tried)) tried else "<none>"
        )
      ))
    }
  } else {
    Sys.setenv(IGPHYML_MOTIFS = motifs_dir)
    Sys.setenv(IGPHYML_PATH   = motifs_dir)
    logf("[brepphylo] Using IgPhyML motifs dir: %s", motifs_dir)
  }

  list(ok = TRUE, exec = exec_path, motifs = motifs_dir)
}

normalize_opt_string <- function(x) {
  if (is.null(x)) return(NULL)
  x <- as.character(x[1])
  x <- trimws(x)
  if (!nzchar(x)) return(NULL)
  x
}

CLASS_UNKNOWN_DEFAULT <- "unknown"

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

read_json_or <- function(path, default = list()) {
  if (!file.exists(path)) return(default)
  tryCatch(jsonlite::fromJSON(path, simplifyVector = FALSE), error = function(e) default)
}

PARAM_SCHEMA_JSON  <- read_json_or(PARAM_SCHEMA_PATH, list())
RESULT_SCHEMA_JSON <- read_json_or(RESULT_SCHEMA_PATH, list())
SPEC_JSON          <- read_json_or(SPEC_JSON_PATH, list())
UI_JSON            <- read_json_or(UI_JSON_PATH, list())
ROUTES_JSON        <- read_json_or(ROUTES_JSON_PATH, list(spec = "/spec", run = "/run"))

DEFAULT_ACCEPTS <- c(
  "text/csv",
  "text/tab-separated-values",
  "text/plain",
  "application/octet-stream"
)
DEFAULT_UI <- list(requiresFile = TRUE, maxFiles = 1)

spec_handler_impl <- function() {
  name    <- SPEC_JSON$name    %||% "BrepPhylo"
  version <- SPEC_JSON$version %||% as.character(utils::packageVersion("BrepPhylo"))
  accepts <- SPEC_JSON$accepts
  if (is.null(accepts) || !length(accepts)) accepts <- DEFAULT_ACCEPTS
  ui_hints <- modifyList(DEFAULT_UI, UI_JSON)

  list(
    id          = METHOD_ID,
    name        = name,
    version     = version,
    accepts     = accepts,
    paramSchema = PARAM_SCHEMA_JSON,
    uiHints     = ui_hints
  )
}

ui_handler_impl     <- function() UI_JSON
routes_handler_impl <- function() ROUTES_JSON
schema_handler_impl <- function() list(params = PARAM_SCHEMA_JSON, result = RESULT_SCHEMA_JSON)

fail <- function(msg, res, status = 400, logs = NULL, warnings = NULL) {
  if (is.null(res$status) || res$status == 200) res$status <- status
  list(
    ok       = FALSE,
    error    = msg,
    logs     = logs %||% list(),
    warnings = warnings %||% list()
  )
}

# ---------------------------
# Run BrepPhylo
# ---------------------------
run_handler_impl <- function(req, res) {
  tryCatch({
    # ---- accumulators for pipeline diagnostics ----
    warnings <- character(0)
    logs <- list()
    add_log <- function(step, ok, out) {
      logs[[length(logs) + 1]] <<- list(step = step, ok = ok, out = out)
    }
    fail_local <- function(msg, status = 400) {
      fail(msg, res, status = status, logs = logs, warnings = as.list(warnings))
    }

    # ---- parse and validate JSON body ----
    body_raw <- req$postBody
    if (is.raw(body_raw)) body_raw <- rawToChar(body_raw)
    if (is.null(body_raw) || !nzchar(body_raw)) {
      return(fail_local('Empty JSON body. Expected {"file_path": "...", "params": {...}}.'))
    }

    body <- tryCatch(jsonlite::fromJSON(body_raw, simplifyVector = FALSE), error = function(e) e)
    if (inherits(body, "error")) {
      return(fail_local(paste0("Invalid JSON body: ", body$message)))
    }

    file_path <- body$file_path %||% NULL
    params    <- body$params    %||% list()

    if (is.null(file_path) || !nzchar(file_path)) {
      return(fail_local("file_path is required."))
    }
    if (!file.exists(file_path) || isTRUE(file.info(file_path)$isdir)) {
      return(fail_local(sprintf("file_path does not exist or is not a file: %s", file_path)))
    }
    if (file.access(file_path, 4) != 0) {
      return(fail_local(sprintf("file_path is not readable: %s", file_path)))
    }

    ext <- tolower(tools::file_ext(file_path))
    if (!ext %in% c("csv", "tsv", "txt")) {
      return(fail_local(sprintf("Unsupported file extension '%s'. Provide CSV/TSV.", ext)))
    }

    add_log(
      "brepphylo.request",
      TRUE,
      sprintf("Validated request; file_path=%s, ext=%s.", file_path, ext)
    )

    # ---- read input table ----
    df <- tryCatch(read_input_table(file_path), error = function(e) e)
    if (inherits(df, "error")) {
      return(fail_local(paste("Failed to read input table:", df$message)))
    }
    if (!is.data.frame(df) || !nrow(df)) {
      return(fail_local("Input table is empty."))
    }

    add_log(
      "brepphylo.readInput",
      TRUE,
      sprintf("Read input table with %d rows and %d columns.", nrow(df), ncol(df))
    )

    # ---- resolve columns ----
    seq_col   <- normalize_col(params$sequence_column,    "sequence")
    clone_col <- normalize_col(params$clone_id_column,    "clone_id")
    germ_col  <- normalize_col(params$germline_id_column, "V.GENE.and.allele")
    class_col <- normalize_col(params$class_column,       NULL)
    label_col <- normalize_col(params$label_column,       NULL)

    required_cols <- c(seq_col, clone_col, germ_col)
    missing <- required_cols[!required_cols %in% names(df)]
    if (length(missing)) {
      return(fail_local(sprintf("Missing required column(s): %s", paste(missing, collapse = ", "))))
    }

    # ---- parse additional params ----
    which_clones  <- parse_vec(params$which_clones  %||% params$whichClones)
    ignore_clones <- parse_vec(params$ignore_clones %||% params$ignoreClones)
    germline_set  <- normalize_opt_string(params$germline_set %||% params$germlineSet)

    apply_filters        <- as_bool(params$apply_filters, FALSE)
    uppercase            <- as_bool(params$uppercase, FALSE)
    gap_policy           <- params$gap_policy       %||% "keep"   # keep | remove | replace_N | replace_NNN | drop_row
    noniupac_policy      <- params$noniupac_policy  %||% "keep"   # keep | replace_N | drop_row
    max_class_categories <- as.integer(params$max_class_categories %||% 30L)

    allowed_gap <- c("keep", "remove", "replace_N", "replace_NNN", "drop_row")
    if (!gap_policy %in% allowed_gap) {
      return(fail_local(sprintf("gap_policy must be one of: %s", paste(allowed_gap, collapse = ", "))))
    }
    allowed_noni <- c("keep", "replace_N", "drop_row")
    if (!noniupac_policy %in% allowed_noni) {
      return(fail_local(sprintf("noniupac_policy must be one of: %s", paste(allowed_noni, collapse = ", "))))
    }

    tree_type <- params$tree_type %||% "dnapars"
    tree_type_effective <- tree_type

    ig_stop_policy <- params$ig_stop_policy %||% "drop_seqs"  # drop_seqs | fallback_dnapars | error
    allowed_ig <- c("drop_seqs", "fallback_dnapars", "error")
    if (!ig_stop_policy %in% allowed_ig) {
      return(fail_local(sprintf("ig_stop_policy must be one of: %s", paste(allowed_ig, collapse = ", "))))
    }

    igphyml_accuracy <- params$igphyml_accuracy %||% "basic"

    # ---- clean / filter DF (basic empties) ----
    cleaned <- clean_input_df(df, seq_col, clone_col, germ_col)
    df <- cleaned$df
    warnings <- c(warnings, cleaned$warnings)
    if (!nrow(df)) {
      add_log("brepphylo.preprocess", FALSE, "All rows were dropped during preprocessing.")
      return(fail_local("All rows were dropped during preprocessing (empty sequence/clone/germline)."))
    }

    add_log(
      "brepphylo.preprocess",
      TRUE,
      paste(
        c(
          sprintf("Preprocessed input table; remaining rows=%d.", nrow(df)),
          cleaned$warnings
        ),
        collapse = "\n"
      )
    )

    if (!is.null(class_col) && !class_col %in% names(df)) {
      warnings <- c(
        warnings,
        sprintf("Class column '%s' not found; colouring disabled.", class_col)
      )
      class_col <- NULL
    }
    if (!is.null(label_col) && !label_col %in% names(df)) {
      warnings <- c(
        warnings,
        sprintf("Label column '%s' not found; falling back to sequence order.", label_col)
      )
      label_col <- NULL
    }

    # ---- apply_filters (optional, on sequence column only) ----
    filter_stats <- list(upper = 0L, gap_rows = 0L, noniupac_rows = 0L)
    if (apply_filters) {
      ft <- apply_text_filters(
        df,
        seq_col,
        list(
          uppercase       = uppercase,
          gap_policy      = gap_policy,
          noniupac_policy = noniupac_policy
        )
      )
      df <- ft$df        # FIX: use df, not db
      filter_stats <- ft$stats
      if (!nrow(df)) {
        add_log("brepphylo.filters", FALSE, "All rows dropped by apply_filters.")
        return(fail_local("All rows were dropped by sequence filters (gaps / non-IUPAC)."))
      }

      add_log(
        "brepphylo.filters",
        TRUE,
        sprintf(
          paste(
            "apply_filters=TRUE; uppercase=%s; gap_policy=%s; noniupac_policy=%s;",
            "uppercased_rows=%d; gap_rows_touched=%d; noniupac_rows_touched=%d."
          ),
          uppercase, gap_policy, noniupac_policy,
          filter_stats$upper, filter_stats$gap_rows, filter_stats$noniupac_rows
        )
      )
    } else {
      add_log("brepphylo.filters", TRUE, "apply_filters=FALSE (no sequence text filters applied).")
    }

    # ---- class column handling: unknown + max_class_categories ----
    class_unknown_replaced <- 0L
    n_class_states <- 0L
    class_states_capped <- FALSE

    pal <- list()
    colour_col <- NULL

    if (!is.null(class_col)) {
      vals <- as.character(df[[class_col]])
      is_missing_class <- is.na(vals) | !nzchar(trimws(vals))
      if (any(is_missing_class)) {
        df[[class_col]] <- vals
        df[[class_col]][is_missing_class] <- CLASS_UNKNOWN_DEFAULT
        class_unknown_replaced <- sum(is_missing_class, na.rm = TRUE)
        warnings <- c(
          warnings,
          sprintf(
            "Class column '%s' had %d empty/NA values -> set to '%s' for colouring.",
            class_col, class_unknown_replaced, CLASS_UNKNOWN_DEFAULT
          )
        )
      }

      vals2 <- as.character(df[[class_col]])
      class_states <- sort(unique(vals2[!is.na(vals2)]))
      n_class_states <- length(class_states)

      if (n_class_states > max_class_categories) {
        class_states_capped <- TRUE
        warnings <- c(
          warnings,
          sprintf(
            "Class column '%s' has %d unique values (> max_class_categories=%d); colouring will be disabled.",
            class_col, n_class_states, max_class_categories
          )
        )
        # leave pal empty and colour_col NULL -> no colouring
      } else {
        pal <- build_class_palette(df, class_col)
        colour_col <- if (length(pal)) class_col else NULL
      }
    }

    # ---- colour specification ----
    colourSpecification <- NULL
    if (!is.null(colour_col) && length(pal) > 0L) {
      colourSpecification <- list(
        colours        = pal,
        coloursColumn  = colour_col,
        germlineColour = params$germline_colour %||% "#808080"
      )
    } else {
      # No colouring -> let BrepPhylo use its defaults
      colourSpecification <- NULL
    }

    # ---- IgPhyML preflight: stops / frame ----
    ig_stop_rows  <- 0L
    ig_frame_rows <- 0L
    ig_fallback   <- FALSE

    if (identical(tree_type, "igphyml")) {
      det <- detect_stops_and_frame(df[[seq_col]])
      ig_stop_rows  <- sum(det$stop, na.rm = TRUE)
      ig_frame_rows <- sum(det$frame_bad, na.rm = TRUE)

      if (ig_stop_rows > 0L || ig_frame_rows > 0L) {
        if (ig_stop_policy == "drop_seqs") {
          keep <- !(det$stop | det$frame_bad)
          dropped <- sum(!keep, na.rm = TRUE)
          df <- df[keep, , drop = FALSE]
          warnings <- c(
            warnings,
            sprintf(
              "IgPhyML: dropped %d sequences with stop codons and %d out-of-frame sequences (policy=drop_seqs).",
              ig_stop_rows, ig_frame_rows
            )
          )
          if (!nrow(df)) {
            add_log("brepphylo.igphymlPreflight", FALSE,
                    "All sequences removed by IgPhyML preflight (stops/frame).")
            return(fail_local(
              sprintf(
                "All sequences removed for IgPhyML: %d had stop codons and %d were out-of-frame.",
                ig_stop_rows, ig_frame_rows
              )
            ))
          }
        } else if (ig_stop_policy == "fallback_dnapars") {
          tree_type_effective <- "dnapars"
          ig_fallback <- TRUE
          warnings <- c(
            warnings,
            sprintf(
              "IgPhyML fallback: switched to 'dnapars' because %d sequences had stop codons and %d were out-of-frame (policy=fallback_dnapars).",
              ig_stop_rows, ig_frame_rows
            )
          )
        } else { # "error"
          add_log("brepphylo.igphymlPreflight", FALSE,
                  sprintf("IgPhyML blocked: stops=%d, frame=%d (policy=error).", ig_stop_rows, ig_frame_rows))
          return(fail_local(
            sprintf(
              "IgPhyML blocked: %d sequences contain stop codons and %d are out-of-frame (ig_stop_policy=error).",
              ig_stop_rows, ig_frame_rows
            )
          ))
        }
      }

      add_log(
        "brepphylo.igphymlPreflight",
        TRUE,
        sprintf(
          "IgPhyML preflight: stop_rows=%d, frame_rows=%d, policy=%s, fallback_to_dnapars=%s.",
          ig_stop_rows, ig_frame_rows, ig_stop_policy, ig_fallback
        )
      )
    }

    # ---- tree construction config (env-based executables) ----
    tree_type_effective <- tree_type_effective %||% tree_type
    tc_params <- list()

    if (identical(tree_type_effective, "dnapars")) {
      tc_params$collapseAndReplace <- as_bool(params$collapse_and_replace, TRUE)

      # prefer DNAPARS_PATH; fallback to PATH; let cloneLineage validate if still missing
      dnapars_exec <- Sys.getenv("DNAPARS_PATH", "")
      if (!nzchar(dnapars_exec)) {
        dnapars_exec <- Sys.which("dnapars")
      }
      if (nzchar(dnapars_exec)) {
        tc_params$executable <- dnapars_exec
        add_log("brepphylo.dnapars.exec", TRUE,
                sprintf("Using DNAPARS executable: %s", dnapars_exec))
      } else {
        warnings <- c(
          warnings,
          "DNAPARS executable not found in DNAPARS_PATH or PATH; BrepPhylo will try its own lookup and may fail."
        )
        add_log("brepphylo.dnapars.exec", FALSE,
                "DNAPARS executable not found in DNAPARS_PATH or PATH.")
      }
    } else if (identical(tree_type_effective, "igphyml")) {
      if (nzchar(igphyml_accuracy)) {
        tc_params$accuracy <- igphyml_accuracy
      }

      resolved <- resolve_igphyml(require_ok = TRUE)
      if (!isTRUE(resolved$ok)) {
        return(fail_local(resolved$error))
      }
      tc_params$executable <- resolved$exec
      add_log(
        "brepphylo.igphyml.exec",
        TRUE,
        sprintf(
          "Using IgPhyML exec=%s; motifs=%s",
          resolved$exec, resolved$motifs %||% "<none>"
        )
      )
    }

    treeConstruction <- list(
      type       = tree_type_effective,
      parameters = tc_params
    )

    makeAlignmentPDFConstruction <- list(
      makeAlignmentPDF = as_bool(params$make_alignment_pdf, FALSE)
    )

    # ---- other params ----
    out_dir <- tempfile("brepphylo_", tmpdir = tempdir())
    dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

    min_clone_size <- as.integer(params$min_clone_size %||% 10L)
    species        <- params$species   %||% "Homo_sapiens"
    algorithm      <- params$algorithm %||% "ClustalOmega"
    plot_type      <- params$plot_type %||% "phylogram"
    plot_format    <- params$plot_format %||% "png"

    if (!nzchar(species))      return(fail_local("species is required."))
    if (!nzchar(algorithm))    return(fail_local("algorithm is required."))
    if (!nzchar(plot_type))    return(fail_local("plot_type is required."))
    if (!nzchar(plot_format))  return(fail_local("plot_format is required."))

    allowed_alg <- c("ClustalOmega", "ClustalW")
    if (!algorithm %in% allowed_alg) {
      return(fail_local(sprintf("algorithm must be one of: %s",
                                paste(allowed_alg, collapse = ", "))))
    }

    gather_plots <- as_bool(params$gather_plots, TRUE)
    use_temp_dir <- as_bool(params$use_temp_dir, TRUE)

    # ---- run BrepPhylo::cloneLineage with captured output ----
    log_vec <- character(0)
    err <- tryCatch({
      log_vec <- capture.output({
        BrepPhylo::cloneLineage(
          input        = df,
          outputFolder = out_dir,
          species      = species,
          minCloneSize = min_clone_size,
          sequenceColumn   = seq_col,
          cloneIdColumn    = clone_col,
          germlineIdColumn = germ_col,
          labelColumn      = if (!is.null(label_col) && nzchar(label_col)) label_col else NULL,
          algorithm        = algorithm,
          whichClones      = if (length(which_clones)) which_clones else NULL,
          ignoreClones     = if (length(ignore_clones)) ignore_clones else NULL,
          colourSpecification = colourSpecification,
          plotType         = plot_type,
          plotFormat       = plot_format,
          gatherPlots      = gather_plots,
          useTempDir       = use_temp_dir,
          germlineSet      = germline_set,
          treeConstruction = treeConstruction,
          makeAlignmentPDFConstruction = makeAlignmentPDFConstruction
        )
      })
      NULL
    }, error = function(e) e)

    log_text <- paste(log_vec, collapse = "\n")
    add_log("brepphylo.cloneLineage", !inherits(err, "error"), log_text)

    if (inherits(err, "error")) {
      res$status <- 400
      return(list(
        ok       = FALSE,
        error    = conditionMessage(err),
        logs     = logs,
        warnings = as.list(warnings)
      ))
    }

    # ---- collect trees ----
    tree_files <- list.files(
      out_dir,
      pattern   = "^clone_.*\\.tree$",
      recursive = TRUE,
      full.names = TRUE
    )
    if (!length(tree_files)) {
      res$status <- 500
      add_log("brepphylo.collectTrees", FALSE,
              "No .tree files were produced by BrepPhylo.")
      return(list(
        ok       = FALSE,
        error    = "BrepPhylo did not produce any .tree files.",
        logs     = logs,
        warnings = as.list(warnings)
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

    # ---- collect figures (tree images) ----
    plot_files <- list.files(
      out_dir,
      pattern   = paste0("\\.", plot_format, "$"),
      recursive = TRUE,
      full.names = TRUE
    )
    plot_files <- plot_files[grepl("clone_", basename(plot_files), fixed = TRUE)]

    png_data <- list()
    pdf_data <- list()
    for (cid in clone_ids) {
      candidates <- plot_files[grepl(paste0("clone_", cid, "\\."),
                                     basename(plot_files))]
      if (!length(candidates)) {
        png_data[[cid]] <- NULL
        pdf_data[[cid]] <- NULL
        next
      }
      f <- candidates[[1]]
      sz <- file.info(f)$size
      if (is.na(sz) || sz <= 0) {
        png_data[[cid]] <- NULL
        pdf_data[[cid]] <- NULL
        next
      }
      raw <- readBin(f, what = "raw", n = sz)
      if (grepl("\\.png$", f, ignore.case = TRUE)) {
        # plain base64 – frontend will prepend "data:image/png;base64,"
        png_data[[cid]] <- jsonlite::base64_enc(raw)
      }
      if (grepl("\\.pdf$", f, ignore.case = TRUE)) {
        pdf_data[[cid]] <- jsonlite::base64_enc(raw)
      }
    }

    phylogeny_png <- unname(png_data[clone_ids])
    phylogeny_pdf <- unname(pdf_data[clone_ids])

    # ---- annotations per clone ----
    annotations <- lapply(
      clone_ids,
      function(cid) make_annotations_per_clone(df, cid, clone_col, label_col, class_col)
    )

    # ---- clones meta and stats ----
    clone_counts <- clone_seq_counts(df, clone_col, clone_ids)

    # IMPORTANT: keep these as arrays even for length 1 to avoid auto_unbox
    clones_meta <- list(
      clone_id = as.list(unname(clone_ids)),
      seqs     = as.list(unname(clone_counts))
    )

    stats <- list(
      method               = METHOD_ID,
      tree_type_requested  = tree_type,
      tree_type            = tree_type_effective,
      species              = species,
      algorithm            = algorithm,
      plot_type            = plot_type,
      plot_format          = plot_format,
      min_clone_size       = min_clone_size,
      gather_plots         = gather_plots,
      use_temp_dir         = use_temp_dir,
      sequence_column      = seq_col,
      clone_id_column      = clone_col,
      germline_id_column   = germ_col,
      class_column         = class_col,
      label_column         = label_col,
      which_clones         = which_clones,
      ignore_clones        = ignore_clones,
      germline_set         = germline_set,
      n_clones             = length(clone_ids),
      n_trees              = length(trees),

      # colouring stats
      class_unknown_value             = CLASS_UNKNOWN_DEFAULT,
      class_unknown_replaced_in_input = class_unknown_replaced,
      class_n_states                  = n_class_states,
      class_states_capped             = class_states_capped,
      max_class_categories            = max_class_categories,

      # filter stats
      filters_applied       = apply_filters,
      uppercased_rows       = filter_stats$upper,
      gap_rows_touched      = filter_stats$gap_rows,
      noniupac_rows_touched = filter_stats$noniupac_rows,
      gap_policy            = gap_policy,
      noniupac_policy       = noniupac_policy,

      # IgPhyML stats
      ig_stop_policy              = ig_stop_policy,
      igphyml_stop_rows           = ig_stop_rows,
      igphyml_frame_rows          = ig_frame_rows,
      igphyml_fallback_to_dnapars = ig_fallback
    )

    add_log(
      "brepphylo.summarise",
      TRUE,
      sprintf("Built %d trees for %d clones.", length(trees), length(clone_ids))
    )

    # ---- build artifacts ZIP with all other files (per-clone folders etc.) ----
    artifacts_zip_b64 <- NULL
    all_files <- list.files(out_dir, recursive = TRUE, full.names = TRUE)

    if (length(all_files)) {
      # Exclude tree and main plot files (we already return them)
      exclude_basenames <- unique(c(
        paste0("clone_", clone_ids, ".tree"),
        paste0("clone_", clone_ids, ".png"),
        paste0("clone_", clone_ids, ".pdf")
      ))

      files_to_zip <- all_files[!(basename(all_files) %in% exclude_basenames)]

      if (length(files_to_zip)) {
        zip_path <- file.path(out_dir, "brepphylo_artifacts.zip")
        if (file.exists(zip_path)) {
          file.remove(zip_path)
        }

        old_wd <- getwd()
        setwd(out_dir)
        on.exit(setwd(old_wd), add = TRUE)

        rel_paths <- unique(gsub(paste0("^", out_dir, "/?"), "", files_to_zip))
        rel_paths <- rel_paths[nzchar(rel_paths)]

        if (length(rel_paths)) {
          utils::zip(zipfile = zip_path, files = rel_paths)
          sz <- file.info(zip_path)$size
          if (!is.na(sz) && sz > 0) {
            zip_raw <- readBin(zip_path, what = "raw", n = sz)
            artifacts_zip_b64 <- jsonlite::base64_enc(zip_raw)
            add_log(
              "brepphylo.artifacts",
              TRUE,
              sprintf("Zipped %d files into brepphylo_artifacts.zip (%d bytes).",
                      length(rel_paths), sz)
            )
          } else {
            add_log(
              "brepphylo.artifacts",
              FALSE,
              "brepphylo_artifacts.zip was created but has zero size."
            )
          }
        } else {
          add_log("brepphylo.artifacts", TRUE, "No extra files to zip (rel_paths empty).")
        }
      } else {
        add_log("brepphylo.artifacts", TRUE, "No extra files to zip (files_to_zip empty).")
      }
    } else {
      add_log("brepphylo.artifacts", TRUE, "No files found in output directory.")
    }

    # ---- warnings aggregation for filters ----
    if (apply_filters) {
      if (uppercase && filter_stats$upper > 0L) {
        warnings <- c(warnings, sprintf("Uppercased %d rows in '%s'.", filter_stats$upper, seq_col))
      }
      if (gap_policy == "remove" && filter_stats$gap_rows > 0L) {
        warnings <- c(warnings, sprintf("Removed gaps in %d rows.", filter_stats$gap_rows))
      }
      if (gap_policy %in% c("replace_N", "replace_NNN") && filter_stats$gap_rows > 0L) {
        warnings <- c(warnings, sprintf("Replaced gaps in %d rows.", filter_stats$gap_rows))
      }
      if (gap_policy == "drop_row" && filter_stats$gap_rows > 0L) {
        warnings <- c(warnings, sprintf("Dropped %d rows due to gap characters.", filter_stats$gap_rows))
      }
      if (noniupac_policy == "replace_N" && filter_stats$noniupac_rows > 0L) {
        warnings <- c(warnings, sprintf("Replaced non-IUPAC letters in %d rows.", filter_stats$noniupac_rows))
      }
      if (noniupac_policy == "drop_row" && filter_stats$noniupac_rows > 0L) {
        warnings <- c(warnings, sprintf("Dropped %d rows with non-IUPAC letters.", filter_stats$noniupac_rows))
      }
    }

    # ---- final result ----
    result <- list(
      ok         = TRUE,
      trees      = unname(trees),
      figures    = list(
        phylogeny     = phylogeny_png,
        phylogeny_pdf = phylogeny_pdf
      ),
      annotations = annotations,
      clones      = clones_meta,
      stats       = stats,
      # single ZIP containing all clone_* folders and other artifacts,
      # excluding clone_ID.tree / clone_ID.png / clone_ID.pdf
      artifact_zip_b64  = artifacts_zip_b64,
      warnings    = unname(as.list(warnings)),
      logs        = logs,              # full stdout + step logs
      render      = "phylogeny",
      error       = NULL
    )

    return(result)
  }, error = function(e) {
    logf("[brepphylo][ERROR] %s", as.character(e))
    fail(
      as.character(e),
      res,
      status = ifelse(is.null(res$status) || res$status == 200, 500, res$status)
    )
  })
}

STRICT_CONTRACT <- tolower(Sys.getenv("STRICT_CONTRACT_ROUTES", "true")) %in% c("1", "true", "yes")

#* @plumber
function(pr) {
  if (!STRICT_CONTRACT) {
    pr$handle("GET",  "/spec", serializer = SER, function(req, res) spec_handler_impl())
    pr$handle("POST", "/run",  serializer = SER, function(req, res) run_handler_impl(req, res))
  }

  pr$handle("GET",  ROUTES_JSON$spec, serializer = SER, function(req, res) spec_handler_impl())
  pr$handle("POST", ROUTES_JSON$run,  serializer = SER, function(req, res) run_handler_impl(req, res))
  pr$handle("GET",  "/ui",            serializer = SER, function(req, res) ui_handler_impl())
  pr$handle("GET",  "/routes",        serializer = SER, function(req, res) routes_handler_impl())
  pr$handle("GET",  "/schema",        serializer = SER, function(req, res) schema_handler_impl())
  pr$handle("GET",  "/ping",          serializer = SER, function(req, res) {
    list(
      ok                = TRUE,
      method            = METHOD_ID,
      brepphylo_version = as.character(utils::packageVersion("BrepPhylo"))
    )
  })

  pr_set_error(pr, function(req, res, err) {
    res$status <- 500
    list(ok = FALSE, error = as.character(err))
  })

  pr
}
