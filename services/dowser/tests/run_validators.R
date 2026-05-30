#!/usr/bin/env Rscript

root_dir <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- sub("^--file=", "", args[grep("^--file=", args)])
  if (length(file_arg) && nzchar(file_arg[1])) {
    return(normalizePath(file.path(dirname(file_arg[1]), ".."), mustWork = FALSE))
  }
  normalizePath("services/dowser", mustWork = FALSE)
}

root <- root_dir()
for (mod in c(
  "validators.R", "data_io.R", "format_clones.R", "tree_build.R",
  "dta.R", "time_evolution.R", "internal_seqs.R", "exports.R", "handlers.R"
)) {
  source(file.path(root, mod))
}

failures <- 0L
assert_true <- function(cond, msg) {
  if (!isTRUE(cond)) {
    cat("FAIL:", msg, "\n")
    failures <<- failures + 1L
  }
}
assert_equal <- function(a, b, msg) {
  if (!identical(a, b)) {
    cat("FAIL:", msg, "\n")
    failures <<- failures + 1L
  }
}

# 1. FASTA rejected
fasta_err <- validate_fast_extension("input.fasta")
assert_true(!is.null(fasta_err), "FASTA extension rejected")
assert_true(grepl("Raw FASTA", fasta_err, fixed = TRUE), "FASTA error mentions adapter requirement")

# 2. junction_length derivation
db_junc <- data.frame(
  sequence_id = c("s1", "s2", "s3"),
  clone_id = c("c1", "c1", "c1"),
  sequence_alignment = c("ACGTACGT", "ACGTACGA", "ACGTACGC"),
  germline_alignment_d_mask = c("ACGTACGT", "ACGTACGT", "ACGTACGT"),
  v_call = rep("IGHV1*01", 3),
  j_call = rep("IGHJ4*01", 3),
  junction = c("AAA", "AAAA", "AAAAA"),
  stringsAsFactors = FALSE
)
prep <- prepare_db_working(db_junc, list())
assert_true("junction_length" %in% names(prep$db_working), "junction_length derived")
assert_equal(prep$db_working$junction_length, c(3L, 4L, 5L), "junction_length values correct")
assert_true(length(prep$data_provenance$transformations) >= 1, "provenance recorded for derivation")

# 3. missing both junction_length and junction fails
db_none <- db_junc[, setdiff(names(db_junc), "junction"), drop = FALSE]
failed <- FALSE
tryCatch(
  prepare_db_working(db_none, list()),
  error = function(e) { failed <<- TRUE }
)
assert_true(failed, "missing junction_length and junction fails")

# 4. removed filter params rejected via dowser_validation_error
removed_msg <- reject_removed_params(list(apply_filters = TRUE, gap_policy = "remove"))
assert_true(!is.null(removed_msg), "deprecated apply_filters rejected message exists")
tree_model_msg <- reject_removed_params(list(tree_model = "mp"))
assert_true(grepl("Use tree_build instead", tree_model_msg, fixed = TRUE), "deprecated tree_model rejected message exists")
removed_err <- tryCatch(
  dowser_validation_error(removed_msg, step = "dowser.params.removed"),
  error = function(e) e
)
assert_true(inherits(removed_err, "dowser_validation"), "dowser_validation class set")
assert_equal(removed_err$step, "dowser.params.removed", "removed param step correct")
assert_true(inherits(removed_err, "error"), "dowser_validation is error condition")
assert_true(inherits(removed_err, "condition"), "dowser_validation is condition")

# 5. invalid tree build step
tryCatch(
  dowser_validation_error("bad build", step = "dowser.params.tree_build", details = list(foo = "bar")),
  error = function(e) {
    assert_equal(e$step, "dowser.params.tree_build", "tree build step correct")
    assert_equal(e$details$foo, "bar", "custom error details included")
  }
)

# 6. trait validation for DTA
db_trait <- db_junc
db_trait$c_call <- c("IGHM", "IGHG1", NA)
tv <- validate_trait_for_dta(db_trait, "c_call", exclude_missing = TRUE)
assert_true(isTRUE(tv$ok), "DTA trait validation ok with exclusions")
assert_equal(length(tv$excluded_rows), 1L, "one missing trait row excluded")

# 7. missing trait not accepted as biological state when exclude=false
tv_fail <- validate_trait_for_dta(db_trait, "c_call", exclude_missing = FALSE)
assert_true(!isTRUE(tv_fail$ok), "missing trait fails when exclusion disabled")

# 8. DTA rejects .plot_* trait fields
tv_plot <- validate_trait_for_dta(db_trait, ".plot_c_call", exclude_missing = TRUE)
assert_true(!isTRUE(tv_plot$ok), ".plot_* trait field rejected")
assert_equal(tv_plot$step, "dowser.validate.trait_field", ".plot_* trait field step correct")

# 9. label_field uniqueness
db_label <- db_junc
db_label$display <- c("a", "a", "b")
lc <- validate_label_field_uniqueness(db_label, "display", "sequence_id")
assert_true(!isTRUE(lc$use_display), "non-unique label_field disables display newick")
assert_true(!is.null(lc$warning), "non-unique label_field emits warning")

