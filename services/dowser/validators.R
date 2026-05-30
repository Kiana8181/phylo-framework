# Dowser microservice validation helpers.
# Sourced by plumber.R; no side effects on load.

`%||%` <- function(x, y) {
  if (!is.null(x) && !(is.character(x) && length(x) == 1 && is.na(x))) x else y
}

ANALYSIS_MODE_ENUM <- c(
  "tree_only",
  "tree_with_internal_sequences",
  "discrete_trait_analysis",
  "time_evolution"
)

TREE_BUILD_ENUM <- c("pratchet", "pml", "dnapars", "dnaml", "igphyml", "raxml")
TRAIT_MODEL_ENUM <- c("unconstrained", "isotype_irreversible")
PARTITION_MODEL_ENUM <- c("single", "cf", "hl", "hlf", "hlc", "hlcf")
CHAIN_MODE_ENUM <- c("H", "HL")
ALTERNATIVE_ENUM <- c("greater", "less", "two.sided")

DEFAULT_ISOTYPE_ORDER <- c(
  "IGHM", "IGHD", "IGHG3", "IGHG1", "IGHA1",
  "IGHG2", "IGHG4", "IGHE", "IGHA2"
)
DEFAULT_ISOTYPE_EXCEPTIONS <- c("IGHD,IGHM")

REMOVED_PARAMS <- c(
  "apply_filters", "uppercase", "gap_policy", "noniupac_policy",
  "len_policy", "ig_stop_policy"
)

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
  val <- trimws(val)
  if (!nzchar(val)) return(default)
  val
}

dowser_validation_error <- function(message, step, details = NULL) {
  stop(structure(
    list(
      message = as.character(message),
      call = NULL,
      step = as.character(step),
      details = details
    ),
    class = c("dowser_validation", "error", "condition")
  ))
}

validate_partition_model <- function(p) {
  part <- p$partition_model %||% "single"
  if (!part %in% PARTITION_MODEL_ENUM) {
    return(list(
      ok = FALSE,
      error = sprintf("Unsupported partition_model: %s", part),
      step = "dowser.params.partition_model"
    ))
  }
  if (!identical(p$tree_build, "igphyml") && !identical(part, "single")) {
    return(list(
      ok = FALSE,
      error = "partition_model other than 'single' is currently supported only for tree_build='igphyml'.",
      step = "dowser.params.partition_model"
    ))
  }
  if (part %in% c("hl", "hlf", "hlc", "hlcf") && !identical(p$chain_mode, "HL")) {
    return(list(
      ok = FALSE,
      error = "partition_model 'hl', 'hlf', 'hlc', or 'hlcf' requires chain_mode='HL'.",
      step = "dowser.params.partition_model"
    ))
  }
  list(ok = TRUE)
}

validate_use_regions_columns <- function(db) {
  required <- c("v_region_start", "v_region_end", "j_region_start", "j_region_end")
  missing <- setdiff(required, names(db))
  if (length(missing)) {
    return(list(
      ok = FALSE,
      error = sprintf(
        "use_regions=TRUE requires region columns: %s (missing: %s).",
        paste(required, collapse = ", "),
        paste(missing, collapse = ", ")
      ),
      step = "dowser.params.use_regions"
    ))
  }
  list(ok = TRUE)
}

reject_removed_params <- function(params) {
  present <- intersect(REMOVED_PARAMS, names(params))
  if (length(present)) {
    return(sprintf(
      "Removed parameter(s) no longer supported (data integrity): %s. Dowser no longer mutates sequence/germline alignment data.",
      paste(present, collapse = ", ")
    ))
  }
  if ("tree_model" %in% names(params)) {
    return("Removed parameter no longer supported: tree_model. Use tree_build instead.")
  }
  NULL
}

