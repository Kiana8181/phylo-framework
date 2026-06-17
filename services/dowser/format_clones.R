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

  list(clones = clones, chain_qc = chain_qc, format_args = args)
}