# 10. canonical label_field sequence_id always ok
lc2 <- validate_label_field_uniqueness(db_junc, "sequence_id", "sequence_id")
assert_true(!isTRUE(lc2$use_display), "sequence_id label_field skips display newick")

# 11. duplicate sequence_id rejected
db_dup <- db_junc
db_dup$sequence_id <- c("s1", "s1", "s3")
uid <- validate_sequence_id_uniqueness(db_dup, "sequence_id")
assert_true(!isTRUE(uid$ok), "duplicate sequence_id rejected")

# 12. formatClones args include traits for DTA mode
p_dta <- list(
  analysis_mode = "discrete_trait_analysis",
  trait_field = "c_call",
  annotation_fields = character(0),
  collapse_identical_sequences = TRUE,
  mod3 = FALSE,
  filterstop = FALSE,
  use_regions = FALSE
)
db_trait2 <- db_junc
db_trait2$c_call <- c("IGHM", "IGHG1", "IGHG1")
args <- build_format_clones_args(db_trait2, p_dta)
assert_true("traits" %in% names(args), "traits passed to formatClones for DTA")
assert_equal(args$traits, "c_call", "trait_field used as traits")
assert_equal(args$filterstop, FALSE, "default filterstop = FALSE")
assert_equal(args$mod3, FALSE, "default mod3 = FALSE")

# 13. num_fields retains abundance columns
db_num <- db_junc
db_num$duplicate_count <- c(1L, 2L, 3L)
db_num$umi_count <- c(10L, 20L, 30L)
args_num <- build_format_clones_args(db_num, list(analysis_mode = "tree_only", mod3 = FALSE, filterstop = FALSE, use_regions = FALSE))
assert_true("duplicate_count" %in% args_num$num_fields, "duplicate_count in num_fields")
assert_true("umi_count" %in% args_num$num_fields, "umi_count in num_fields")

# 14. IgPhyML preflight without exec path (mock missing)
old_bin <- Sys.getenv("IGPHYML_BIN", "")
Sys.setenv(IGPHYML_BIN = "/nonexistent/igphyml/path")
ig_res <- tryCatch(
  resolve_igphyml(user_exec = "/nonexistent/igphyml/path", require_ok = TRUE),
  error = function(e) e
)
assert_true(inherits(ig_res, "dowser_validation"), "missing IgPhyML raises dowser_validation")
assert_equal(ig_res$step, "dowser.preflight.igphyml", "missing IgPhyML step correct")
if (nzchar(old_bin)) Sys.setenv(IGPHYML_BIN = old_bin) else Sys.unsetenv("IGPHYML_BIN")

# 14b. check_igphyml_exec returns structured failure without stopping
exec_check <- check_igphyml_exec("/nonexistent/igphyml/path")
assert_true(!isTRUE(exec_check$ok), "check_igphyml_exec returns ok=FALSE for missing path")
assert_equal(exec_check$step, "dowser.preflight.igphyml", "check_igphyml_exec step correct")

# 15. IgPhyML sequence validation reports problematic records
db_ig <- db_junc
db_ig$stop_codon <- c(FALSE, TRUE, FALSE)
igv <- validate_igphyml_sequences(db_ig)
assert_true(!isTRUE(igv$ok), "stop_codon=true triggers IgPhyML validation error")
assert_true(length(igv$details$records) >= 1, "problematic records listed")
assert_true(!is.null(igv$details$summary), "summary included")
assert_true(isTRUE(igv$details$used_authoritative_airr_fields), "authoritative AIRR fields flagged for stop_codon")

db_ig2 <- db_junc
db_ig2$vj_in_frame <- c(TRUE, FALSE, TRUE)
igv2 <- validate_igphyml_sequences(db_ig2)
assert_true(!isTRUE(igv2$ok), "vj_in_frame=false triggers validation error")
assert_true(any(grepl("vj_in_frame=false", vapply(igv2$details$records, function(r) r$reason, character(1)))), "vj_in_frame reason present")
assert_true(isTRUE(igv2$details$used_authoritative_airr_fields), "authoritative AIRR fields flagged for vj_in_frame")

db_ig3 <- db_junc
db_ig3$productive <- c(TRUE, FALSE, TRUE)
igv3 <- validate_igphyml_sequences(db_ig3)
assert_true(!isTRUE(igv3$ok), "productive=false triggers validation error")
assert_true(isTRUE(igv3$details$used_authoritative_airr_fields), "authoritative AIRR fields flagged for productive")

db_ig4 <- db_junc
db_ig4$complete_vdj <- c(TRUE, FALSE, TRUE)
igv4 <- validate_igphyml_sequences(db_ig4)
assert_true(isTRUE(igv4$ok), "complete_vdj=false is warning-only")
assert_true(length(igv4$warnings %||% character(0)) >= 1, "complete_vdj=false produces warning")
assert_true(any(grepl("complete_vdj", igv4$warnings, ignore.case = TRUE)), "complete_vdj mentioned in warning")

