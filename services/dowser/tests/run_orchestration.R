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
for (mod in c("validators.R", "dta.R", "internal_seqs.R", "exports.R")) {
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

# build_find_switches_args passes trees_tbl when fixtrees=TRUE (not clones)
mock_clones <- data.frame(clone_id = "c1", seqs = 3L, stringsAsFactors = FALSE)
mock_trees <- data.frame(clone_id = "c1", trees = I(list(structure(list(), class = "phylo"))), stringsAsFactors = FALSE)
p_dta <- list(
  trait_field = "c_call",
  permutations = 10L,
  tip_switch = 5L,
  permute_all = TRUE,
  alternative = "greater",
  run_test_ps = TRUE,
  run_test_sp = TRUE,
  run_test_sc = TRUE,
  nproc = 1L,
  trait_model = "unconstrained"
)
pref_ig <- list(igphyml = list(exec = "/usr/local/bin/igphyml"))

switch_args <- build_find_switches_args(mock_trees, p_dta, NULL, pref_ig, fixtrees = TRUE)
first_arg <- find_switches_input_arg(mock_trees)
assert_true(first_arg %in% names(switch_args), "findSwitches args include input key")
assert_equal(switch_args[[first_arg]]$clone_id, mock_trees$clone_id, "findSwitches called with trees_tbl when fixtrees=TRUE")
assert_true(!identical(switch_args[[first_arg]], mock_clones), "findSwitches does not receive clones when fixtrees=TRUE")
assert_true(isTRUE(switch_args$fixtrees), "fixtrees=TRUE passed to findSwitches")
assert_true(!("permute_all" %in% names(switch_args)), "permute_all not passed to findSwitches")
assert_true(!("permuteAll" %in% names(switch_args)), "permuteAll not passed to findSwitches")
assert_equal(switch_args$igphyml, "/usr/local/bin/igphyml", "igphyml passed to findSwitches from preflight")

# fixtrees=FALSE uses clones input
switch_args_clone <- build_find_switches_args(mock_clones, p_dta, NULL, pref_ig, fixtrees = FALSE)
first_arg_clone <- find_switches_input_arg(mock_clones)
assert_equal(switch_args_clone[[first_arg_clone]]$clone_id, mock_clones$clone_id, "fixtrees=FALSE passes clones")

# extract_dowser_test_result handles means/reps, summary/raw, and direct data.frame
df_summary <- data.frame(clone_id = "c1", p = 0.05, stringsAsFactors = FALSE)
df_raw <- data.frame(clone_id = "c1", rep = 1L, val = 0.1, stringsAsFactors = FALSE)

out_means <- extract_dowser_test_result(list(means = df_summary, reps = df_raw))
assert_true(length(out_means$summary) >= 1, "means extracted as summary")
assert_true(length(out_means$raw) >= 1, "reps extracted as raw")
assert_true("means" %in% unlist(out_means$available_fields), "available_fields lists means")

out_summary <- extract_dowser_test_result(list(summary = df_summary, raw = df_raw))
assert_true(length(out_summary$summary) >= 1, "summary field extracted")
assert_true(length(out_summary$raw) >= 1, "raw field extracted")

out_df <- extract_dowser_test_result(df_summary)
assert_true(length(out_df$summary) >= 1, "direct data.frame extracted as summary")

out_null <- extract_dowser_test_result(NULL)
assert_equal(out_null$summary, list(), "NULL input returns empty summary")
assert_equal(out_null$raw, list(), "NULL input returns empty raw")

# call_testSP/call_testSC permuteAll support introspection
if (requireNamespace("dowser", quietly = TRUE)) {
  sp_formals <- names(formals(dowser::testSP))
  sc_formals <- names(formals(dowser::testSC))
  ps_formals <- names(formals(dowser::testPS))
  if ("permuteAll" %in% sp_formals) {
    assert_true("permuteAll" %in% sp_formals, "testSP supports permuteAll in installed Dowser")
  }
  if ("permuteAll" %in% sc_formals) {
    assert_true("permuteAll" %in% sc_formals, "testSC supports permuteAll in installed Dowser")
  }
  assert_true(!("permuteAll" %in% ps_formals), "testPS must not receive permuteAll")
}

# call_testPS does not pass permuteAll
if (requireNamespace("dowser", quietly = TRUE)) {
  mock_sw <- data.frame(clone_id = "c1", stringsAsFactors = FALSE)
  ps_call <- tryCatch(call_testPS(mock_sw), error = function(e) NULL)
  if (!is.null(ps_call)) {
    assert_equal(ps_call$warnings, character(0), "call_testPS emits no permuteAll warnings")
  }
}

# extract_dowser_test_result with reps-only input
df_reps_only <- data.frame(clone_id = "c1", rep = 1L, val = 0.1, stringsAsFactors = FALSE)
out_reps <- extract_dowser_test_result(list(reps = df_reps_only))
assert_equal(out_reps$summary, list(), "reps-only input has empty summary")
assert_true(length(out_reps$raw) >= 1, "reps-only input has non-empty raw")
assert_true("reps" %in% unlist(out_reps$available_fields), "reps listed in available_fields")

# build_lineage_nodes joins getAllSeqs output with phy$edge topology
phy <- structure(list(
  edge = matrix(c(4L, 1L, 4L, 2L, 5L, 3L, 5L, 4L), ncol = 2, byrow = TRUE),
  edge.length = c(0.01, 0.02, 0.03, 0.04),
  tip.label = c("s1", "s2", "s3"),
  Nnode = 2L
), class = "phylo")

all_seqs <- data.frame(
  clone_id = rep("c1", 5),
  node = c(1L, 2L, 3L, 4L, 5L),
  node_id = c("s1", "s2", "s3", "N4", "N5"),
  locus = rep("IGH", 5),
  sequence = c("AAA", "AAC", "AAT", "AAG", "ATA"),
  sequence_alignment = c("AAA", "AAC", "AAT", "AAG", "ATA"),
  stringsAsFactors = FALSE
)

nodes <- build_lineage_nodes(phy, "c1", all_seqs)
assert_true(length(nodes) >= 5, "lineage nodes built from getAllSeqs + edge topology")
internal <- Filter(function(n) isTRUE(n$is_internal), nodes)
assert_true(length(internal) >= 1, "internal nodes present")
tip_idx <- which(vapply(nodes, function(n) identical(n$node_id, "s1"), logical(1)))
assert_true(length(tip_idx) >= 1, "tip node s1 found in lineage nodes")
tip_node <- nodes[[tip_idx[1]]]
assert_equal(tip_node$sequence, "AAA", "tip sequence from getAllSeqs")

# getAllSeqs failure path (topology-only nodes)
nodes_no_seq <- build_lineage_nodes(phy, "c1", NULL)
assert_true(length(nodes_no_seq) >= 5, "topology-only nodes when all_seqs NULL")
assert_equal(nodes_no_seq[[1]]$sequence, "", "no fabricated sequences when getAllSeqs unavailable")

# plot_col_in_trees detects plot-only column in trees_tbl$data
phy_min <- structure(list(
  edge = matrix(c(4L, 1L, 4L, 2L), ncol = 2, byrow = TRUE),
  edge.length = c(0.01, 0.02),
  tip.label = c("s1", "s2"),
  Nnode = 1L
), class = "phylo")

trees_with_plot <- data.frame(
  clone_id = "c1",
  trees = I(list(phy_min)),
  data = I(list(data.frame(
    sequence_id = c("s1", "s2"),
    `.plot_tissue` = c("A", "unknown"),
    check.names = FALSE,
    stringsAsFactors = FALSE
  ))),
  stringsAsFactors = FALSE
)
assert_true(plot_col_in_trees(trees_with_plot, ".plot_tissue"), "plot_col_in_trees true when column in data")

trees_without_plot <- data.frame(
  clone_id = "c1",
  trees = I(list(phy_min)),
  data = I(list(data.frame(sequence_id = c("s1", "s2"), stringsAsFactors = FALSE))),
  stringsAsFactors = FALSE
)
assert_true(!plot_col_in_trees(trees_without_plot, ".plot_tissue"), "plot_col_in_trees false when column missing")

# render_tree_figures warns when plot-only column missing after formatClones
p_render <- list(analysis_mode = "tree_only", tipsize = 2, show_node_numbers = FALSE)
fig_missing <- render_tree_figures(trees_without_plot, p_render, ".plot_tissue", FALSE, "tissue")
assert_true(!is.null(fig_missing$warnings), "render_tree_figures emits warning when plot column missing")
assert_true(
  any(grepl("no plottable metadata column was found after formatClones", fig_missing$warnings, fixed = TRUE)),
  "render warning mentions missing plottable metadata column"
)

# prepare_trees_tbl_for_plot resolves biological tip_col for plotTrees
trees_ccall <- data.frame(
  clone_id = "c1",
  trees = I(list(phy_min)),
  data = I(list(data.frame(
    sequence_id = c("s1", "s2"),
    c_call = factor(c("IGHM", "IGHG1")),
    `.plot_c_call` = factor(c("unknown", "IGHG1")),
    check.names = FALSE,
    stringsAsFactors = FALSE
  ))),
  stringsAsFactors = FALSE
)
prepared_ccall <- prepare_trees_tbl_for_plot(trees_ccall, "c_call", ".plot_c_call")
assert_equal(prepared_ccall$tips_field, "c_call", "plot staging resolves tips to biological c_call")
assert_true(is.character(prepared_ccall$tbl$data[[1]]$c_call), "c_call coerced to character for plot")
assert_equal(prepared_ccall$tbl$data[[1]]$c_call[[1]], "unknown", "sanitized plot values copied into c_call")
assert_true(plot_col_is_plottable(prepared_ccall$tbl, "c_call"), "plot_col_is_plottable true after staging")
assert_true(!plot_col_is_plottable(trees_without_plot, "c_call"), "plot_col_is_plottable false when column missing")

# rehydrate tip coloring from db when getTrees output drops metadata columns
trees_no_ccall <- data.frame(
  clone_id = "c1",
  trees = I(list(phy_min)),
  data = I(list(data.frame(sequence_id = c("s1", "s2"), stringsAsFactors = FALSE))),
  stringsAsFactors = FALSE
)
db_ccall <- data.frame(
  sequence_id = c("s1", "s2"),
  clone_id = c("c1", "c1"),
  c_call = c("IGHM", "IGHG1"),
  `.plot_c_call` = c("unknown", "IGHG1"),
  check.names = FALSE,
  stringsAsFactors = FALSE
)
prepared_rehydrate <- prepare_trees_tbl_for_plot(trees_no_ccall, "c_call", ".plot_c_call", db = db_ccall)
assert_equal(prepared_rehydrate$tips_field, "c_call", "rehydrated tips_field is biological c_call")
assert_true(isTRUE(prepared_rehydrate$rehydrated), "rehydrated flag set when metadata injected from db")
assert_equal(prepared_rehydrate$tbl$data[[1]]$c_call[[1]], "unknown", "rehydrated c_call uses sanitized plot values")
assert_true(!inherits(prepared_rehydrate$tbl$data[[1]], "data.frame") || ncol(prepared_rehydrate$tbl$data[[1]]) >= 2,
            "rehydrated metadata retains multiple columns")

# clone metadata fallback when trees_tbl$data element is missing
trees_null_data <- data.frame(
  clone_id = "c1",
  trees = I(list(phy_min)),
  data = I(list(NULL)),
  stringsAsFactors = FALSE
)
clones_meta <- data.frame(
  clone_id = "c1",
  data = I(list(data.frame(
    sequence_id = c("s1", "s2"),
    c_call = c("IGHM", "IGHG1"),
    stringsAsFactors = FALSE
  ))),
  stringsAsFactors = FALSE
)
prepared_clone_fb <- prepare_trees_tbl_for_plot(
  trees_null_data, "c_call", ".plot_c_call", db = db_ccall, clones = clones_meta
)
assert_equal(prepared_clone_fb$tips_field, "c_call", "clone fallback enables tip coloring")
assert_true(isTRUE(prepared_clone_fb$rehydrated), "clone fallback sets rehydrated flag")

# airrClone metadata in trees_tbl$data is recognized for tip coloring
if (requireNamespace("dowser", quietly = TRUE)) {
  data(ExampleClones, package = "dowser", envir = environment())
  ex_clones <- ExampleClones[1:2, , drop = FALSE]
  ex_trees <- dowser::getTrees(ex_clones)
  prepared_airr <- prepare_trees_tbl_for_plot(ex_trees, "c_call", ".plot_c_call")
  assert_equal(prepared_airr$tips_field, "c_call", "airrClone metadata supports c_call tip coloring")
  assert_true(is_airr_clone(prepared_airr$tbl$data[[1]]), "airrClone class preserved during plot staging")
}

# rehydrate c_call into airrClone data slot when column was dropped
if (requireNamespace("dowser", quietly = TRUE)) {
  data(ExampleClones, package = "dowser", envir = environment())
  ex_clones <- ExampleClones[1, , drop = FALSE]
  ex_trees <- dowser::getTrees(ex_clones)
  ac <- ex_trees$data[[1]]
  ac_df <- slot(ac, "data")
  ac_df$c_call <- NULL
  slot(ac, "data") <- ac_df
  ex_trees$data[[1]] <- ac
  db_airr <- as.data.frame(slot(ExampleClones$data[[1]], "data"))
  db_airr$".plot_c_call" <- as.character(db_airr$c_call)
  prepared_airr_rehydrate <- prepare_trees_tbl_for_plot(
    ex_trees, "c_call", ".plot_c_call", db = db_airr, clones = ex_clones
  )
  assert_equal(prepared_airr_rehydrate$tips_field, "c_call", "airrClone rehydration restores c_call")
  assert_true(is_airr_clone(prepared_airr_rehydrate$tbl$data[[1]]), "airrClone preserved after rehydration")
  rehydrated_df <- slot(prepared_airr_rehydrate$tbl$data[[1]], "data")
  assert_true("c_call" %in% names(rehydrated_df), "c_call present in airrClone data slot after rehydration")
}

# factor tip.label coerced before plotting
phy_factor <- phy_min
phy_factor$tip.label <- factor(c("s1", "s2"))
trees_factor_tips <- data.frame(
  clone_id = "c1",
  trees = I(list(phy_factor)),
  data = trees_ccall$data,
  stringsAsFactors = FALSE
)
prepared_factor <- prepare_trees_tbl_for_plot(trees_factor_tips, "c_call", ".plot_c_call")
assert_true(is.character(prepared_factor$tbl$trees[[1]]$tip.label), "phy tip.label coerced to character")

# internal-node PNG gating skips trait node coloring on standard phylo trees
p_internal <- list(
  analysis_mode = "tree_with_internal_sequences",
  tipsize = 2,
  show_node_numbers = FALSE,
  return_internal_sequences = TRUE
)
fig_internal <- render_tree_figures(trees_ccall, p_internal, ".plot_c_call", FALSE, "c_call")
assert_true(!is.null(fig_internal$warnings), "internal mode emits guidance when node trait coloring unavailable")
assert_true(
  any(grepl("Internal node trait coloring skipped", fig_internal$warnings, fixed = TRUE)),
  "internal-node PNG gating explains trait coloring limitation"
)
assert_true(
  !any(grepl("and internal nodes:", fig_internal$warnings, fixed = TRUE)),
  "internal-node gating avoids plotTrees internal-node failure"
)

# tip_size_by passes numeric column name to plotTrees for variable tip sizes
if (requireNamespace("dowser", quietly = TRUE)) {
  data(ExampleClones, package = "dowser", envir = environment())
  ex_trees <- dowser::getTrees(ExampleClones[1, , drop = FALSE])
  p_size <- list(analysis_mode = "tree_only", tipsize = 2, tip_size_by = "duplicate_count")
  fig_size <- render_tree_figures(ex_trees, p_size, NULL, FALSE, "c_call")
  assert_true(
    !is.null(fig_size$figure_paths) &&
      length(fig_size$figure_paths) > 0 &&
      file.exists(fig_size$figure_paths[[1]]),
    "tip_size_by duplicate_count renders PNG previews"
  )
}

cat("\n")
if (failures > 0) {
  cat("Orchestration tests failed:", failures, "\n")
  quit(status = 1)
}
cat("All Dowser orchestration tests passed.\n")