resolve_tree_build <- function(p) {
  build <- normalize_col(p$tree_build, NULL)
  build <- build %||% "pratchet"
  if (!build %in% TREE_BUILD_ENUM) {
    return(list(
      ok = FALSE,
      error = sprintf(
        "tree_build must be one of: %s",
        paste(TREE_BUILD_ENUM, collapse = ", ")
      )
    ))
  }
  list(ok = TRUE, build = build)
}

validate_analysis_mode <- function(mode) {
  mode <- normalize_col(mode, "tree_only")
  if (!mode %in% ANALYSIS_MODE_ENUM) {
    return(sprintf(
      "analysis_mode must be one of: %s",
      paste(ANALYSIS_MODE_ENUM, collapse = ", ")
    ))
  }
  NULL
}

validate_fast_extension <- function(path) {
  ext <- tolower(tools::file_ext(path))
  if (ext %in% c("fasta", "fa", "fna", "faa")) {
    return(paste0(
      "Dowser requires aligned AIRR/Change-O clone table input with sequence_alignment, ",
      "germline_alignment_d_mask, and clone metadata. Raw FASTA must be processed by an ",
      "AIRR/Change-O/IgBLAST/IMGT adapter before running Dowser."
    ))
  }
  if (!ext %in% c("tsv", "txt", "csv", "rds", "rda", "rdata")) {
    return(sprintf("Unsupported file extension: %s", ext))
  }
  NULL
}

validate_required_columns <- function(db, cols) {
  missing <- setdiff(cols, names(db))
  if (length(missing)) {
    return(paste0(
      "Input missing required columns for Dowser: ",
      paste(missing, collapse = ", "),
      ". Upload a Change-O clone table (e.g. clone-pass.tsv)."
    ))
  }
  NULL
}

validate_sequence_id_uniqueness <- function(db, id_col = "sequence_id") {
  ids <- as.character(db[[id_col]])
  empty <- is.na(ids) | !nzchar(trimws(ids))
  if (any(empty)) {
    bad <- which(empty)[1:min(5, sum(empty))]
    return(list(
      ok = FALSE,
      error = sprintf(
        "Empty %s values are not allowed (%d rows). Example row indices: %s",
        id_col, sum(empty), paste(bad, collapse = ", ")
      ),
      step = "dowser.validate.sequence_id"
    ))
  }
  dup <- ids[duplicated(ids)]
  if (length(dup)) {
    return(list(
      ok = FALSE,
      error = sprintf(
        "Duplicate %s values found (%d duplicates). Example: %s",
        id_col, length(unique(dup)), paste(head(unique(dup), 3), collapse = ", ")
      ),
      step = "dowser.validate.sequence_id"
    ))
  }
  list(ok = TRUE)
}

validate_label_field_uniqueness <- function(db, label_field, id_col = "sequence_id") {
  if (is.null(label_field) || !nzchar(label_field) || identical(label_field, id_col)) {
    return(list(ok = TRUE, unique = TRUE, use_display = FALSE))
  }
  if (!label_field %in% names(db)) {
    return(list(
      ok = TRUE,
      unique = FALSE,
      use_display = FALSE,
      warning = sprintf("Label column '%s' not found; display Newick omitted.", label_field)
    ))
  }
  labels <- as.character(db[[label_field]])
  labels[is.na(labels) | !nzchar(trimws(labels))] <- as.character(db[[id_col]])[
    is.na(labels) | !nzchar(trimws(labels))
  ]
  dup <- labels[duplicated(labels)]
  if (length(dup)) {
    return(list(
      ok = TRUE,
      unique = FALSE,
      use_display = FALSE,
      warning = sprintf(
        "label_field '%s' is not unique (%d duplicated values); display Newick omitted. Canonical Newick uses sequence_id.",
        label_field, length(unique(dup))
      )
    ))
  }
  list(ok = TRUE, unique = TRUE, use_display = TRUE)
}