db_ig5 <- db_junc
n_before <- nrow(db_ig5)
igv5 <- validate_igphyml_sequences(db_ig5)
assert_true(isTRUE(igv5$ok), "ungapped length not mod 3 returns ok without AIRR fields")
assert_equal(nrow(db_ig5), n_before, "validation does not drop rows (frame heuristic)")
assert_true(length(igv5$warnings %||% character(0)) >= 1, "frame heuristic warning emitted")
assert_true(isFALSE(igv5$details$used_authoritative_airr_fields), "heuristic path marks non-authoritative")
assert_true(length(igv5$details$heuristic_warning_records %||% list()) >= 1, "heuristic records included")

db_ig6 <- db_junc
db_ig6$sequence_alignment <- c("AAATAATAA", "ACGTACGA", "ACGTACGC")
db_ig6$germline_alignment_d_mask <- c("AAATAATAA", "ACGTACGT", "ACGTACGT")
igv6 <- validate_igphyml_sequences(db_ig6)
assert_true(isTRUE(igv6$ok), "heuristic stop codon returns ok without AIRR fields")
assert_true(any(grepl("stop-codon", igv6$warnings, ignore.case = TRUE)), "stop heuristic warning emitted")

db_ig7 <- db_junc
db_ig7$sequence_alignment <- c("ACGTACGT", NA, "ACGTACGC")
igv7 <- validate_igphyml_sequences(db_ig7)
assert_true(!isTRUE(igv7$ok), "missing sequence_alignment fails in IgPhyML validator")
assert_equal(igv7$step, "dowser.preflight.igphyml.sequence_validity", "structural failure step")

db_ig8 <- db_junc
db_ig8$germline_alignment_d_mask <- c("ACGTACGT", "", "ACGTACGT")
igv8 <- validate_igphyml_sequences(db_ig8)
assert_true(!isTRUE(igv8$ok), "empty germline_alignment_d_mask fails in IgPhyML validator")

db_ig9 <- db_junc
db_ig9$sequence_alignment <- c("ACGTACGTA", "ACGTACGTA", "ACGTACGTA")
db_ig9$germline_alignment_d_mask <- c("ACGTACGTA", "ACGTACGTA", "ACGTACGTA")
igv9 <- validate_igphyml_sequences(db_ig9)
assert_true(isTRUE(igv9$ok), "clean alignments without AIRR fields return ok")
assert_true(isFALSE(igv9$details$used_authoritative_airr_fields %||% TRUE), "no AIRR fields uses heuristic metadata flag")

db_ig10 <- db_junc
db_ig10$stop_codon <- c(FALSE, TRUE, FALSE)
igv10 <- validate_igphyml_sequences(db_ig10)
assert_true(!isTRUE(igv10$ok), "IgPhyML validation failure does not imply ok")
assert_true(!identical(igv10$ok, "igphyml"), "no tree_build fallback encoded in validation result")

db_ig11 <- db_junc
db_ig11$sequence_alignment <- c("AAATAATAA", "ACGT", "ACGTACGC")
db_ig11$germline_alignment_d_mask <- c("AAATAATAA", "ACGT", "ACGTACGT")
heur_both <- build_igphyml_heuristic_warnings(db_ig11, "sequence_alignment", "sequence_id", "clone_id")
assert_true(length(heur_both$warnings) >= 2, "frame and stop heuristics can both emit warnings")

formatted_ok <- data.frame(
  clone_id = "c1",
  data = I(list(db_ig[-2, , drop = FALSE])),
  stringsAsFactors = FALSE
)
igv_formatted_ok <- validate_igphyml_sequences_after_format_clones(formatted_ok)
assert_true(isTRUE(igv_formatted_ok$ok), "IgPhyML validation uses post-formatClones retained records")

formatted_bad <- data.frame(
  clone_id = "c1",
  data = I(list(db_ig)),
  stringsAsFactors = FALSE
)
igv_formatted_bad <- validate_igphyml_sequences_after_format_clones(formatted_bad)
assert_true(!isTRUE(igv_formatted_bad$ok), "IgPhyML validation still fails retained bad records")

# 16. dnapars/dnaml exec passed to getTrees args
p_dn <- list(tree_build = "dnapars", analysis_mode = "tree_only", nproc = 1L, collapse_internal_nodes = TRUE, check_divergence = TRUE)
pref <- list(phylip = list(exec = "/usr/local/bin/dnapars", tool = "dnapars"))
args_dn <- build_get_trees_args(list(), p_dn, pref, "/tmp", "run1")
assert_equal(args_dn$exec, "/usr/local/bin/dnapars", "dnapars build args include exec")
p_dn$tree_build <- "dnaml"
pref$phylip$exec <- "/usr/local/bin/dnaml"
args_ml <- build_get_trees_args(list(), p_dn, pref, "/tmp", "run1")
assert_equal(args_ml$exec, "/usr/local/bin/dnaml", "dnaml build args include exec")

