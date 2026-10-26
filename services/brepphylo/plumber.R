#* @apiTitle BrepPhylo microservice
#* @apiDescription Build BCR lineage trees with BrepPhylo::cloneLineage and CSR analysis.

library(plumber)
SER <- plumber::serializer_json(
  auto_unbox = TRUE,
  null       = "null",
  na         = "null",
  dataframe  = "rows"
)
plumber::register_serializer("SER", function(...) SER)

library(jsonlite)
library(BrepPhylo)
library(ape)
library(Biostrings)
library(igraph)

# Validation helpers (no global side effects)
validators_candidates <- c(
  file.path(getwd(), "validators.R"),
  "/srv/validators.R",
  "validators.R"
)
validators_path <- validators_candidates[file.exists(validators_candidates)][1]
if (is.na(validators_path)) {
  stop("validators.R not found; expected alongside plumber.R or at /srv/validators.R")
}
source(validators_path, local = FALSE)

# ---------------------------
# Helpers
# ---------------------------
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

clone_seq_counts <- function(df, clone_col, clone_ids) {
  vapply(clone_ids, function(cid) sum(df[[clone_col]] == cid, na.rm = TRUE), integer(1))
}

tail_file_text <- function(path, n = 80) {
  lines <- tryCatch(readLines(path, warn = FALSE), error = function(e) {
    sprintf("<failed to read %s: %s>", basename(path), conditionMessage(e))
  })
  if (!length(lines)) return("<empty log>")
  paste(utils::tail(lines, n), collapse = "\n")
}

summarise_brepphylo_output_dir <- function(out_dir, tail_lines = 80, max_files = 120) {
  output_dir <- normalizePath(out_dir, mustWork = FALSE)
  all_files <- list.files(out_dir, recursive = TRUE, full.names = TRUE, all.files = FALSE)
  rel_files <- gsub(paste0("^", out_dir, "/?"), "", all_files)
  rel_files <- sort(rel_files[nzchar(rel_files)])
  shown_files <- utils::head(rel_files, max_files)

  clone_logs <- list.files(
    out_dir,
    pattern = "^clone_.*\\.log$",
    recursive = TRUE,
    full.names = TRUE
  )
  log_files <- clone_logs
  log_source <- "clone_*.log"
  if (!length(log_files)) {
    log_files <- list.files(
      out_dir,
      pattern = "\\.log$",
      recursive = TRUE,
      full.names = TRUE
    )
    log_source <- "*.log"
  }

  log_tails <- character(0)
  if (length(log_files)) {
    log_files <- sort(log_files)
    log_tails <- vapply(
      log_files,
      function(p) {
        rel <- gsub(paste0("^", out_dir, "/?"), "", p)
        paste0("----- ", rel, " -----\n", tail_file_text(p, tail_lines))
      },
      FUN.VALUE = character(1)
    )
  }

  parts <- c(
    "No .tree files were produced by BrepPhylo.",
    sprintf("output_dir=%s", output_dir),
    sprintf("files_found=%d", length(rel_files))
  )

  if (length(shown_files)) {
    parts <- c(parts, paste0("produced_files:\n", paste(shown_files, collapse = "\n")))
    if (length(rel_files) > length(shown_files)) {
      parts <- c(parts, sprintf("produced_files_truncated=%d", length(rel_files) - length(shown_files)))
    }
  } else {
    parts <- c(parts, "produced_files=<none>")
  }

  if (length(log_tails)) {
    parts <- c(
      parts,
      sprintf("log_source=%s", log_source),
      sprintf("clone_log_files_found=%d", length(clone_logs)),
      sprintf("log_files_found=%d", length(log_files)),
      paste0("log_tails:\n", paste(log_tails, collapse = "\n\n"))
    )
  } else {
    parts <- c(
      parts,
      sprintf("clone_log_files_found=%d", length(clone_logs)),
      "log_files_found=0"
    )
  }

  paste(parts, collapse = "\n")
}

fixed_colour_specification <- function() {
  list(
    colours        = list(default = "#000000"),
    coloursColumn  = ".brepphylo_colour",
    germlineColour = "#808080"
  )
}

INTERNAL_ANNOTATION_COLS <- c(".brepphylo_tip_id", ".brepphylo_colour")

find_distance_table <- function(out_dir, clone_id) {
  patterns <- c("dist", "distance", "path_stats")
  prefix <- paste0("clone_", clone_id)
  candidates <- list.files(
    out_dir,
    recursive = TRUE,
    full.names = TRUE
  )
  candidates <- candidates[startsWith(basename(candidates), prefix)]
  for (p in candidates) {
    bn <- tolower(basename(p))
    if (any(vapply(patterns, function(pat) grepl(pat, bn, fixed = TRUE), logical(1)))) {
      if (grepl("\\.(tsv|csv|txt)$", bn, ignore.case = TRUE)) {
        return(p)
      }
    }
  }
  NULL
}

read_distance_table <- function(path) {
  if (is.null(path) || !file.exists(path)) return(NULL)
  ext <- tolower(tools::file_ext(path))
  df <- tryCatch(
    if (ext == "csv") read.csv(path, stringsAsFactors = FALSE) else read.delim(path, stringsAsFactors = FALSE),
    error = function(e) NULL
  )
  df
}

df_to_records <- function(df) {
  if (is.null(df) || !is.data.frame(df) || !nrow(df)) return(list())
  lapply(seq_len(nrow(df)), function(i) as.list(df[i, , drop = FALSE]))
}

arborescence_edges_from_table <- function(table_df) {
  if (is.null(table_df) || !is.data.frame(table_df) || !nrow(table_df)) return(list())
  cols <- names(table_df)
  pick <- function(candidates) {
    hit <- candidates[candidates %in% cols]
    if (length(hit)) hit[1] else NULL
  }
  start_id <- pick(c("startID", "startId", "from", "start"))
  end_id <- pick(c("endID", "endId", "to", "end"))
  weight <- pick(c("weight", "Weight", "dist"))
  start_label <- pick(c("startLabel", "start_label", "fromLabel"))
  end_label <- pick(c("endLabel", "end_label", "toLabel"))

  lapply(seq_len(nrow(table_df)), function(i) {
    row <- table_df[i, , drop = FALSE]
    list(
      startID    = if (!is.null(start_id)) row[[start_id]] else NA,
      endID      = if (!is.null(end_id)) row[[end_id]] else NA,
      weight     = if (!is.null(weight)) as.numeric(row[[weight]]) else NA_real_,
      startLabel = if (!is.null(start_label)) as.character(row[[start_label]]) else "",
      endLabel   = if (!is.null(end_label)) as.character(row[[end_label]]) else ""
    )
  })
}