validate_trait_for_dta <- function(db, trait_field, exclude_missing = TRUE) {
  if (is.null(trait_field) || !nzchar(trait_field)) {
    return(list(ok = FALSE, error = "trait_field is required for discrete_trait_analysis.", step = "dowser.validate.trait"))
  }
  if (startsWith(trait_field, ".plot_")) {
    return(list(
      ok = FALSE,
      error = "Plot-only columns cannot be used as biological DTA traits.",
      step = "dowser.validate.trait_field"
    ))
  }
  if (!trait_field %in% names(db)) {
    return(list(
      ok = FALSE,
      error = sprintf("trait_field '%s' not found in input table.", trait_field),
      step = "dowser.validate.trait"
    ))
  }
  vals <- as.character(db[[trait_field]])
  missing <- is.na(vals) | !nzchar(trimws(vals))
  n_missing <- sum(missing)
  excluded <- integer(0)
  if (n_missing > 0 && exclude_missing) {
    excluded <- which(missing)
  } else if (n_missing > 0) {
    return(list(
      ok = FALSE,
      error = sprintf(
        "trait_field '%s' has %d missing/empty values; missing traits cannot be treated as biological states in DTA.",
        trait_field, n_missing
      ),
      step = "dowser.validate.trait"
    ))
  }
  list(ok = TRUE, n_missing = n_missing, excluded_rows = excluded)
}

validate_isotype_states <- function(db, trait_field, isotype_order) {
  observed <- unique(as.character(db[[trait_field]]))
  observed <- observed[!is.na(observed) & nzchar(trimws(observed))]
  missing <- setdiff(observed, isotype_order)
  if (length(missing)) {
    return(list(
      ok = FALSE,
      error = sprintf(
        "Observed c_call values not covered by isotype_order: %s",
        paste(missing, collapse = ", ")
      ),
      step = "dowser.validate.isotype_order",
      details = list(missing_states = as.list(missing), observed = as.list(observed))
    ))
  }
  list(ok = TRUE)
}

validate_chain_mode_hl <- function(db, cell_col, locus_col, heavy_locus) {
  missing <- setdiff(c(cell_col, locus_col), names(db))
  if (length(missing)) {
    return(list(
      ok = FALSE,
      error = sprintf(
        "chain_mode=HL requires columns %s and %s (missing: %s).",
        cell_col, locus_col, paste(missing, collapse = ", ")
      ),
      step = "dowser.validate.chain_mode"
    ))
  }
  loci <- unique(as.character(db[[locus_col]]))
  loci <- loci[!is.na(loci) & nzchar(trimws(loci))]
  if (!heavy_locus %in% loci) {
    return(list(
      ok = FALSE,
      error = sprintf("heavy_locus '%s' not found in locus column '%s'.", heavy_locus, locus_col),
      step = "dowser.validate.chain_mode"
    ))
  }
  light <- setdiff(loci, heavy_locus)
  if (!length(light)) {
    return(list(
      ok = FALSE,
      error = "No light-chain loci found for chain_mode=HL.",
      step = "dowser.validate.chain_mode"
    ))
  }
  list(ok = TRUE, light_loci = light)
}

is_falsey <- function(x) {
  !is.na(x) && x %in% c(FALSE, "F", "false", "0", 0)
}

is_truthy <- function(x) {
  !is.na(x) && x %in% c(TRUE, "T", "true", "1", 1)
}