test_missing_phylip <- function(tool) {
  env_key <- if (tool == "dnapars") "DNAPARS_PATH" else "DNAML_PATH"
  old_env <- Sys.getenv(env_key, unset = NA)
  old_path <- Sys.getenv("PATH", unset = NA)
  on.exit({
    if (is.na(old_env)) Sys.unsetenv(env_key) else do.call(Sys.setenv, setNames(list(old_env), env_key))
    if (is.na(old_path)) Sys.unsetenv("PATH") else Sys.setenv(PATH = old_path)
  }, add = TRUE)
  do.call(Sys.setenv, setNames(list("/nonexistent/path"), env_key))
  Sys.setenv(PATH = "/nonexistent")
  resolve_phylip(tool)
}

# 17. missing dnapars/dnaml preflight step
dn_res <- test_missing_phylip("dnapars")
assert_true(!isTRUE(dn_res$ok), "missing dnapars returns failure")
assert_equal(dn_res$step, "dowser.preflight.dnapars", "missing dnapars step")

ml_res <- test_missing_phylip("dnaml")
assert_true(!isTRUE(ml_res$ok), "missing dnaml returns failure")
assert_equal(ml_res$step, "dowser.preflight.dnaml", "missing dnaml step")

# 18. prepare_tip_color_column does not mutate original column
db_color <- db_junc
db_color$tissue <- c("A", NA, "B")
orig <- db_color$tissue
tc <- prepare_tip_color_column(db_color, "tissue", "unknown")
assert_equal(db_color$tissue, orig, "original trait column unchanged")
assert_true(".plot_tissue" %in% names(tc$db), "plot-only column created")
assert_equal(tc$plot_tip_col, ".plot_tissue", "plot_tip_col returned")

# 19. build_display_label_map sanitizes unsafe labels
db_disp <- db_junc
db_disp$label <- c("IGHG1 sample A", "tip;two", "ok_label")
dm <- build_display_label_map(db_disp, "sequence_id", "label")
assert_true(isTRUE(dm$use_display), "unique display labels usable")
assert_equal(dm$newick_safe[["s1"]], "IGHG1_sample_A", "unsafe labels sanitized for newick")
assert_equal(dm$tip_label_map[[1]]$display_label_raw, "IGHG1 sample A", "raw display label preserved")

db_dup_label <- db_disp
db_dup_label$label <- c("dup", "dup", "ok_label")
dm_dup <- build_display_label_map(db_dup_label, "sequence_id", "label")
assert_true(!isTRUE(dm_dup$use_display), "non-unique label_field disables display")

# 20. partition_model validation
assert_true(isTRUE(validate_partition_model(list(tree_build = "igphyml", partition_model = "cf", chain_mode = "H"))$ok), "cf+igphyml accepted")
assert_true(!isTRUE(validate_partition_model(list(tree_build = "pratchet", partition_model = "cf", chain_mode = "H"))$ok), "cf+pratchet rejected")
assert_true(!isTRUE(validate_partition_model(list(tree_build = "igphyml", partition_model = "hl", chain_mode = "H"))$ok), "hl+H rejected")
assert_true(isTRUE(validate_partition_model(list(tree_build = "igphyml", partition_model = "hl", chain_mode = "HL"))$ok), "hl+HL accepted")
assert_true(!isTRUE(validate_partition_model(list(tree_build = "igphyml", partition_model = "hlf", chain_mode = "H"))$ok), "hlf+H rejected")
assert_true(isTRUE(validate_partition_model(list(tree_build = "igphyml", partition_model = "hlf", chain_mode = "HL"))$ok), "hlf+HL accepted")
assert_true(isTRUE(validate_partition_model(list(tree_build = "igphyml", partition_model = "hlc", chain_mode = "HL"))$ok), "hlc+HL accepted")

# 21. multi-stage input_qc
qc <- init_input_qc(db_trait, "clone_id", "sequence_id")
qc$n_rows_after_derived_fields <- nrow(db_trait)
ex_rows <- tv$excluded_rows
qc$excluded_missing_trait <- build_excluded_missing_trait(db_trait, ex_rows, "c_call", "clone_id", "sequence_id")
assert_equal(qc$n_rows_original, 3L, "original row count")
assert_equal(length(qc$excluded_missing_trait), 1L, "excluded missing trait recorded")
assert_equal(qc$excluded_missing_trait[[1]]$reason, "missing_trait", "exclusion reason recorded")

# 22. add_artifact_if_exists
tmpdir <- tempfile("artifact_test_")
dir.create(tmpdir)
writeLines("{}", file.path(tmpdir, "exists.json"))
arts <- list()
arts <- add_artifact_if_exists(arts, tmpdir, "exists.json", "exists.json", "json")
arts <- add_artifact_if_exists(arts, tmpdir, "missing.json", "missing.json", "json")
assert_equal(length(arts), 1L, "missing optional artifact is not listed")
assert_equal(arts[[1]]$name, "exists.json", "existing artifact listed")
unlink(tmpdir, recursive = TRUE)

# 23. use_regions validation error when columns missing
ur_failed <- FALSE
tryCatch(
  {
    p_ur <- list(use_regions = TRUE, chain_mode = "H")
    args_ur <- build_format_clones_args(db_junc, p_ur)
    run_format_clones(db_junc, p_ur)
  },
  error = function(e) {
    if (inherits(e, "dowser_validation") && identical(e$step, "dowser.params.use_regions")) {
      ur_failed <<- TRUE
    }
  }
)
assert_true(ur_failed, "use_regions without region columns returns validation error")