normalize_isotype_label <- function(x) {
  x <- trimws(as.character(x))
  x <- sub("^Ig", "", x, ignore.case = TRUE)
  x
}

derive_germline_id_from_arborescence <- function(table_df, path_stats = NULL, tip_id_col = NULL) {
  if (is.null(table_df) || !is.data.frame(table_df) || !nrow(table_df)) return(NULL)

  cols <- names(table_df)
  pick <- function(candidates) {
    hit <- candidates[candidates %in% cols]
    if (length(hit)) hit[1] else NULL
  }
  start_id <- pick(c("startID", "startId", "from", "start"))
  end_id <- pick(c("endID", "endId", "to", "end"))
  start_label <- pick(c("startLabel", "start_label", "fromLabel"))
  end_label <- pick(c("endLabel", "end_label", "toLabel"))

  germ_patterns <- c("germline", "gl")
  for (lbl_col in c(start_label, end_label)) {
    if (is.null(lbl_col)) next
    vals <- tolower(trimws(as.character(table_df[[lbl_col]])))
    hit <- which(vals %in% germ_patterns)
    if (length(hit)) {
      id_col <- if (identical(lbl_col, start_label)) start_id else end_id
      if (!is.null(id_col)) return(as.character(table_df[[id_col]][hit[1]]))
    }
  }

  if (!is.null(start_id) && !is.null(end_id)) {
    starts <- as.character(table_df[[start_id]])
    ends <- as.character(table_df[[end_id]])
    roots <- setdiff(unique(starts), unique(ends))
    if (length(roots)) return(roots[1])
  }

  if (!is.null(path_stats) && is.data.frame(path_stats) && nrow(path_stats)) {
    dist_cols <- intersect(c("dist", "distFromGermline", "distance", "Distance"), names(path_stats))
    seq_cols <- intersect(c("Seq_ID", "sequence_id", "label", tip_id_col), names(path_stats))
    if (length(dist_cols) && length(seq_cols)) {
      dist_col <- dist_cols[1]
      seq_col <- seq_cols[1]
      dists <- suppressWarnings(as.numeric(path_stats[[dist_col]]))
      zero_idx <- which(!is.na(dists) & dists == 0)
      if (length(zero_idx)) return(as.character(path_stats[[seq_col]][zero_idx[1]]))
    }
  }

  NULL
}

try_summarise_csr <- function(csr_df, clone_id, warnings_out = character(0)) {
  if (is.null(csr_df) || !is.data.frame(csr_df) || !nrow(csr_df)) {
    return(list(summary = list(), warnings = warnings_out))
  }
  if (!exists("summariseCSR", where = asNamespace("BrepPhylo"), inherits = FALSE)) {
    return(list(summary = list(), warnings = warnings_out))
  }

  csr_prep <- csr_df
  if (!"clone_id" %in% names(csr_prep) && !"CloneID" %in% names(csr_prep)) {
    csr_prep$clone_id <- clone_id
  }

  clone_col <- intersect(c("CloneID", "clone_id"), names(csr_prep))[1]
  if (is.na(clone_col)) clone_col <- "clone_id"
  dist_col <- intersect(c("distFromGermline", "dist", "meanDist", "distance"), names(csr_prep))[1]
  if (is.na(dist_col)) {
    return(list(
      summary = list(),
      warnings = c(
        warnings_out,
        sprintf(
          "Clone %s: summariseCSR skipped because no distance column was found in CSR events.",
          clone_id
        )
      )
    ))
  }

  summary_try <- tryCatch(
    BrepPhylo::summariseCSR(
      csr_prep,
      cloneID_column = clone_col,
      dist_column = dist_col,
      summarise_variables = clone_col
    ),
    error = function(e) e
  )

  if (inherits(summary_try, "error")) {
    return(list(
      summary = list(),
      warnings = c(
        warnings_out,
        sprintf("Clone %s: summariseCSR failed: %s", clone_id, conditionMessage(summary_try))
      )
    ))
  }

  list(summary = df_to_records(summary_try), warnings = warnings_out)
}