validate_igphyml_sequences <- function(db, id_col = "sequence_id", clone_col = "clone_id", seq_col = "sequence_alignment") {
  n <- nrow(db)
  if (n == 0) return(list(ok = TRUE))

  airr_fields <- c("productive", "vj_in_frame", "stop_codon", "complete_vdj")
  has_airr <- any(airr_fields %in% names(db))

  bad_idx <- rep(FALSE, n)
  reason_map <- vector("list", n)

  add_reason <- function(idx, reason) {
    if (!length(idx)) return(invisible(NULL))
    bad_idx[idx] <<- TRUE
    for (i in idx) {
      reason_map[[i]] <<- unique(c(reason_map[[i]] %||% character(0), reason))
    }
  }

  if ("productive" %in% names(db)) {
    add_reason(which(vapply(db$productive, is_falsey, logical(1))), "productive=false")
  }
  if ("vj_in_frame" %in% names(db)) {
    add_reason(which(vapply(db$vj_in_frame, is_falsey, logical(1))), "vj_in_frame=false")
  }
  if ("stop_codon" %in% names(db)) {
    add_reason(which(vapply(db$stop_codon, is_truthy, logical(1))), "stop_codon=true")
  }
  if ("complete_vdj" %in% names(db)) {
    add_reason(which(vapply(db$complete_vdj, is_falsey, logical(1))), "complete_vdj=false")
  }

  if (!has_airr && seq_col %in% names(db)) {
    gap_re <- "[-\\.\\s]"
    x <- toupper(gsub(gap_re, "", as.character(db[[seq_col]]), perl = TRUE))
    x[is.na(x)] <- ""
    frame_bad <- (nchar(x) %% 3) != 0 & nzchar(x)
    stop_bad <- rep(FALSE, n)
    ok <- !frame_bad & nzchar(x)
    if (any(ok) && requireNamespace("Biostrings", quietly = TRUE)) {
      aa <- Biostrings::translate(Biostrings::DNAStringSet(x[ok]), if.fuzzy.codon = "X")
      stop_bad[ok] <- grepl("\\*", as.character(aa))
    }
    add_reason(which(stop_bad), "heuristic_stop_codon")
    add_reason(which(frame_bad), "heuristic_out_of_frame")
  }

  if (!any(bad_idx)) {
    if (!has_airr) {
      return(list(
        ok = TRUE,
        warnings = "IgPhyML sequence validity fields were not present; only conservative checks were applied."
      ))
    }
    return(list(ok = TRUE))
  }

  bad_rows <- which(bad_idx)
  records <- lapply(bad_rows, function(i) {
    list(
      sequence_id = if (id_col %in% names(db)) as.character(db[[id_col]][i]) else NA_character_,
      clone_id = if (clone_col %in% names(db)) as.character(db[[clone_col]][i]) else NA_character_,
      reason = paste(reason_map[[i]], collapse = ";")
    )
  })

  summary <- list(
    n_stop_codon = sum(vapply(records, function(r) grepl("stop_codon=true", r$reason), logical(1))),
    n_vj_out_of_frame = sum(vapply(records, function(r) grepl("vj_in_frame=false", r$reason), logical(1))),
    n_non_productive = sum(vapply(records, function(r) grepl("productive=false", r$reason), logical(1))),
    n_incomplete_vdj = sum(vapply(records, function(r) grepl("complete_vdj=false", r$reason), logical(1)))
  )

  truncated <- length(records) > 100
  if (truncated) records <- records[1:100]

  list(
    ok = FALSE,
    error = sprintf(
      "IgPhyML requires productive in-frame sequences without in-frame stop codons. Found %d problematic records.",
      sum(bad_idx)
    ),
    step = "dowser.preflight.igphyml.sequence_validity",
    details = list(
      records = records,
      summary = summary,
      truncated = truncated
    )
  )
}

clone_meta_data_frame <- function(meta) {
  if (inherits(meta, "data.frame")) return(meta)
  if (methods::is(meta, "airrClone") && "data" %in% methods::slotNames(meta)) {
    df <- methods::slot(meta, "data")
    if (inherits(df, "data.frame")) return(df)
  }
  NULL
}