# 24. build_get_trees_args includes igphyml for DTA with pml tree_build
p_dta_pml <- list(
  tree_build = "pml",
  analysis_mode = "discrete_trait_analysis",
  trait_field = "c_call",
  nproc = 1L,
  collapse_internal_nodes = TRUE,
  check_divergence = TRUE
)
pref_dta <- list(igphyml = list(exec = "/usr/local/bin/igphyml", motifs = "/motifs"))
args_dta <- build_get_trees_args(list(), p_dta_pml, pref_dta, "/tmp", "run1")
assert_equal(args_dta$igphyml, "/usr/local/bin/igphyml", "igphyml passed to getTrees for DTA+pml")
assert_true(!("exec" %in% names(args_dta)) || args_dta$exec != "/usr/local/bin/igphyml" || identical(args_dta$build, "igphyml"),
            "exec reserved for igphyml build, igphyml arg used for trait reconstruction")

# 25. no igphyml in getTrees args when preflight lacks igphyml
args_no_ig <- build_get_trees_args(list(), p_dta_pml, list(), "/tmp", "run1")
assert_true(is.null(args_no_ig$igphyml), "no igphyml arg without preflight igphyml")

# 26. junction_length row-level validation
db_junc_bad <- db_junc
db_junc_bad$junction_length <- c(3L, NA, 5L)
junc_na_failed <- FALSE
tryCatch(validate_junction_length(db_junc_bad), error = function(e) {
  if (inherits(e, "dowser_validation") && identical(e$step, "dowser.validate.junction_length")) {
    junc_na_failed <<- TRUE
  }
})
assert_true(junc_na_failed, "junction_length NA fails with row-level details")

db_junc_abc <- db_junc
db_junc_abc$junction_length <- c(3L, "abc", 5L)
junc_abc_failed <- FALSE
tryCatch(validate_junction_length(db_junc_abc), error = function(e) {
  if (inherits(e, "dowser_validation") && identical(e$step, "dowser.validate.junction_length")) {
    junc_abc_failed <<- TRUE
  }
})
assert_true(junc_abc_failed, "junction_length abc fails")

db_junc_zero <- db_junc
db_junc_zero$junction_length <- c(3L, 0L, 5L)
junc_zero_failed <- FALSE
tryCatch(validate_junction_length(db_junc_zero), error = function(e) {
  if (inherits(e, "dowser_validation") && identical(e$step, "dowser.validate.junction_length")) {
    junc_zero_failed <<- TRUE
  }
})
assert_true(junc_zero_failed, "junction_length 0 fails")

db_junc_valid <- db_junc
db_junc_valid$junction_length <- c("3", "4", "5")
db_valid <- validate_junction_length(db_junc_valid)
assert_equal(db_valid$junction_length, c(3L, 4L, 5L), "valid numeric strings pass junction_length validation")

# 27. validate_alignment_presence
db_align <- db_junc
db_align$sequence_alignment <- c("ACGTACGT", NA, "ACGTACGC")
align_failed <- FALSE
tryCatch(validate_alignment_presence(db_align), error = function(e) {
  if (inherits(e, "dowser_validation") && identical(e$step, "dowser.validate.alignment_missing")) {
    align_failed <<- TRUE
  }
})
assert_true(align_failed, "missing sequence_alignment fails")

db_align2 <- db_junc
db_align2$germline_alignment_d_mask <- c("ACGTACGT", "", "ACGTACGT")
align_empty_failed <- FALSE
tryCatch(validate_alignment_presence(db_align2), error = function(e) {
  if (inherits(e, "dowser_validation") && identical(e$step, "dowser.validate.alignment_missing")) {
    align_empty_failed <<- TRUE
  }
})
assert_true(align_empty_failed, "empty germline_alignment_d_mask fails")

# 28. validate_sequence_ids_for_mapping
db_safe <- db_junc
seqid_ok <- TRUE
tryCatch(validate_sequence_ids_for_mapping(db_safe), error = function(e) { seqid_ok <<- FALSE })
assert_true(seqid_ok, "valid safe IDs pass sequence_id mapping validation")

db_ws <- db_junc
db_ws$sequence_id <- c("s 1", "s2", "s3")
seqid_ws_failed <- FALSE
tryCatch(validate_sequence_ids_for_mapping(db_ws), error = function(e) {
  if (inherits(e, "dowser_validation") && identical(e$step, "dowser.validate.sequence_id_mapping")) {
    seqid_ws_failed <<- TRUE
  }
})
assert_true(seqid_ws_failed, "whitespace in sequence_id fails")

db_colon <- db_junc
db_colon$sequence_id <- c("s:1", "s2", "s3")
seqid_colon_failed <- FALSE
tryCatch(validate_sequence_ids_for_mapping(db_colon), error = function(e) {
  if (inherits(e, "dowser_validation") && identical(e$step, "dowser.validate.sequence_id_mapping")) {
    seqid_colon_failed <<- TRUE
  }
})
assert_true(seqid_colon_failed, "colon in sequence_id fails")

