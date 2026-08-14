# Trait-aware formatClones wrapper including paired H/L support.
# Uses canonical AIRR column names (mapped upstream via API prepare).

resolve_paired_chains <- function(db, p) {
  chain_mode <- p$chain_mode %||% "H"
  if (!identical(chain_mode, "HL")) {
    return(list(db = db, chain_qc = list(chain_mode = "H")))
  }

  heavy <- p$heavy_locus %||% "IGH"
  v <- validate_chain_mode_hl(db, "cell_id", "locus", heavy)
  if (!isTRUE(v$ok)) {
    dowser_validation_error(v$error, step = v$step)
  }

  n_before <- nrow(db)
  resolved <- tryCatch(
    dowser::resolveLightChains(
      db,
      cell = "cell_id",
      locus = "locus",
      heavy = heavy
    ),
    error = function(e) e
  )
  if (inherits(resolved, "error")) {
    dowser_validation_error(
      sprintf("resolveLightChains failed: %s", conditionMessage(resolved)),
      step = "dowser.validate.paired_chains",
      details = list(reason = conditionMessage(resolved))
    )
  }

  n_after <- nrow(resolved)
  chain_qc <- list(
    chain_mode = "HL",
    n_input_rows = n_before,
    n_after_resolve = n_after,
    n_dropped = max(0L, n_before - n_after),
    heavy_locus = heavy,
    light_loci = as.list(v$light_loci),
    cell_id_column = "cell_id",
    locus_column = "locus"
  )

  list(db = resolved, chain_qc = chain_qc)
}

build_format_clones_args <- function(db, p) {
  trait_fields <- parse_vec(p$trait_fields)
  if (!length(trait_fields) && !is.null(p$trait_field) && nzchar(p$trait_field)) {
    trait_fields <- parse_vec(p$trait_field)
  }
  trait_fields <- trait_fields[!startsWith(trait_fields, ".plot_")]

  annotation_fields <- parse_vec(p$annotation_fields)
  tip_col <- p$tip_color_by
  if (is.character(tip_col) && length(tip_col) == 1 && !nzchar(tip_col)) tip_col <- NULL

  default_num <- c("duplicate_count", "umi_count", "clone_count", "consensus_count")
  user_num <- parse_vec(p$numeric_annotation_fields)
  mode <- p$analysis_mode %||% "tree_only"
  if (identical(mode, "time_evolution") && !is.null(p$time_field) && nzchar(p$time_field)) {
    user_num <- unique(c(user_num, p$time_field))
  }
  num_keep <- intersect(unique(c(default_num, user_num)), names(db))

  text_keep <- unique(c(trait_fields, annotation_fields, tip_col))
  text_keep <- intersect(text_keep, names(db))
  text_keep <- setdiff(text_keep, num_keep)

  extra_columns <- unique(c(text_keep, num_keep, parse_vec(p$columns)))
  extra_columns <- intersect(extra_columns, names(db))

  use_traits <- if (identical(mode, "discrete_trait_analysis")) trait_fields else trait_fields

  args <- list(
    db = db,
    seq = "sequence_alignment",
    germ = "germline_alignment_d_mask",
    clone = "clone_id",
    id = "sequence_id",
    v_call = "v_call",
    j_call = "j_call",
    junc_len = "junction_length",
    text_fields = if (length(text_keep)) text_keep else NULL,
    num_fields = if (length(num_keep)) num_keep else NULL,
    columns = if (length(extra_columns)) extra_columns else NULL,
    collapse = isTRUE(p$collapse_identical_sequences %||% TRUE),
    randomize = FALSE,
    minseq = as.integer(p$minseq %||% 3L),
    nproc = as.integer(p$nproc %||% 1L),
    mod3 = isTRUE(p$mod3 %||% FALSE),
    filterstop = isTRUE(p$filterstop %||% FALSE),
    use_regions = isTRUE(p$use_regions %||% FALSE)
  )

  if (length(use_traits)) args$traits <- use_traits

  if (identical(p$chain_mode, "HL")) {
    args$chain <- "HL"
    args$cell <- "cell_id"
    args$locus <- "locus"
    if (!is.null(p$split_light)) args$split_light <- isTRUE(p$split_light)
    if (!is.null(p$light_traits)) args$light_traits <- isTRUE(p$light_traits)
    if (!is.null(p$majoronly)) args$majoronly <- isTRUE(p$majoronly)
  }

  args
}