run_csr_analysis_for_clone <- function(
  clone_id,
  clone_df,
  tree_path,
  out_dir,
  tip_id_col,
  isotype_col,
  plot_format,
  species
) {
  result <- list(
    distance_from_germline = list(),
    csr_events = list(),
    csr_summary = list(),
    csr_summary_fallback = list(),
    isotype_switch_validity = list(),
    arborescence_edges = list(),
    warnings = character(0),
    status = "analyzed",
    skip_reason = NULL
  )

  if (!file.exists(tree_path)) {
    result$status <- "skipped"
    result$skip_reason <- sprintf("Tree file not found: %s", tree_path)
    return(result)
  }

  arbo_out <- file.path(out_dir, paste0("arbo_", clone_id))
  dir.create(arbo_out, recursive = TRUE, showWarnings = FALSE)

  arbo <- tryCatch(
    BrepPhylo::cloneArborescence(
      clone            = clone_df,
      cloneID          = clone_id,
      columnSeqID      = tip_id_col,
      columnSubclass   = isotype_col,
      tree             = tree_path,
      outputFolder     = arbo_out,
      plotFormat       = plot_format
    ),
    error = function(e) e
  )

  if (inherits(arbo, "error")) {
    result$status <- "failed"
    result$skip_reason <- conditionMessage(arbo)
    return(result)
  }

  if (!is.null(arbo$table) && is.data.frame(arbo$table)) {
    result$arborescence_edges <- arborescence_edges_from_table(arbo$table)
  }

  dist_path <- find_distance_table(out_dir, clone_id)
  path_stats <- read_distance_table(dist_path)

  if (!is.null(path_stats) && nrow(path_stats)) {
    seq_col_name <- intersect(c("Seq_ID", "sequence_id", "label", tip_id_col), names(path_stats))
    dist_col_name <- intersect(c("dist", "distFromGermline", "distance", "Distance"), names(path_stats))
    seq_col <- if (length(seq_col_name)) seq_col_name[1] else names(path_stats)[1]
    dist_col <- if (length(dist_col_name)) dist_col_name[1] else names(path_stats)[2]

    for (i in seq_len(nrow(path_stats))) {
      result$distance_from_germline[[length(result$distance_from_germline) + 1L]] <- list(
        clone_id    = clone_id,
        sequence_id = as.character(path_stats[[seq_col]][i]),
        distance    = suppressWarnings(as.numeric(path_stats[[dist_col]][i]))
      )
    }
  }

  csr_df <- NULL
  if (!is.null(arbo$csr_events) && is.data.frame(arbo$csr_events) && nrow(arbo$csr_events)) {
    csr_df <- arbo$csr_events
  }

  if (is.null(csr_df) && !is.null(arbo$table) && !is.null(path_stats)) {
    germline_id <- derive_germline_id_from_arborescence(arbo$table, path_stats, tip_id_col)
    if (!is.null(germline_id) && nzchar(as.character(germline_id)[1])) {
      csr_try <- tryCatch(
        BrepPhylo::getCSEvents(
          clone           = clone_df,
          columnSeqID     = tip_id_col,
          columnSubclass  = isotype_col,
          dfArborescence  = arbo$table,
          germline        = germline_id,
          path_stats      = path_stats
        ),
        error = function(e) e
      )
      if (inherits(csr_try, "error")) {
        result$warnings <- c(
          result$warnings,
          sprintf("Clone %s: getCSEvents fallback failed: %s", clone_id, conditionMessage(csr_try))
        )
      } else if (is.data.frame(csr_try) && nrow(csr_try)) {
        csr_df <- csr_try
      }
    } else {
      result$warnings <- c(
        result$warnings,
        sprintf(
          "Clone %s: CSR fallback skipped because germline/root node ID could not be determined safely.",
          clone_id
        )
      )
    }
  }

  human_species <- identical(species, "Homo_sapiens")
  if (!human_species && !is.null(csr_df) && nrow(csr_df)) {
    result$warnings <- c(
      result$warnings,
      sprintf(
        "CSR isotype-switch validity not evaluated for species '%s' (human-only logic); events marked valid=null.",
        species
      )
    )
  }

  if (!is.null(csr_df) && is.data.frame(csr_df) && nrow(csr_df)) {
    from_cols <- intersect(c("from", "fromSubclass", "startSubclass", "parentSubclass"), names(csr_df))
    to_cols <- intersect(c("to", "toSubclass", "endSubclass", "childSubclass"), names(csr_df))
    dist_cols <- intersect(c("distFromGermline", "dist", "meanDist", "distance"), names(csr_df))
    from_col <- if (length(from_cols)) from_cols[1] else NULL
    to_col <- if (length(to_cols)) to_cols[1] else NULL
    dist_col <- if (length(dist_cols)) dist_cols[1] else NULL

    for (i in seq_len(nrow(csr_df))) {
      from_iso <- if (!is.null(from_col)) as.character(csr_df[[from_col]][i]) else NA_character_
      to_iso <- if (!is.null(to_col)) as.character(csr_df[[to_col]][i]) else NA_character_
      dist_val <- if (!is.null(dist_col)) suppressWarnings(as.numeric(csr_df[[dist_col]][i])) else NA_real_

      valid_val <- NULL
      if (human_species && !is.na(from_iso) && !is.na(to_iso)) {
        valid_val <- tryCatch(
          BrepPhylo::is.valid.IsotypeSwitch(
            normalize_isotype_label(from_iso),
            normalize_isotype_label(to_iso)
          ),
          error = function(e) NA
        )
      }

      result$csr_events[[length(result$csr_events) + 1L]] <- list(
        clone_id               = clone_id,
        from_isotype           = from_iso,
        to_isotype             = to_iso,
        distance_from_germline = dist_val,
        valid                  = valid_val
      )

      result$isotype_switch_validity[[length(result$isotype_switch_validity) + 1L]] <- list(
        clone_id         = clone_id,
        sequence_id_from = from_iso,
        sequence_id_to   = to_iso,
        from_isotype     = from_iso,
        to_isotype       = to_iso,
        valid            = valid_val
      )
    }

    result$csr_summary_fallback <- aggregate_csr_summary(result$csr_events)
    summarise_res <- try_summarise_csr(csr_df, clone_id, result$warnings)
    result$csr_summary <- summarise_res$summary
    result$warnings <- summarise_res$warnings
  }

  result
}

build_annotations_from_tree_tips <- function(
  clone_df,
  clone_id,
  label_col,
  tip_id_col,
  tree_path,
  unmapped_tree_tips,
  unmapped_input_rows
) {
  tree <- tryCatch(ape::read.tree(tree_path), error = function(e) NULL)
  if (is.null(tree)) {
    return(list(
      annotations = list(),
      unmapped_tree_tips = unmapped_tree_tips,
      unmapped_input_rows = unmapped_input_rows
    ))
  }

  tip_labels <- tree$tip.label
  if (is.null(tip_labels)) tip_labels <- character(0)

  tip_ids <- trimws(as.character(clone_df[[tip_id_col]]))
  annotations <- list()
  matched_rows <- logical(nrow(clone_df))

  for (tip in tip_labels) {
    row_idx <- which(tip_ids == tip)
    if (!length(row_idx)) {
      unmapped_tree_tips[[length(unmapped_tree_tips) + 1L]] <- list(
        clone_id = clone_id,
        final_tip_label = tip
      )
      next
    }
    i <- row_idx[1]
    matched_rows[i] <- TRUE
    row <- clone_df[i, , drop = FALSE]
    ann <- as.list(row[1, , drop = FALSE])
    for (drop_col in INTERNAL_ANNOTATION_COLS) {
      if (drop_col %in% names(ann)) ann[[drop_col]] <- NULL
    }

    original_seq_id <- NA_character_
    for (cand in c("sequence_id", "Sequence.ID")) {
      if (cand %in% names(row)) {
        val <- trimws(as.character(row[[cand]]))
        if (nzchar(val) && !is.na(val)) {
          original_seq_id <- val
          break
        }
      }
    }

    ann$original_sequence_id <- original_seq_id
    ann$final_tip_label <- tip
    ann$clone_id <- clone_id
    if (!is.null(label_col) && nzchar(label_col) && label_col %in% names(row)) {
      ann$label <- as.character(row[[label_col]])
    } else {
      ann$label <- tip
    }
    annotations[[length(annotations) + 1L]] <- ann
  }

  for (i in seq_len(nrow(clone_df))) {
    if (!matched_rows[i]) {
      user_label <- if (!is.null(label_col) && nzchar(label_col) && label_col %in% names(clone_df)) {
        as.character(clone_df[[label_col]][i])
      } else {
        tip_ids[i]
      }
      unmapped_input_rows[[length(unmapped_input_rows) + 1L]] <- list(
        row_index = i,
        sequence_id = tip_ids[i],
        clone_id = clone_id,
        label = user_label
      )
    }
  }

  list(
    annotations = annotations,
    unmapped_tree_tips = unmapped_tree_tips,
    unmapped_input_rows = unmapped_input_rows
  )
}