db_dup_seq <- db_junc
db_dup_seq$sequence_id <- c("s1", "s1", "s3")
seqid_dup_failed <- FALSE
tryCatch(validate_sequence_ids_for_mapping(db_dup_seq), error = function(e) {
  if (inherits(e, "dowser_validation") && identical(e$step, "dowser.validate.sequence_id_mapping")) {
    seqid_dup_failed <<- TRUE
  }
})
assert_true(seqid_dup_failed, "duplicate sequence_id fails mapping validation")

# 29. extract_igphyml_metadata partition fields
trees_no_part <- data.frame(clone_id = "c1", trees = I(list(structure(list(), class = "phylo"))), stringsAsFactors = FALSE)
meta_cf <- extract_igphyml_metadata(trees_no_part, pref_dta, list(tree_build = "igphyml", partition_model = "cf"))
assert_true(isTRUE(meta_cf$partition_model_supported), "igphyml+cf => supported true")
assert_equal(meta_cf$partition_model_effective, "cf", "effective partition cf")
assert_true(!isTRUE(meta_cf$partition_model_output_detected), "no partition column => output_detected false")
assert_true(!is.null(meta_cf$partition_model_requested), "requested field present")

# 30. FASTA input returns dowser_validation with file_extension step
fasta_val_failed <- FALSE
tryCatch(read_airr_from_path("input.fasta"), error = function(e) {
  if (inherits(e, "dowser_validation") && identical(e$step, "dowser.validate.file_extension")) {
    fasta_val_failed <<- TRUE
  }
})
assert_true(fasta_val_failed, "FASTA input raises dowser.validate.file_extension")

# 31. missing required columns returns dowser.validate.required_columns
db_no_v <- db_junc[, setdiff(names(db_junc), "v_call"), drop = FALSE]
req_col_failed <- FALSE
tryCatch(prepare_db_working(db_no_v, list()), error = function(e) {
  if (inherits(e, "dowser_validation") && identical(e$step, "dowser.validate.required_columns")) {
    req_col_failed <<- TRUE
  }
})
assert_true(req_col_failed, "missing required columns raises dowser.validate.required_columns")

# 32. DTA missing IgPhyML returns structured failure step
old_bin <- Sys.getenv("IGPHYML_BIN", "")
Sys.setenv(IGPHYML_BIN = "/nonexistent/igphyml/path")
ig_dta_err <- tryCatch(
  resolve_igphyml(user_exec = "/nonexistent/igphyml/path", require_ok = TRUE),
  error = function(e) e
)
assert_true(inherits(ig_dta_err, "dowser_validation"), "missing IgPhyML for DTA raises dowser_validation")
assert_equal(ig_dta_err$step, "dowser.preflight.igphyml", "missing IgPhyML for DTA step correct")
if (nzchar(old_bin)) Sys.setenv(IGPHYML_BIN = old_bin) else Sys.unsetenv("IGPHYML_BIN")

# 33. igphyml build does not duplicate igphyml arg when exec is set
p_ig <- list(
  tree_build = "igphyml",
  analysis_mode = "discrete_trait_analysis",
  trait_field = "c_call",
  partition_model = "single",
  nproc = 1L,
  collapse_internal_nodes = TRUE,
  check_divergence = TRUE
)
pref_ig_build <- list(igphyml = list(exec = "/usr/local/bin/igphyml", motifs = "/motifs"))
args_ig_build <- build_get_trees_args(list(), p_ig, pref_ig_build, "/tmp", "run1")
assert_equal(args_ig_build$exec, "/usr/local/bin/igphyml", "igphyml build uses exec arg")
assert_true(is.null(args_ig_build$igphyml), "igphyml build does not duplicate igphyml arg")

# 34. parentheses in sequence_id fail mapping validation
db_paren <- db_junc
db_paren$sequence_id <- c("s(1)", "s2", "s3")
seqid_paren_failed <- FALSE
tryCatch(validate_sequence_ids_for_mapping(db_paren), error = function(e) {
  if (inherits(e, "dowser_validation") && identical(e$step, "dowser.validate.sequence_id_mapping")) {
    seqid_paren_failed <<- TRUE
  }
})
assert_true(seqid_paren_failed, "parentheses in sequence_id fail")

# 35. plot-only column propagated into formatClones args
db_plot <- db_junc
db_plot$tissue <- c("A", NA, "B")
tc_plot <- prepare_tip_color_column(db_plot, "tissue", "unknown")
p_plot <- list(
  analysis_mode = "tree_only",
  trait_field = NULL,
  tip_color_by = "tissue",
  annotation_fields = character(0),
  columns = character(0),
  collapse_identical_sequences = TRUE,
  mod3 = FALSE,
  filterstop = FALSE,
  use_regions = FALSE
)
if (!is.null(tc_plot$plot_tip_col) && nzchar(tc_plot$plot_tip_col)) {
  p_plot$annotation_fields <- unique(c(parse_vec(p_plot$annotation_fields), tc_plot$plot_tip_col))
  p_plot$columns <- unique(c(parse_vec(p_plot$columns), tc_plot$plot_tip_col))
}
args_plot <- build_format_clones_args(tc_plot$db, p_plot)
assert_true(".plot_tissue" %in% args_plot$text_fields, "plot-only column in text_fields")
assert_true(".plot_tissue" %in% args_plot$columns, "plot-only column in columns")
assert_true("tissue" %in% args_plot$text_fields, "original tip_col retained in text_fields")