igphyml_validation_db_from_clones <- function(clones) {
  if (is.null(clones) || !inherits(clones, "data.frame") || !nrow(clones)) return(NULL)
  if (!"data" %in% names(clones)) return(clones)

  rows <- list()
  for (i in seq_len(nrow(clones))) {
    df <- clone_meta_data_frame(clones$data[[i]])
    if (is.null(df) || !nrow(df)) next
    if (!"clone_id" %in% names(df) && "clone_id" %in% names(clones)) {
      df$clone_id <- as.character(clones$clone_id[[i]])
    }
    rows[[length(rows) + 1L]] <- df
  }
  if (!length(rows)) return(NULL)
  all_names <- unique(unlist(lapply(rows, names), use.names = FALSE))
  rows <- lapply(rows, function(df) {
    missing <- setdiff(all_names, names(df))
    for (col in missing) df[[col]] <- NA
    df[, all_names, drop = FALSE]
  })
  do.call(rbind, rows)
}

validate_igphyml_sequences_after_format_clones <- function(clones) {
  db <- igphyml_validation_db_from_clones(clones)
  if (is.null(db)) {
    return(list(
      ok = TRUE,
      warnings = "IgPhyML sequence validity could not inspect formatted clone records; relying on Dowser/IgPhyML runtime checks."
    ))
  }
  validate_igphyml_sequences(db)
}

validate_clone_consistency <- function(db, clone_col, seq_col, germ_col, junc_col, v_col, j_col, id_col = "sequence_id") {
  issues <- list()
  length_mismatch_rows <- list()
  n_missing_seq <- 0L
  n_missing_germ <- 0L
  n_length_mismatch <- 0L

  for (i in seq_len(nrow(db))) {
    seqs <- as.character(db[[seq_col]][i])
    germs <- as.character(db[[germ_col]][i])
    if (is.na(seqs) || !nzchar(trimws(seqs))) n_missing_seq <- n_missing_seq + 1L
    if (is.na(germs) || !nzchar(trimws(germs))) n_missing_germ <- n_missing_germ + 1L
    lens <- nchar(seqs)
    glens <- nchar(germs)
    if (!is.na(lens) && !is.na(glens) && lens != glens) {
      n_length_mismatch <- n_length_mismatch + 1L
      if (length(length_mismatch_rows) < 50) {
        length_mismatch_rows[[length(length_mismatch_rows) + 1]] <- list(
          sequence_id = as.character(db[[id_col]][i]),
          clone_id = as.character(db[[clone_col]][i]),
          reason = "length_mismatch"
        )
      }
    }
  }

  for (cid in unique(as.character(db[[clone_col]]))) {
    rows <- db[[clone_col]] == cid
    if (junc_col %in% names(db)) {
      jvals <- db[[junc_col]][rows]
      if (length(unique(jvals[!is.na(jvals)])) > 1) {
        issues[[length(issues) + 1]] <- list(clone_id = cid, issue = "inconsistent_junction_length")
      }
    }
  }

  list(
    n_missing_sequence_alignment = n_missing_seq,
    n_missing_germline_alignment = n_missing_germ,
    n_length_mismatch = n_length_mismatch,
    length_mismatch = length_mismatch_rows,
    clone_issues = issues
  )
}

build_excluded_missing_trait <- function(db, excluded_rows, trait_field, clone_col = "clone_id", id_col = "sequence_id") {
  if (!length(excluded_rows)) return(list())
  lapply(excluded_rows[1:min(50, length(excluded_rows))], function(i) {
    list(
      sequence_id = as.character(db[[id_col]][i]),
      clone_id = as.character(db[[clone_col]][i]),
      trait_field = trait_field,
      reason = "missing_trait"
    )
  })
}

validate_junction_length <- function(db) {
  raw <- db$junction_length
  parsed <- suppressWarnings(as.integer(as.character(raw)))
  raw_chr <- trimws(as.character(raw))
  bad <- is.na(parsed) | parsed <= 0L | !grepl("^\\d+$", raw_chr, perl = TRUE)

  if (any(bad)) {
    records <- lapply(which(bad), function(i) {
      list(
        row = i,
        sequence_id = as.character(db$sequence_id[i] %||% NA_character_),
        clone_id = as.character(db$clone_id[i] %||% NA_character_),
        junction_length = as.character(raw[i] %||% NA_character_),
        reason = "junction_length_missing_non_numeric_or_non_positive"
      )
    })

    dowser_validation_error(
      sprintf("junction_length has %d invalid row-level values.", length(records)),
      step = "dowser.validate.junction_length",
      details = list(records = records)
    )
  }

  db$junction_length <- parsed
  db
}