# Collect the sequence_id values retained inside the returned airrClone objects.
# Post-formatClones the alignment column is renamed from `sequence_alignment` to
# `sequence` inside each @data slot (see validators.R), so callers must be able to
# read the alignment under either name.
retained_records_from_clones <- function(clones, id_col = "sequence_id") {
  if (is.null(clones) || !inherits(clones, "data.frame") || !nrow(clones)) {
    return(NULL)
  }
  if (!"data" %in% names(clones)) return(NULL)

  ids <- character(0)
  aligns <- character(0)
  for (i in seq_len(nrow(clones))) {
    df <- clone_meta_data_frame(clones$data[[i]])
    if (is.null(df) || !nrow(df)) next
    if (!id_col %in% names(df)) next
    align_col <- if ("sequence" %in% names(df)) {
      "sequence"
    } else if ("sequence_alignment" %in% names(df)) {
      "sequence_alignment"
    } else {
      NA_character_
    }
    ids <- c(ids, as.character(df[[id_col]]))
    aligns <- c(
      aligns,
      if (is.na(align_col)) rep(NA_character_, nrow(df)) else as.character(df[[align_col]])
    )
  }
  if (!length(ids)) return(NULL)
  data.frame(sequence_id = ids, alignment = aligns, stringsAsFactors = FALSE)
}

normalize_alignment_for_mapping <- function(x) {
  x <- as.character(x)
  x[is.na(x)] <- ""
  toupper(gsub("[.\\-[:space:]]", "", x, perl = TRUE))
}