# 35b. numeric color-by column is not passed as text_fields when preserved as numeric
db_numeric_plot <- db_junc
db_numeric_plot$timepoint <- c(1, 2, 3)
tc_numeric_plot <- prepare_tip_color_column(db_numeric_plot, "timepoint", "unknown")
p_numeric_plot <- list(
  analysis_mode = "time_evolution",
  trait_field = NULL,
  tip_color_by = "timepoint",
  annotation_fields = tc_numeric_plot$plot_tip_col,
  numeric_annotation_fields = "timepoint",
  columns = tc_numeric_plot$plot_tip_col,
  collapse_identical_sequences = TRUE,
  mod3 = FALSE,
  filterstop = FALSE,
  use_regions = FALSE
)
args_numeric_plot <- build_format_clones_args(tc_numeric_plot$db, p_numeric_plot)
assert_true(".plot_timepoint" %in% args_numeric_plot$text_fields, "numeric color-by plot column retained as text_fields")
assert_true(!("timepoint" %in% args_numeric_plot$text_fields), "numeric color-by original excluded from text_fields")
assert_true("timepoint" %in% args_numeric_plot$num_fields, "numeric color-by original retained as num_fields")

# 36. .plot_* stripped from traits even if injected
db_dta_plot <- db_junc
db_dta_plot$c_call <- c("IGHM", "IGHG1", "IGHG1")
db_dta_plot$".plot_c_call" <- c("unknown", "IGHG1", "IGHG1")
p_dta_plot <- list(
  analysis_mode = "discrete_trait_analysis",
  trait_field = ".plot_c_call",
  trait_fields = c(".plot_c_call", "c_call"),
  tip_color_by = "c_call",
  annotation_fields = ".plot_c_call",
  collapse_identical_sequences = TRUE,
  mod3 = FALSE,
  filterstop = FALSE,
  use_regions = FALSE
)
args_dta_plot <- build_format_clones_args(db_dta_plot, p_dta_plot)
assert_true(is.null(args_dta_plot$traits) || !(".plot_c_call" %in% args_dta_plot$traits), ".plot_* excluded from traits")
assert_true("c_call" %in% args_dta_plot$text_fields || ".plot_c_call" %in% args_dta_plot$text_fields,
            "biological or plot-only columns retained as text_fields")

# 37. parse_dowser_params rejects trait_field = .plot_c_call
parse_plot_failed <- FALSE
tryCatch(
  parse_dowser_params(jsonlite::toJSON(list(trait_field = ".plot_c_call"))),
  error = function(e) {
    if (inherits(e, "dowser_validation") && identical(e$step, "dowser.validate.trait_field")) {
      parse_plot_failed <<- TRUE
    }
  }
)
assert_true(parse_plot_failed, "parse_dowser_params rejects .plot_* trait_field")

# 38. DTA with trait_field=c_call uses c_call not .plot_c_call
p_dta_ccall <- list(
  analysis_mode = "discrete_trait_analysis",
  trait_field = "c_call",
  tip_color_by = "c_call",
  annotation_fields = character(0),
  collapse_identical_sequences = TRUE,
  mod3 = FALSE,
  filterstop = FALSE,
  use_regions = FALSE
)
db_dta_ccall <- db_junc
db_dta_ccall$c_call <- c("IGHM", "IGHG1", "IGHG1")
db_dta_ccall$".plot_c_call" <- c("unknown", "IGHG1", "IGHG1")
args_dta_ccall <- build_format_clones_args(db_dta_ccall, p_dta_ccall)
assert_equal(args_dta_ccall$traits, "c_call", "DTA traits use original c_call")

# 39. custom trait model textarea content is validated and wired into tree/DTA args
model_text <- paste(c(
  "#BEGIN",
  "3",
  "",
  "#STATES",
  "A",
  "B",
  "C",
  "",
  "#CONSTRAINTS",
  "C A 1000",
  "C B 1000",
  "",
  "",
  "#AMBIGUOUS",
  "GERM A",
  "GERM B",
  "GERM C"
), collapse = "\n")
mv <- validate_trait_modelfile_text(model_text)
assert_true(isTRUE(mv$ok), "custom trait model text validates")
tmp_model_dir <- tempfile("dowser_model_test_")
dir.create(tmp_model_dir, showWarnings = FALSE)
model_info <- resolve_trait_modelfile(list(modelfile = model_text), tmp_model_dir)
assert_true(file.exists(model_info$path), "custom trait model text written to temp file")
p_model <- list(
  tree_build = "pratchet",
  analysis_mode = "discrete_trait_analysis",
  trait_field = "state",
  modelfile = model_info$path,
  nproc = 1L,
  collapse_internal_nodes = TRUE,
  check_divergence = TRUE,
  permutations = 10L,
  tip_switch = 5L
)
tree_args_model <- build_get_trees_args(list(), p_model, list(), tmp_model_dir, "run_model")
assert_equal(tree_args_model$modelfile, model_info$path, "custom trait model passed to getTrees")
switch_args_model <- build_find_switches_args(list(), p_model, model_info$path, list(), fixtrees = TRUE)
assert_equal(switch_args_model$modelfile, model_info$path, "custom trait model passed to findSwitches")
unlink(tmp_model_dir, recursive = TRUE)

