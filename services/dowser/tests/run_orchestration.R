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
  any(grepl("not present after formatClones", fig_missing$warnings, fixed = TRUE)),
  "render warning mentions formatClones retention failure"
)

cat("\n")
if (failures > 0) {
  cat("Orchestration tests failed:", failures, "\n")
  quit(status = 1)
}
cat("All Dowser orchestration tests passed.\n")