# Determine which input sequence_ids were folded away by formatClones and, for each,
# which retained record represents it (matched on identical alignment).
compute_collapse_mapping <- function(db_arg, clones, id_col = "sequence_id",
                                     seq_col = "sequence_alignment") {
  empty <- list(
    entries = list(),
    warnings = character(0),
    n_input_ids = 0L,
    n_retained_ids = 0L,
    n_collapsed = 0L,
    n_dropped_no_alignment_match = 0L,
    n_ambiguous = 0L,
    available = FALSE
  )
  if (is.null(db_arg) || !inherits(db_arg, "data.frame") || !nrow(db_arg)) return(empty)
  if (!id_col %in% names(db_arg)) return(empty)

  retained <- retained_records_from_clones(clones, id_col = id_col)
  if (is.null(retained)) return(empty)

  input_ids <- as.character(db_arg[[id_col]])
  input_aligns <- if (seq_col %in% names(db_arg)) {
    as.character(db_arg[[seq_col]])
  } else {
    rep(NA_character_, length(input_ids))
  }
  input_alignment_keys <- normalize_alignment_for_mapping(input_aligns)
  retained$alignment_key <- normalize_alignment_for_mapping(retained$alignment)
  retained_ids <- unique(retained$sequence_id)
  collapsed_ids <- setdiff(input_ids, retained_ids)

  entries <- list()
  warns <- character(0)
  n_collapsed <- 0L
  n_nomatch <- 0L
  n_ambig <- 0L
  retained_nonempty <- retained$alignment[!is.na(retained$alignment) & nzchar(retained$alignment)]
  retained_lengths <- if (length(retained_nonempty)) nchar(retained_nonempty) else integer(0)

  for (cid in collapsed_ids) {
    idx <- match(cid, input_ids)
    aln <- if (is.na(idx)) NA_character_ else input_aligns[[idx]]

    reps <- character(0)
    if (!is.na(aln) && nzchar(aln)) {
      aln_key <- input_alignment_keys[[idx]]
      cand <- retained$sequence_id[nzchar(retained$alignment_key) &
        retained$alignment_key == aln_key]
      # Order candidates by their position in the original input rows so the
      # choice is deterministic rather than dependent on clone iteration order.
      cand <- unique(cand)
      reps <- cand[order(match(cand, input_ids))]
      if (!length(reps)) {
        # formatClones can re-align or pad a retained sequence. Fall back to
        # the normalized pre-formatClones alignment to preserve the original
        # sequence_id relationship in that case.
        retained_input <- input_ids %in% retained_ids
        cand <- input_ids[retained_input & input_alignment_keys == aln_key]
        reps <- unique(cand[order(match(cand, input_ids))])
      }
    }

    if (!length(reps)) {
      aln_key <- if (is.na(idx) || is.na(aln) || !nzchar(aln)) "" else input_alignment_keys[[idx]]
      entries[[length(entries) + 1L]] <- list(
        collapsed = cid,
        representative = "",
        reason = if (nzchar(aln_key) && length(retained_lengths) &&
          !any(nchar(retained$alignment_key[nzchar(retained$alignment_key)]) == nchar(aln_key))) {
          "dropped_by_formatClones_alignment_length_mismatch"
        } else {
          "dropped_by_formatClones_no_alignment_match"
        }
      )
      n_nomatch <- n_nomatch + 1L
    } else if (length(reps) > 1L) {
      entries[[length(entries) + 1L]] <- list(
        collapsed = cid,
        representative = reps[[1]],
        reason = "dropped_by_formatClones_ambiguous_match"
      )
      n_ambig <- n_ambig + 1L
      warns <- c(warns, sprintf(
        paste0(
          "Collapsed sequence_id '%s' matches %d retained records by identical alignment ",
          "(%s); the first in input row order was recorded as its representative."
        ),
        cid, length(reps), paste(reps, collapse = ", ")
      ))
    } else {
      entries[[length(entries) + 1L]] <- list(
        collapsed = cid,
        representative = reps[[1]],
        reason = "collapsed_by_formatClones"
      )
      n_collapsed <- n_collapsed + 1L
    }
  }
  # Deterministic ordering so the emitted TSV is byte-stable across runs.
  if (length(entries)) {
    entries <- entries[order(vapply(entries, function(e) e$collapsed, character(1)))]
  }

  list(
    entries = entries,
    warnings = warns,
    n_input_ids = length(unique(input_ids)),
    n_retained_ids = length(retained_ids),
    n_collapsed = n_collapsed,
    n_dropped_no_alignment_match = n_nomatch,
    n_ambiguous = n_ambig,
    available = TRUE
  )
}

run_format_clones <- function(db, p) {
  if (isTRUE(p$use_regions %||% FALSE)) {
    ur <- validate_use_regions_columns(db)
    if (!isTRUE(ur$ok)) {
      dowser_validation_error(ur$error, step = ur$step)
    }
  }

  paired <- resolve_paired_chains(db, p)
  db <- paired$db
  chain_qc <- paired$chain_qc

  args <- build_format_clones_args(db, p)
  db_arg <- args$db
  args$db <- NULL

  clones <- do.call(dowser::formatClones, c(list(db_arg), args))

  # Record which input sequences formatClones folded away, and into which
  # representative. Failure to compute the mapping must never abort the run.
  collapse_mapping <- tryCatch(
    compute_collapse_mapping(
      db_arg,
      clones,
      id_col = args$id %||% "sequence_id",
      seq_col = args$seq %||% "sequence_alignment"
    ),
    error = function(e) list(
      entries = list(),
      warnings = sprintf("Collapse mapping could not be computed: %s", conditionMessage(e)),
      n_input_ids = 0L, n_retained_ids = 0L, n_collapsed = 0L,
      n_dropped_no_alignment_match = 0L, n_ambiguous = 0L, available = FALSE
    )
  )

  list(
    clones = clones,
    chain_qc = chain_qc,
    format_args = args,
    collapse_mapping = collapse_mapping
  )
}