# 39. resolve_correlation_test_fn prefers exported correlationTest
if (requireNamespace("dowser", quietly = TRUE)) {
  fn_corr <- resolve_correlation_test_fn()
  assert_true(is.function(fn_corr), "resolve_correlation_test_fn returns a function")
  exports <- getNamespaceExports("dowser")
  if ("correlationTest" %in% exports) {
    assert_equal(fn_corr, getFromNamespace("correlationTest", "dowser"), "exported correlationTest preferred")
  }
}

# 40. time_evolution auto-retains time_field in formatClones num_fields
db_time <- db_junc
db_time$timepoint <- c(1, 2, 3)
p_time <- list(
  analysis_mode = "time_evolution",
  time_field = "timepoint",
  collapse_identical_sequences = TRUE,
  mod3 = FALSE,
  filterstop = FALSE,
  use_regions = FALSE
)
args_time <- build_format_clones_args(db_time, p_time)
assert_true("timepoint" %in% args_time$num_fields, "time_field auto-retained for time_evolution")

# 41. extract_time_evolution_results drops non-JSON object columns
mock_time_res <- data.frame(
  clone_id = "c1",
  locus = "IGH",
  seqs = 3L,
  slope = 0.12,
  p = 0.04,
  correlation = 0.81,
  random_correlation = 0.1,
  min_p = 0.01,
  nposs = 10,
  nclust = 3L,
  stringsAsFactors = FALSE
)
mock_time_res$data <- I(list(structure(list(), class = "airrClone")))
mock_time_res$trees <- I(list(structure(list(), class = "phylo")))
time_records <- extract_time_evolution_results(mock_time_res)
assert_equal(length(time_records), 1L, "extract_time_evolution_results returns one row")
assert_true(is.null(time_records[[1]]$data), "airrClone column omitted from time results")
assert_true(is.null(time_records[[1]]$trees), "phylo column omitted from time results")
assert_equal(time_records[[1]]$correlation, 0.81, "time stat columns retained")

# 42. single-clone result keeps schema-required arrays when auto_unbox is disabled
minimal_result <- prepare_dowser_result(list(
  ok = TRUE,
  trees = c("((A,B):0.1);"),
  trees_detail = list(list(
    clone_id = "c1",
    canonical_newick = "((A,B):0.1);",
    display_newick = NULL,
    lineage_newick = "((A,B):0.1);",
    tip_label_map = list(list(sequence_id = "s1", display_label = "s1")),
    nodes = list(),
    all_sequences = list(),
    show_node_numbers = TRUE
  )),
  clones = list(clone_id = list("c1"), seqs = list(5L)),
  annotations = list(data.frame(label = "s1", sequence_id = "s1", stringsAsFactors = FALSE)),
  figures = list(phylogeny = list("cGFnZW5vbmU=")),
  stats = list(
    n_clones = 1L,
    n_trees = 1L,
    total_seqs = 5L,
    analysis_mode = "tree_with_internal_sequences",
    tree_build = "dnapars",
    canonical_ids = "sequence_id"
  ),
  input_qc = list(),
  data_provenance = list(),
  discrete_trait_analysis = NULL,
  time_evolution = NULL,
  igphyml = NULL,
  chain_qc = NULL,
  artifacts = list(),
  artifact_zip_b64 = list(clone_bundle_zip = NULL),
  artifact_name = "dowser_artifacts.zip",
  warnings = list(),
  logs = list(),
  render = NULL
))
minimal_json <- serialize_dowser_result(minimal_result)
parsed_minimal <- jsonlite::fromJSON(minimal_json, simplifyVector = FALSE)
assert_true(is.list(parsed_minimal$trees), "single tree serialized as JSON array")
assert_equal(length(parsed_minimal$trees), 1L, "single tree array length preserved")
assert_true(is.list(parsed_minimal$clones$clone_id), "single clone_id serialized as JSON array")
assert_true(is.list(parsed_minimal$clones$seqs), "single seqs serialized as JSON array")
assert_true(is.list(parsed_minimal$annotations), "single annotation entry serialized as JSON array")
assert_true(is.list(parsed_minimal$figures$phylogeny), "single figure serialized as JSON array")
contracts_dir <- Sys.getenv("CONTRACTS_DIR", file.path(root, "..", "..", "packages", "contracts"))
schema_path <- file.path(contracts_dir, "methods", "dowser", "result.schema.json")
if (file.exists(schema_path)) {
  assert_true(
    validate_dowser_result_contract(minimal_result, schema_path),
    "single-clone minimal result passes result.schema.json"
  )
}

cat("\n")
if (failures > 0) {
  cat("Validator tests failed:", failures, "\n")
  quit(status = 1)
}
cat("All Dowser validator tests passed.\n")