validate_alignment_presence <- function(db,
                                        seq_col = "sequence_alignment",
                                        germ_col = "germline_alignment_d_mask") {
  missing_seq <- is.na(db[[seq_col]]) | !nzchar(trimws(as.character(db[[seq_col]])))
  missing_germ <- is.na(db[[germ_col]]) | !nzchar(trimws(as.character(db[[germ_col]])))

  bad <- missing_seq | missing_germ
  if (any(bad)) {
    records <- lapply(which(bad), function(i) {
      reasons <- character(0)
      if (missing_seq[i]) reasons <- c(reasons, "missing_sequence_alignment")
      if (missing_germ[i]) reasons <- c(reasons, "missing_germline_alignment_d_mask")

      list(
        row = i,
        sequence_id = as.character(db$sequence_id[i] %||% NA_character_),
        clone_id = as.character(db$clone_id[i] %||% NA_character_),
        reason = paste(reasons, collapse = ",")
      )
    })

    dowser_validation_error(
      sprintf("Found %d rows with missing sequence/germline alignment values.", length(records)),
      step = "dowser.validate.alignment_missing",
      details = list(records = records)
    )
  }

  invisible(TRUE)
}

validate_sequence_ids_for_mapping <- function(db, id_col = "sequence_id") {
  ids <- as.character(db[[id_col]])
  missing <- is.na(ids) | !nzchar(trimws(ids))
  duplicated_ids <- duplicated(ids) | duplicated(ids, fromLast = TRUE)
  unsafe <- grepl("[\\s;:=,\\(\\)\\[\\]'\\\"]", ids, perl = TRUE)

  bad <- missing | duplicated_ids | unsafe
  if (any(bad)) {
    records <- lapply(which(bad), function(i) {
      reasons <- character(0)
      if (missing[i]) reasons <- c(reasons, "missing_sequence_id")
      if (duplicated_ids[i]) reasons <- c(reasons, "duplicate_sequence_id")
      if (unsafe[i]) reasons <- c(reasons, "unsafe_sequence_id_for_newick_mapping")

      list(
        row = i,
        sequence_id = ids[i],
        clone_id = as.character(db$clone_id[i] %||% NA_character_),
        reason = paste(reasons, collapse = ",")
      )
    })

    dowser_validation_error(
      sprintf(
        "Found %d sequence_id values that are missing, duplicated, or unsafe for stable tree mapping.",
        length(records)
      ),
      step = "dowser.validate.sequence_id_mapping",
      details = list(records = records)
    )
  }

  invisible(TRUE)
}

build_duplicate_sequence_ids <- function(db, id_col = "sequence_id") {
  ids <- as.character(db[[id_col]])
  dup <- ids[duplicated(ids)]
  if (!length(dup)) return(list())
  unique(dup)
}

init_input_qc <- function(db_original, clone_col = "clone_id", id_col = "sequence_id") {
  list(
    n_rows_original = nrow(db_original),
    n_clones_original = length(unique(as.character(db_original[[clone_col]]))),
    n_rows_after_derived_fields = nrow(db_original),
    n_rows_after_trait_exclusion = nrow(db_original),
    n_clones_after_trait_exclusion = length(unique(as.character(db_original[[clone_col]]))),
    n_clones_after_formatClones = NA_integer_,
    excluded_missing_trait = list(),
    length_mismatch = list(),
    duplicate_sequence_ids = build_duplicate_sequence_ids(db_original, id_col)
  )
}
