#!/usr/bin/env Rscript

# Lightweight validator unit tests (no testthat dependency required).

root_dir <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- sub("^--file=", "", args[grep("^--file=", args)])
  if (length(file_arg) && nzchar(file_arg[1])) {
    return(normalizePath(file.path(dirname(file_arg[1]), ".."), mustWork = FALSE))
  }
  normalizePath("services/brepphylo", mustWork = FALSE)
}

root <- root_dir()
source(file.path(root, "validators.R"))

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

# require_positive_int
assert_true(is.null(require_positive_int("min_clone_size", 10)), "10 ok")
assert_true(!is.null(require_positive_int("min_clone_size", NA)), "NA rejected")
assert_true(!is.null(require_positive_int("min_clone_size", "")), "empty rejected")
assert_true(!is.null(require_positive_int("min_clone_size", "abc")), "non-numeric rejected")
assert_true(!is.null(require_positive_int("min_clone_size", 0)), "zero rejected")

# species enum
assert_true(is.null(validate_species("Homo_sapiens")), "Homo_sapiens ok")
assert_true(!is.null(validate_species("Human")), "invalid species rejected")

# plot_type enum
assert_true(is.null(validate_plot_type("phylogram")), "phylogram ok")
assert_true(!is.null(validate_plot_type("invalid")), "invalid plot rejected")

# mutually exclusive filters
assert_true(
  !is.null(validate_mutually_exclusive(c("a"), c("b"))),
  "both filters rejected"
)
assert_true(
  is.null(validate_mutually_exclusive(c("a"), character(0))),
  "single filter ok"
)

# FASTA validation
good_fasta <- paste0(
  ">IGHV1-69*01\n",
  "CAGGTGCAGCTGGTGGAGTCTGGG\n",
  ">IGKV1-5*01\n",
  "GACATCCAGATGACCCAGTCTCC\n"
)
fasta_ok <- validate_germline_set_text(good_fasta)
assert_true(isTRUE(fasta_ok$ok), "valid FASTA accepted")

normalized_custom <- normalize_custom_germline_set_text(paste0(
  ">M99641|IGHV1-18*01|Homo_sapiens|F|V-REGION\n",
  "CAGGTTCAGCTGGTGCAGTCT\n"
))
assert_true(
  grepl(">custom|IGHV1-18*01|custom|custom-germline", normalized_custom, fixed = TRUE),
  "custom IMGT FASTA is rewritten with BrepPhylo-compatible species key"
)

normalized_simple <- normalize_custom_germline_set_text(good_fasta)
assert_true(
  grepl(">custom|IGHV1-69*01|custom|custom-germline", normalized_simple, fixed = TRUE),
  "simple allele FASTA is rewritten with BrepPhylo-compatible species key"
)

bad_fasta <- "not a fasta"
fasta_bad <- validate_germline_set_text(bad_fasta)
assert_true(!isTRUE(fasta_bad$ok), "invalid FASTA rejected")

# strict clone id validation
df_safe <- data.frame(
  clone_id = c("safe", "a_b", "clone-1"),
  sequence = c("ACGT", "ACGT", "ACGT"),
  stringsAsFactors = FALSE
)
safe_check <- validate_clone_ids_strict(df_safe, "clone_id")
assert_true(isTRUE(safe_check$ok), "safe clone IDs accepted")

df_unsafe <- data.frame(
  clone_id = c("clone/a", "bad id"),
  sequence = c("ACGT", "ACGT"),
  stringsAsFactors = FALSE
)
unsafe_check <- validate_clone_ids_strict(df_unsafe, "clone_id")
assert_true(!isTRUE(unsafe_check$ok), "unsafe clone IDs rejected")
assert_true(grepl("clone/a", unsafe_check$error, fixed = TRUE), "error lists offending clone ID")

# tip id resolution
df_label <- data.frame(label = c("s1", "s2"), sequence_id = c("x1", "x2"))
tip_label <- resolve_or_create_tip_id_column(df_label, "label")
assert_equal(tip_label$tip_id_col, "label", "uses label column when provided")
assert_true(!tip_label$generated, "label column not generated")

df_seq <- data.frame(sequence_id = c("x1", "x2"), clone_id = c("c1", "c1"))
tip_seq <- resolve_or_create_tip_id_column(df_seq, NULL)
assert_equal(tip_seq$tip_id_col, "sequence_id", "uses sequence_id when no label column")
assert_true(!tip_seq$generated, "sequence_id not generated")

df_none <- data.frame(sequence = c("ACGT", "ACGT"), clone_id = c("c1", "c1"))
tip_gen <- resolve_or_create_tip_id_column(df_none, NULL)
assert_equal(tip_gen$tip_id_col, ".brepphylo_tip_id", "generates internal tip id column")
assert_true(tip_gen$generated, "internal tip id marked generated")
assert_equal(tip_gen$df$.brepphylo_tip_id, c("seq_1", "seq_2"), "internal tip ids are globally unique")

# escape_regex
assert_equal(escape_regex("a.b"), "a\\.b", "dot escaped")
assert_equal(escape_regex("clone*1"), "clone\\*1", "star escaped")

# mixed germline
df2 <- data.frame(
  clone_id = c("c1", "c1", "c2"),
  germ = c("IGHV1*01", "IGHV2*01", "IGHV1*01"),
  stringsAsFactors = FALSE
)
mixed <- precheck_mixed_germline(df2, "clone_id", "germ")
assert_equal(length(mixed), 1L, "one mixed germline clone")

# duplicate labels
df3 <- data.frame(
  clone_id = c("c1", "c1"),
  label = c("A", "A"),
  stringsAsFactors = FALSE
)
dup <- precheck_label_uniqueness(df3, "clone_id", "label")
assert_true(!isTRUE(dup$ok), "duplicate labels rejected")

# IMGT gapped validation
df4 <- data.frame(sequence = c("ACGT.ACGT", "ACGT.ACGT"))
aligned_ok <- validate_aligned_imgt_gapped(df4, "sequence")
assert_true(isTRUE(aligned_ok$ok), "aligned gapped ok")

df5 <- data.frame(sequence = c("ACGT", "ACGT"))
aligned_bad <- validate_aligned_imgt_gapped(df5, "sequence")
assert_true(!isTRUE(aligned_bad$ok), "ungapped rejected for aligned mode")

# Alignment-length equality applies only in aligned_imgt_gapped mode, where the
# alignment is consumed as given. Under the default raw_sequence mode Clustal
# re-aligns, so ragged input never reaches this function.
df6 <- data.frame(sequence = c("ACGT.ACGT", "ACGT.ACGTA", "ACGT.ACGT"))
ragged <- validate_aligned_imgt_gapped(df6, "sequence")
assert_true(!isTRUE(ragged$ok), "unequal lengths rejected for aligned mode")
assert_true(
  grepl("not all the same length", ragged$error, fixed = TRUE),
  "unequal-length error names the cause"
)
assert_true(
  grepl("raw_sequence", ragged$error, fixed = TRUE),
  "unequal-length error points at the raw_sequence alternative"
)

cat("\n", failures, " failure(s)\n", sep = "")
if (failures > 0L) quit(status = 1)