aggregate_csr_summary <- function(csr_events) {
  counts <- list()
  for (ev in csr_events) {
    from <- ev$from_isotype %||% "?"
    to <- ev$to_isotype %||% "?"
    key <- paste(from, to, sep = "->")
    counts[[key]] <- (counts[[key]] %||% 0L) + 1L
  }
  counts
}

# ---------------------------
# IgPhyML exec + motifs (env-driven only)
# ---------------------------
IG_EXEC_DEFAULT   <- Sys.getenv("IGPHYML_BIN", Sys.getenv("IG_EXEC_DEFAULT", "igphyml"))
IG_MOTIFS_DEFAULT <- Sys.getenv("IGPHYML_MOTIFS", "")

validate_motifs_dir <- function(path) {
  if (!nzchar(path)) return(FALSE)
  if (!dir.exists(path)) return(FALSE)
  length(list.files(path, all.files = FALSE)) > 0
}

check_igphyml_exec <- function(user_exec = NULL) {
  cand <- user_exec %||% Sys.which("igphyml")
  if (!nzchar(cand)) {
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
  x <- as.character(x)[1]
  x <- trimws(x)
  if (!nzchar(x)) return(NULL)
  x
}

# ---------------------------
# Config & Contracts loading
# ---------------------------
METHOD_ID     <- "brepphylo"
CONTRACTS_DIR <- Sys.getenv("CONTRACTS_DIR", "packages/contracts")
METHOD_DIR    <- file.path(CONTRACTS_DIR, "methods", METHOD_ID)

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
ROUTES_JSON        <- modifyList(
  list(
    spec = "/spec", run = "/run", jobs = "/jobs",
    jobStatus = "/jobs/{job_id}/status",
    jobResult = "/jobs/{job_id}/result",
    jobCancel = "/jobs/{job_id}/cancel",
    jobLog = "/jobs/{job_id}/log",
    job = "/jobs/{job_id}",
    capacity = "/capacity"
  ),
  ROUTES_JSON
)

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

reject_removed_params <- function(params) {
  removed <- c(
    "germline_set", "germlineSet", "class_column", "germline_colour",
    "max_class_categories", "use_temp_dir", "useTempDir",
    "apply_filters", "uppercase", "gap_policy", "noniupac_policy",
    "resume_completed_clones", "resumeCompletedClones"
  )
  present <- intersect(removed, names(params))
  if (length(present)) {
    return(sprintf(
      "Removed parameter(s) no longer supported: %s. Use germline_set_text with species='custom' for custom germlines.",
      paste(present, collapse = ", ")
    ))
  }
  NULL
}

# Irrelevant tree_type-conditional params are ignored at call time (UI may still submit defaults).

# ---------------------------
# Run BrepPhylo
# ---------------------------
run_handler_impl <- function(req, res) {
  tryCatch({
    warnings <- character(0)
    logs <- list()
    add_log <- function(step, ok, out) {
      logs[[length(logs) + 1]] <<- list(step = step, ok = ok, out = out)
    }
    fail_local <- function(msg, status = 400) {
      fail(msg, res, status = status, logs = logs, warnings = as.list(warnings))
    }

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

    removed_err <- reject_removed_params(params)
    if (!is.null(removed_err)) return(fail_local(removed_err))

    add_log("brepphylo.request", TRUE, sprintf("Validated request; file_path=%s, ext=%s.", file_path, ext))

    df <- tryCatch(read_input_table(file_path), error = function(e) e)
    if (inherits(df, "error")) {
      return(fail_local(paste("Failed to read input table:", df$message)))
    }
    if (!is.data.frame(df) || !nrow(df)) {
      return(fail_local("Input table is empty."))
    }

    add_log("brepphylo.readInput", TRUE, sprintf("Read input table with %d rows and %d columns.", nrow(df), ncol(df)))

    seq_col   <- normalize_col(params$sequence_column,    "sequence")
    clone_col <- normalize_col(params$clone_id_column,    "clone_id")
    germ_col  <- normalize_col(params$germline_id_column, "V.GENE.and.allele")
    label_col <- normalize_col(params$label_column,       NULL)
    isotype_col <- normalize_col(params$isotype_column,   NULL)

    required_cols <- c(seq_col, clone_col, germ_col)
    missing <- required_cols[!required_cols %in% names(df)]
    if (length(missing)) {
      return(fail_local(sprintf("Missing required column(s): %s", paste(missing, collapse = ", "))))
    }

    which_clones  <- parse_vec(params$which_clones  %||% params$whichClones)
    ignore_clones <- parse_vec(params$ignore_clones %||% params$ignoreClones)

    me_err <- validate_mutually_exclusive(which_clones, ignore_clones)
    if (!is.null(me_err)) return(fail_local(me_err))

    tree_type <- params$tree_type %||% "dnapars"

    input_sequence_mode <- params$input_sequence_mode %||% "raw_sequence"
    for (check_fn in list(
      function() validate_input_sequence_mode(input_sequence_mode),
      function() validate_species(params$species),
      function() validate_plot_type(params$plot_type),
      function() require_positive_int("min_clone_size", params$min_clone_size)
    )) {
      err <- check_fn()
      if (!is.null(err)) return(fail_local(err))
    }

    species <- trimws(as.character(params$species)[1])
    plot_type <- trimws(as.character(params$plot_type)[1])
    plot_format <- params$plot_format %||% "png"
    min_clone_size <- as.integer(params$min_clone_size)
    enable_csr_analysis <- as_bool(params$enable_csr_analysis, TRUE)
    make_alignment_pdf <- as_bool(params$make_alignment_pdf, FALSE)
    gather_plots <- as_bool(params$gather_plots, TRUE)
    igphyml_accuracy <- normalize_opt_string(params$igphyml_accuracy)

    if (!plot_format %in% c("png", "pdf")) {
      return(fail_local("plot_format must be 'png' or 'pdf'."))
    }

    germline_set_text <- params$germline_set_text %||% ""
    germline_set_path <- NULL
    species_effective <- species

    if (identical(species, "custom")) {
      if (!nzchar(trimws(as.character(germline_set_text)[1]))) {
        return(fail_local("germline_set_text is required when species is 'custom'."))
      }
      fasta_val <- validate_germline_set_text(germline_set_text)
      if (!isTRUE(fasta_val$ok)) return(fail_local(fasta_val$error))
      species_effective <- BREPPHYLO_CUSTOM_SPECIES_KEY
    } else if (nzchar(trimws(as.character(germline_set_text)[1]))) {
      warnings <- c(warnings, "germline_set_text is ignored unless species is 'custom'.")
    }

    algorithm <- NULL
    if (identical(input_sequence_mode, "raw_sequence")) {
      algorithm <- params$algorithm %||% "ClustalOmega"
      allowed_alg <- c("ClustalOmega", "ClustalW")
      if (!algorithm %in% allowed_alg) {
        return(fail_local(sprintf("algorithm must be one of: %s", paste(allowed_alg, collapse = ", "))))
      }
    } else {
      aligned_check <- validate_aligned_imgt_gapped(df, seq_col)
      if (!isTRUE(aligned_check$ok)) return(fail_local(aligned_check$error))
    }

    if (enable_csr_analysis) {
      iso_check <- validate_isotype_column(df, isotype_col)
      if (!isTRUE(iso_check$ok)) return(fail_local(iso_check$error))
    }

    row_check <- validate_required_rows(df, seq_col, clone_col, germ_col, label_col)
    if (!isTRUE(row_check$ok)) return(fail_local(row_check$error))

    diagnostics <- list(
      dropped_rows = list(),
      rejected_rows = row_check$rejected_rows,
      unmapped_input_rows = list(),
      unmapped_tree_tips = list(),
      mixed_germline_clones = list(),
      latex_available = NULL
    )

    if (make_alignment_pdf) {
      diagnostics$latex_available <- check_latex_available()
      if (!isTRUE(diagnostics$latex_available)) {
        warnings <- c(
          warnings,
          "make_alignment_pdf=true but LaTeX (pdflatex/latexmk) was not found; alignment PDF generation may fail."
        )
      }
    }

    mixed <- precheck_mixed_germline(df, clone_col, germ_col)
    if (length(mixed)) {
      diagnostics$mixed_germline_clones <- mixed
      msg <- sprintf(
        "%d clone(s) have multiple distinct germline allele calls: %s",
        length(mixed),
        paste(vapply(mixed, function(m) m$clone_id, character(1)), collapse = ", ")
      )
      if (enable_csr_analysis) {
        return(fail_local(paste(msg, "Resolve germline assignments before CSR analysis.")))
      }
      warnings <- c(warnings, msg)
    }

    label_check <- precheck_label_uniqueness(df, clone_col, label_col)
    if (!isTRUE(label_check$ok)) return(fail_local(label_check$error))

    clone_id_check <- validate_clone_ids_strict(df, clone_col)
    if (!isTRUE(clone_id_check$ok)) return(fail_local(clone_id_check$error))

    if (length(which_clones)) {
      before_n <- nrow(df)
      df <- df[df[[clone_col]] %in% which_clones, , drop = FALSE]
      add_log("brepphylo.whichClones", TRUE, sprintf("Applied which_clones filter: kept %d/%d rows.", nrow(df), before_n))
      if (!nrow(df)) return(fail_local("No sequences remain after applying which_clones filter."))
    }

    if (length(ignore_clones)) {
      before_n <- nrow(df)
      df <- df[!(df[[clone_col]] %in% ignore_clones), , drop = FALSE]
      add_log("brepphylo.ignoreClones", TRUE, sprintf("Applied ignore_clones filter: kept %d/%d rows.", nrow(df), before_n))
      if (!nrow(df)) return(fail_local("No sequences remain after applying ignore_clones filter."))
    }

    clone_counts_pre <- table(df[[clone_col]])
    n_clones_pre <- length(clone_counts_pre)
    if (n_clones_pre == 0L) {
      return(fail_local("No clones remain in the input after filtering."))
    }
    n_large_clones <- sum(clone_counts_pre >= min_clone_size)
    if (n_large_clones == 0L) {
      return(fail_local(sprintf(
        "No clones with at least %d sequences remain; adjust min_clone_size or filters.",
        min_clone_size
      )))
    }

    out_dir <- tempfile("brepphylo_", tmpdir = tempdir())
    dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

    if (identical(species, "custom")) {
      germline_set_path <- write_germline_fasta_tmp(
        germline_set_text,
        out_dir,
        species_key = BREPPHYLO_CUSTOM_SPECIES_KEY
      )
    }

    tree_type_effective <- tree_type
    tc_params <- list()

    if (identical(tree_type_effective, "dnapars")) {
      tc_params$collapseAndReplace <- as_bool(params$collapse_and_replace, TRUE)
      dnapars_exec <- Sys.getenv("DNAPARS_PATH", "")
      if (!nzchar(dnapars_exec)) dnapars_exec <- Sys.which("dnapars")
      if (nzchar(dnapars_exec)) {
        tc_params$executable <- dnapars_exec
        add_log("brepphylo.dnapars.exec", TRUE, sprintf("Using DNAPARS executable: %s", dnapars_exec))
      } else {
        warnings <- c(warnings, "DNAPARS executable not found; BrepPhylo will try its own lookup and may fail.")
      }
    } else if (identical(tree_type_effective, "igphyml")) {
      if (!is.null(igphyml_accuracy)) tc_params$accuracy <- igphyml_accuracy
      resolved <- resolve_igphyml(require_ok = TRUE)
      if (!isTRUE(resolved$ok)) return(fail_local(resolved$error))
      tc_params$executable <- resolved$exec
      add_log("brepphylo.igphyml.exec", TRUE, sprintf("Using IgPhyML exec=%s", resolved$exec))
    }

    treeConstruction <- list(type = tree_type_effective, parameters = tc_params)
    makeAlignmentPDFConstruction <- list(makeAlignmentPDF = make_alignment_pdf)

    tip_res <- resolve_or_create_tip_id_column(df, label_col)
    df <- tip_res$df
    tip_id_col <- tip_res$tip_id_col
    df$.brepphylo_colour <- "default"

    colourSpecification <- fixed_colour_specification()

    tree_start <- Sys.time()
    log_vec <- character(0)
    err <- tryCatch({
      with_di2multi_top_alias({
        log_vec <<- capture.output({
          args <- list(
            input                       = df,
            outputFolder                = out_dir,
            minCloneSize                = min_clone_size,
            sequenceColumn              = seq_col,
            cloneIdColumn               = clone_col,
            germlineIdColumn            = germ_col,
            colourSpecification         = colourSpecification,
            plotType                    = plot_type,
            plotFormat                  = plot_format,
            gatherPlots                 = gather_plots,
            treeConstruction            = treeConstruction,
            makeAlignmentPDFConstruction = makeAlignmentPDFConstruction,
            whichClones                 = NULL,
            ignoreClones                = NULL,
            labelColumn                 = tip_id_col
          )
          if (!is.null(species_effective)) args$species <- species_effective
          if (!is.null(germline_set_path)) args$germlineSet <- germline_set_path
          if (!is.null(algorithm)) args$algorithm <- algorithm
          do.call(BrepPhylo::cloneLineage, args)
        })
      })
      NULL
    }, error = function(e) e)

    tree_inference_seconds <- as.numeric(difftime(Sys.time(), tree_start, units = "secs"))
    log_text <- paste(log_vec, collapse = "\n")
    add_log("brepphylo.cloneLineage", !inherits(err, "error"), log_text)

    if (inherits(err, "error")) {
      res$status <- 400
      return(list(
        ok = FALSE,
        error = conditionMessage(err),
        logs = logs,
        warnings = as.list(warnings),
        diagnostics = diagnostics
      ))
    }

    tree_files <- list.files(
      out_dir,
      pattern = "^clone_.*\\.tree$",
      recursive = TRUE,
      full.names = TRUE
    )
    if (!length(tree_files)) {
      res$status <- 500
      collect_diagnostics <- summarise_brepphylo_output_dir(out_dir)
      add_log("brepphylo.collectTrees", FALSE, collect_diagnostics)
      return(list(
        ok = FALSE,
        error = "BrepPhylo did not produce any .tree files.",
        diagnostics = diagnostics,
        logs = logs,
        warnings = as.list(warnings)
      ))
    }

    tree_files <- sort(tree_files)
    trees <- vapply(tree_files, function(p) paste(readLines(p, warn = FALSE), collapse = ""), character(1))
    clone_ids <- sub("^clone_", "", basename(tree_files))
    clone_ids <- sub("\\.tree$", "", clone_ids)

    plot_files <- list.files(
      out_dir,
      pattern = paste0("\\.", plot_format, "$"),
      recursive = TRUE,
      full.names = TRUE
    )
    plot_files <- plot_files[grepl("clone_", basename(plot_files), fixed = TRUE)]

    # Collect figure file PATHS (no base64 round-trip). materialize_artifacts
    # in the job runner copies these into the run's artifact dir; the API
    # worker uploads them to object storage. The files already live on disk
    # in out_dir — no need to load them into RAM here.
    png_paths <- list()
    pdf_paths <- list()
    for (cid in clone_ids) {
      prefix <- paste0("clone_", cid, ".")
      candidates <- plot_files[startsWith(basename(plot_files), prefix)]
      if (!length(candidates)) next
      for (f in candidates) {
        sz <- file.info(f)$size
        if (is.na(sz) || sz <= 0) next
        if (grepl("\\.png$", f, ignore.case = TRUE)) png_paths[[cid]] <- f
        if (grepl("\\.pdf$", f, ignore.case = TRUE)) pdf_paths[[cid]] <- f
      }
    }

    annotations <- vector("list", length(clone_ids))
    for (i in seq_along(clone_ids)) {
      cid <- clone_ids[i]
      clone_df <- df[df[[clone_col]] == cid, , drop = FALSE]
      ann_res <- build_annotations_from_tree_tips(
        clone_df,
        cid,
        label_col,
        tip_id_col,
        tree_files[i],
        diagnostics$unmapped_tree_tips,
        diagnostics$unmapped_input_rows
      )
      diagnostics$unmapped_tree_tips <- ann_res$unmapped_tree_tips
      diagnostics$unmapped_input_rows <- ann_res$unmapped_input_rows
      annotations[[i]] <- ann_res$annotations
    }

    analysis_start <- Sys.time()
    analysis <- list(
      batch_summary = list(clones_analyzed = 0L, clones_skipped = 0L, csr_total = 0L, distance_rows = 0L),
      distance_from_germline = list(),
      csr_events = list(),
      csr_summary = list(),
      csr_summary_fallback = list(),
      arborescence = list(),
      isotype_switch_validity = list(),
      per_clone_status = list(),
      skipped_clones = list()
    )

    if (enable_csr_analysis) {
      # getSummaryFromBatch() requires output from doBatchCloneAnalysis(); not used on cloneLineage path.
      for (i in seq_along(clone_ids)) {
        cid <- clone_ids[i]
        clone_df <- df[df[[clone_col]] == cid, , drop = FALSE]
        n_seqs <- nrow(clone_df)
        ar <- run_csr_analysis_for_clone(
          cid, clone_df, tree_files[i], out_dir, tip_id_col, isotype_col,
          plot_format, species
        )
        warnings <- c(warnings, ar$warnings)

        # A requested analysis that fails must be visible on the run, not only
        # inside analysis$per_clone_status.
        if (identical(ar$status, "failed")) {
          warnings <- c(warnings, sprintf(
            "Class-switch analysis failed for clone %s: %s", cid, ar$skip_reason
          ))
        }

        if (!is.null(ar$skip_reason)) {
          analysis$skipped_clones[[length(analysis$skipped_clones) + 1L]] <- list(
            clone_id = cid,
            reason = ar$skip_reason
          )
          analysis$per_clone_status[[length(analysis$per_clone_status) + 1L]] <- list(
            clone_id = cid,
            n_seqs = n_seqs,
            analyzed = FALSE,
            status = ar$status,
            skip_reason = ar$skip_reason
          )
          next
        }

        analysis$per_clone_status[[length(analysis$per_clone_status) + 1L]] <- list(
          clone_id = cid,
          n_seqs = n_seqs,
          analyzed = TRUE,
          status = ar$status,
          skip_reason = NULL
        )
        analysis$distance_from_germline <- c(analysis$distance_from_germline, ar$distance_from_germline)
        analysis$csr_events <- c(analysis$csr_events, ar$csr_events)
        analysis$isotype_switch_validity <- c(analysis$isotype_switch_validity, ar$isotype_switch_validity)
        analysis$csr_summary <- c(analysis$csr_summary, ar$csr_summary)
        analysis$arborescence[[length(analysis$arborescence) + 1L]] <- list(
          clone_id = cid,
          edges = ar$arborescence_edges
        )
      }

      analysis$batch_summary$clones_analyzed <- sum(vapply(
        analysis$per_clone_status,
        function(s) isTRUE(s$analyzed),
        logical(1)
      ))
      analysis$batch_summary$clones_skipped <- length(analysis$skipped_clones)
      analysis$batch_summary$csr_total <- length(analysis$csr_events)
      analysis$batch_summary$distance_rows <- length(analysis$distance_from_germline)
      analysis$csr_summary_fallback <- aggregate_csr_summary(analysis$csr_events)
    } else {
      for (cid in clone_ids) {
        n_seqs <- sum(df[[clone_col]] == cid, na.rm = TRUE)
        analysis$per_clone_status[[length(analysis$per_clone_status) + 1L]] <- list(
          clone_id = cid,
          n_seqs = n_seqs,
          analyzed = FALSE,
          status = "skipped",
          skip_reason = "CSR analysis disabled (enable_csr_analysis=false)"
        )
      }
      analysis$batch_summary$clones_skipped <- length(clone_ids)
    }

    analysis_seconds <- as.numeric(difftime(Sys.time(), analysis_start, units = "secs"))

    clone_counts <- clone_seq_counts(df, clone_col, clone_ids)
    clones_meta <- list(
      clone_id = as.list(unname(clone_ids)),
      seqs     = as.list(unname(clone_counts))
    )

    stats <- list(
      method                 = METHOD_ID,
      tree_type_requested    = tree_type,
      tree_type              = tree_type_effective,
      input_sequence_mode    = input_sequence_mode,
      species                = species,
      species_effective      = species_effective,
      algorithm              = algorithm,
      plot_type              = plot_type,
      plot_format            = plot_format,
      min_clone_size         = min_clone_size,
      gather_plots           = gather_plots,
      enable_csr_analysis    = enable_csr_analysis,
      sequence_column        = seq_col,
      clone_id_column        = clone_col,
      germline_id_column     = germ_col,
      label_column           = label_col,
      tip_id_column          = tip_id_col,
      isotype_column         = if (enable_csr_analysis) isotype_col else NULL,
      which_clones           = if (length(which_clones)) which_clones else NULL,
      ignore_clones          = if (length(ignore_clones)) ignore_clones else NULL,
      n_clones               = length(clone_ids),
      n_trees                = length(trees),
      tree_inference_seconds = tree_inference_seconds,
      analysis_seconds       = analysis_seconds,
      igphyml_fallback_to_dnapars = FALSE
    )

    add_log("brepphylo.summarise", TRUE, sprintf("Built %d trees for %d clones.", length(trees), length(clone_ids)))

    # Build the artifact bundle zip on disk — no base64 anywhere. The path
    # is then registered into artifact_files for materialize_artifacts to
    # copy into the run's artifact dir.
    bundle_zip_path <- NULL
    all_files <- list.files(out_dir, recursive = TRUE, full.names = TRUE)
    if (length(all_files)) {
      exclude_basenames <- unique(c(
        paste0("clone_", clone_ids, ".tree"),
        paste0("clone_", clone_ids, ".png"),
        paste0("clone_", clone_ids, ".pdf")
      ))
      files_to_zip <- all_files[!(basename(all_files) %in% exclude_basenames)]
      if (length(files_to_zip)) {
        zip_path <- file.path(out_dir, "brepphylo_artifacts.zip")
        if (file.exists(zip_path)) file.remove(zip_path)
        old_wd <- getwd()
        setwd(out_dir)
        on.exit(setwd(old_wd), add = TRUE)
        rel_paths <- unique(gsub(paste0("^", out_dir, "/?"), "", files_to_zip))
        rel_paths <- rel_paths[nzchar(rel_paths)]
        if (length(rel_paths)) {
          utils::zip(zipfile = zip_path, files = rel_paths)
          sz <- file.info(zip_path)$size
          if (!is.na(sz) && sz > 0) bundle_zip_path <- zip_path
        }
      }
    }

    # Assemble artifact_files: per-clone PNG and PDF figures (one entry per
    # file that actually exists) plus the bundle zip.
    artifact_files <- list()
    for (i in seq_along(clone_ids)) {
      cid <- clone_ids[[i]]
      p <- png_paths[[cid]]
      if (!is.null(p) && file.exists(p)) {
        artifact_files[[length(artifact_files) + 1L]] <- list(
          path = p,
          filename = sprintf("phylogeny_%d.png", i),
          kind = "image",
          role = "phylogeny",
          content_type = "image/png",
          previewable = TRUE,
          tree_index = i - 1L
        )
      }
      d <- pdf_paths[[cid]]
      if (!is.null(d) && file.exists(d)) {
        artifact_files[[length(artifact_files) + 1L]] <- list(
          path = d,
          filename = sprintf("phylogeny_%d.pdf", i),
          kind = "other",
          role = "phylogeny_pdf",
          content_type = "application/pdf",
          previewable = FALSE,
          tree_index = i - 1L
        )
      }
    }
    if (!is.null(bundle_zip_path) && file.exists(bundle_zip_path)) {
      artifact_files[[length(artifact_files) + 1L]] <- list(
        path = bundle_zip_path,
        filename = "brepphylo_artifacts.zip",
        kind = "zip",
        role = "clone_bundle_zip",
        content_type = "application/zip",
        previewable = FALSE
      )
    }

    list(
      ok = TRUE,
      trees = unname(trees),
      figures = NULL,
      annotations = annotations,
      clones = clones_meta,
      analysis = analysis,
      diagnostics = diagnostics,
      artifact_files = artifact_files,
      stats = stats,
      warnings = unname(as.list(warnings)),
      logs = logs,
      render = "phylogeny",
      error = NULL
    )
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

# ---------------------------------------------------------------------------
# Async job execution (/jobs contract) - per-job child Rscript process.
# ---------------------------------------------------------------------------
source_job_manager <- function() {
  for (base in c("/srv", getwd())) {
    p <- file.path(base, "job_manager.R")
    if (file.exists(p)) { source(p, local = FALSE); return(invisible(TRUE)) }
  }
  stop("job_manager.R not found")
}
source_job_manager()
JOB_MGR <- job_manager_new("brepphylo")
# Jobs that were running when this service last stopped can never finish: report
# them as failed so their runs do not wait for ever. Only the service does this;
# a job's own process (job_runner.R loads this file too) must not.
if (!identical(Sys.getenv("PHYLO_JOB_CHILD", ""), "1")) {
  closed <- tryCatch(job_manager_recover(JOB_MGR), error = function(e) {
    message(sprintf("[brepphylo] recovery of interrupted jobs failed: %s", conditionMessage(e)))
    0L
  })
  if (closed > 0L) message(sprintf("[brepphylo] closed %d job(s) interrupted by a restart", closed))
}
to_plumber_path <- function(p) gsub("\\{job_id\\}", "<job_id>", p, perl = TRUE)

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

  # Async jobs
  pr$handle("POST", ROUTES_JSON$jobs, serializer = SER, function(req, res) {
    body_raw <- req$postBody
    if (is.raw(body_raw)) body_raw <- rawToChar(body_raw)
    body <- tryCatch(jsonlite::fromJSON(body_raw, simplifyVector = FALSE), error = function(e) NULL)
    if (is.null(body) || !is.list(body)) { res$status <- 400; return(list(ok = FALSE, error = "JSON body required")) }
    job_id <- tryCatch(
      # timeout_seconds: optional time limit for this job, set by the worker
      # from the run's limit.
      job_manager_submit(
        JOB_MGR, body$file_path %||% NULL, body$params %||% list(), body$run_id %||% NULL,
        timeout_seconds = body$timeout_seconds
      ),
      error = function(e) e
    )
    if (inherits(job_id, "error")) { res$status <- 500; return(list(ok = FALSE, error = conditionMessage(job_id))) }
    if (is.list(job_id) && isTRUE(job_id$rejected)) {
      # Not started: 429 when waiting will help (the caller keeps the job
      # queued and retries), 507 when it cannot fit in this container at all.
      decision <- job_id$admission
      retryable <- identical(decision$code, RL_BUSY)
      res$status <- if (retryable) 429L else 507L
      if (retryable) res$setHeader("Retry-After", as.character(decision$retry_after_seconds))
      return(list(
        ok = FALSE, code = decision$code, error = decision$reason,
        retry_after_seconds = decision$retry_after_seconds,
        capacity = job_manager_capacity(JOB_MGR)
      ))
    }
    list(ok = TRUE, job_id = job_id, status = "QUEUED")
  })
  # What this service may use and how much of it is free right now.
  pr$handle("GET", ROUTES_JSON$capacity, serializer = SER, function(req, res) job_manager_capacity(JOB_MGR))
  pr$handle("GET", to_plumber_path(ROUTES_JSON$jobStatus), serializer = SER, function(req, res, job_id) {
    st <- job_manager_status(JOB_MGR, job_id)
    if (is.null(st)) { res$status <- 404; return(list(ok = FALSE, error = "Job not found")) }
    st
  })
  pr$handle("GET", to_plumber_path(ROUTES_JSON$jobResult), serializer = plumber::serializer_content_type("application/json"),
    function(req, res, job_id) {
      r <- job_manager_result(JOB_MGR, job_id)
      if (r$code == 404) { res$status <- 404; return('{"ok":false,"error":"Job not found"}') }
      if (r$code == 409) { res$status <- 409; return('{"ok":false,"error":"Job not finished"}') }
      readChar(r$path, file.info(r$path)$size, useBytes = TRUE)
    })
  cancel_fn <- function(req, res, job_id) {
    st <- job_manager_cancel(JOB_MGR, job_id)
    if (is.null(st)) { res$status <- 404; return(list(ok = FALSE, error = "Job not found")) }
    st
  }
  pr$handle("POST", to_plumber_path(ROUTES_JSON$jobCancel), serializer = SER, cancel_fn)
  pr$handle("DELETE", to_plumber_path(ROUTES_JSON$jobCancel), serializer = SER, cancel_fn)
  # The job's log as text, cut to the configured size (beginning and end kept).
  # Used by the worker to keep a log for jobs that could not upload their own.
  pr$handle("GET", to_plumber_path(ROUTES_JSON$jobLog), serializer = plumber::serializer_content_type("text/plain; charset=utf-8"),
    function(req, res, job_id) {
      found <- job_manager_log(JOB_MGR, job_id)
      if (is.null(found)) { res$status <- 404; return("Job not found") }
      res$setHeader("X-Log-Truncated", if (isTRUE(found$truncated)) "true" else "false")
      found$content
    })
  # Forget a finished job: the worker calls this once it has taken the result,
  # so nothing of the job stays on this container's disk.
  pr$handle("DELETE", to_plumber_path(ROUTES_JSON$job), serializer = SER, function(req, res, job_id) {
    code <- job_manager_delete(JOB_MGR, job_id)
    if (code == 404L) { res$status <- 404; return(list(ok = FALSE, error = "Job not found")) }
    if (code == 409L) { res$status <- 409; return(list(ok = FALSE, error = "Job is still running")) }
    list(ok = TRUE, job_id = job_id, deleted = TRUE)
  })

  pr_set_error(pr, function(req, res, err) {
    res$status <- 500
    list(ok = FALSE, error = as.character(err))
  })

  pr
}
