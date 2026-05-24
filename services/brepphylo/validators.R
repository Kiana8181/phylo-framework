# BrepPhylo microservice validation helpers.
# Sourced by plumber.R; no side effects on load.

`%||%` <- function(x, y) {
  if (!is.null(x) && !(is.character(x) && length(x) == 1 && is.na(x))) x else y
}

SPECIES_ENUM <- c(
  "Homo_sapiens", "Mus_musculus", "Bos_taurus", "Gallus_gallus",
  "Oryctolagus_cuniculus", "Sus_scrofa", "custom"
)

PLOT_TYPE_ENUM <- c("phylogram", "cladogram", "fan", "radial")
INPUT_SEQUENCE_MODE_ENUM <- c("raw_sequence", "aligned_imgt_gapped")
NUCLEOTIDE_ALPHABET_RE <- "^[ACGTRYSWKMBDHVN.\\-]*$"

IMGT_GENE_RE <- "IG[HKL]V[^\\s|]*\\*\\d+"

require_positive_int <- function(name, value) {
  if (is.null(value) || (length(value) == 1L && is.na(value))) {
    return(sprintf("%s must be a positive integer greater than or equal to 1.", name))
  }
  if (is.character(value)) {
    value <- trimws(value)
    if (!nzchar(value)) {
      return(sprintf("%s must be a positive integer greater than or equal to 1.", name))
    }
    if (!grepl("^[0-9]+$", value)) {
      return(sprintf("%s must be a positive integer greater than or equal to 1.", name))
    }
    value <- as.integer(value)
  }
  if (!is.numeric(value) || length(value) != 1L) {
    return(sprintf("%s must be a positive integer greater than or equal to 1.", name))
  }
  iv <- as.integer(value)
  if (is.na(iv) || iv < 1L) {
    return(sprintf("%s must be a positive integer greater than or equal to 1.", name))
  }
  NULL
}

validate_species <- function(value) {
  if (is.null(value) || !nzchar(trimws(as.character(value)[1]))) {
    return("species is required.")
  }
  v <- trimws(as.character(value)[1])
  if (!v %in% SPECIES_ENUM) {
    return(sprintf(
      "species must be one of: %s",
      paste(SPECIES_ENUM, collapse = ", ")
    ))
  }
  NULL
}

validate_plot_type <- function(value) {
  if (is.null(value) || !nzchar(trimws(as.character(value)[1]))) {
    return("plot_type is required.")
  }
  v <- trimws(as.character(value)[1])
  if (!v %in% PLOT_TYPE_ENUM) {
    return(sprintf(
      "plot_type must be one of: %s",
      paste(PLOT_TYPE_ENUM, collapse = ", ")
    ))
  }
  NULL
}

validate_input_sequence_mode <- function(value) {
  if (is.null(value) || !nzchar(trimws(as.character(value)[1]))) {
    return("input_sequence_mode is required.")
  }
  v <- trimws(as.character(value)[1])
  if (!v %in% INPUT_SEQUENCE_MODE_ENUM) {
    return(sprintf(
      "input_sequence_mode must be one of: %s",
      paste(INPUT_SEQUENCE_MODE_ENUM, collapse = ", ")
    ))
  }
  NULL
}

validate_mutually_exclusive <- function(which_clones, ignore_clones) {
  if (length(which_clones) && length(ignore_clones)) {
    return("which_clones and ignore_clones are mutually exclusive; provide only one filter.")
  }
  NULL
}

parse_fasta_records <- function(text) {
  text <- trimws(text)
  if (!nzchar(text)) return(list(ok = FALSE, error = "FASTA content is empty.", records = list()))
  if (!grepl("^>", text)) {
    return(list(ok = FALSE, error = "Custom germline FASTA must start with '>' (FASTA header).", records = list()))
  }

  lines <- strsplit(text, "\n", fixed = TRUE)[[1]]
  records <- list()
  current_header <- NULL
  current_seq <- character(0)

  flush <- function() {
    if (is.null(current_header)) return(invisible(NULL))
    seq_str <- paste(current_seq, collapse = "")
    records[[length(records) + 1L]] <<- list(
      header = current_header,
      sequence = seq_str
    )
    invisible(NULL)
  }

  for (line in lines) {
    line <- trimws(line)
    if (!nzchar(line)) next
    if (startsWith(line, ">")) {
      flush()
      current_header <- sub("^>", "", line)
      current_header <- trimws(current_header)
      current_seq <- character(0)
    } else {
      current_seq <- c(current_seq, line)
    }
  }
  flush()

  if (!length(records)) {
    return(list(ok = FALSE, error = "Custom germline FASTA must contain at least one record.", records = list()))
  }
  list(ok = TRUE, error = NULL, records = records)
}

imgt_like_header <- function(header) {
  if (grepl(IMGT_GENE_RE, header, ignore.case = TRUE)) return(TRUE)
  if (grepl("\\|", header) && grepl("IG", header, ignore.case = TRUE)) return(TRUE)
  FALSE
}

validate_germline_set_text <- function(text) {
  parsed <- parse_fasta_records(text)
  if (!isTRUE(parsed$ok)) {
    return(list(ok = FALSE, error = parsed$error, content = NULL, records = list()))
  }

  errors <- character(0)
  for (i in seq_along(parsed$records)) {
    rec <- parsed$records[[i]]
    idx <- i
    hdr <- rec$header
    seq <- rec$sequence

    if (!nzchar(hdr)) {
      errors <- c(errors, sprintf("Record %d: empty FASTA header.", idx))
      next
    }
    if (!nzchar(seq)) {
      errors <- c(errors, sprintf("Record %d (header '%s'): empty sequence.", idx, hdr))
      next
    }
    if (!imgt_like_header(hdr)) {
      errors <- c(errors, sprintf(
        "Record %d (header '%s'): header does not look IMGT-like (expected IGHV/IGKV/IGLV allele token or pipe-delimited IMGT style).",
        idx, hdr
      ))
    }
    if (!grepl(NUCLEOTIDE_ALPHABET_RE, seq, ignore.case = TRUE)) {
      bad <- unique(unlist(strsplit(gsub("[ACGTRYSWKMBDHVN.\\-]", "", toupper(seq)), "")))
      errors <- c(errors, sprintf(
        "Record %d (header '%s'): sequence contains invalid characters: %s",
        idx, hdr, paste(bad, collapse = ", ")
      ))
    }
  }

  if (length(errors)) {
    return(list(ok = FALSE, error = paste(errors, collapse = " "), content = NULL, records = parsed$records))
  }

  list(ok = TRUE, error = NULL, content = text, records = parsed$records)
}

write_germline_fasta_tmp <- function(text, out_dir) {
  validated <- validate_germline_set_text(text)
  if (!isTRUE(validated$ok)) {
    stop(validated$error)
  }
  path <- file.path(out_dir, "custom_germline_set.fasta")
  writeLines(strsplit(trimws(text), "\n", fixed = TRUE)[[1]], path, useBytes = TRUE)
  normalizePath(path, mustWork = FALSE)
}

validate_aligned_imgt_gapped <- function(df, seq_col) {
  if (!seq_col %in% names(df)) {
    return(list(ok = FALSE, error = sprintf("Sequence column '%s' not found.", seq_col)))
  }
  seqs <- as.character(df[[seq_col]])
  seqs[is.na(seqs)] <- ""
  has_dot <- grepl("\\.", seqs, fixed = FALSE)
  n_with_dot <- sum(has_dot, na.rm = TRUE)
  if (nrow(df) == 0L) {
    return(list(ok = FALSE, error = "No rows to validate for aligned IMGT-gapped mode."))
  }
  if (n_with_dot < ceiling(nrow(df) / 2)) {
    return(list(
      ok = FALSE,
      error = sprintf(
        "input_sequence_mode is 'aligned_imgt_gapped' but only %d/%d rows contain IMGT-style gap characters ('.'). Sequences do not appear to be IMGT-gapped/aligned.",
        n_with_dot, nrow(df)
      )
    ))
  }
  list(ok = TRUE, error = NULL)
}

validate_isotype_column <- function(df, isotype_col) {
  if (is.null(isotype_col) || !nzchar(trimws(isotype_col))) {
    return(list(ok = FALSE, error = "isotype_column is required when enable_csr_analysis is true."))
  }
  if (!isotype_col %in% names(df)) {
    return(list(ok = FALSE, error = sprintf("Isotype column '%s' not found in input table.", isotype_col)))
  }
  vals <- as.character(df[[isotype_col]])
  empty <- is.na(vals) | !nzchar(trimws(vals))
  if (all(empty)) {
    return(list(ok = FALSE, error = sprintf("Isotype column '%s' has no non-empty values.", isotype_col)))
  }
  list(ok = TRUE, error = NULL)
}

row_identifier <- function(df, row_idx, label_col, clone_col, seq_col) {
  seq_id <- NA_character_
  if (!is.null(label_col) && nzchar(label_col) && label_col %in% names(df)) {
    seq_id <- trimws(as.character(df[[label_col]][row_idx]))
  }
  if (is.na(seq_id) || !nzchar(seq_id)) {
    seq_id <- sprintf("row_%d", row_idx)
  }
  clone_id <- if (clone_col %in% names(df)) as.character(df[[clone_col]][row_idx]) else NA_character_
  list(sequence_id = seq_id, clone_id = clone_id)
}

validate_required_rows <- function(df, seq_col, clone_col, germ_col, label_col = NULL) {
  rejected <- list()
  drop_blank <- function(x) is.na(x) | !nzchar(trimws(as.character(x)))

  for (i in seq_len(nrow(df))) {
    id <- row_identifier(df, i, label_col, clone_col, seq_col)
    if (drop_blank(df[[seq_col]][i])) {
      rejected[[length(rejected) + 1L]] <- list(
        row_index = i,
        sequence_id = id$sequence_id,
        clone_id = id$clone_id,
        reason = sprintf("empty %s", seq_col)
      )
    } else if (drop_blank(df[[clone_col]][i])) {
      rejected[[length(rejected) + 1L]] <- list(
        row_index = i,
        sequence_id = id$sequence_id,
        clone_id = id$clone_id,
        reason = sprintf("empty %s", clone_col)
      )
    } else if (drop_blank(df[[germ_col]][i])) {
      rejected[[length(rejected) + 1L]] <- list(
        row_index = i,
        sequence_id = id$sequence_id,
        clone_id = id$clone_id,
        reason = sprintf("empty %s", germ_col)
      )
    }
  }

  if (length(rejected)) {
    msgs <- vapply(rejected, function(r) {
      sprintf(
        "row %d (sequence_id=%s, clone_id=%s): %s",
        r$row_index, r$sequence_id %||% "?", r$clone_id %||% "?", r$reason
      )
    }, FUN.VALUE = character(1))
    return(list(
      ok = FALSE,
      error = paste(
        "Input contains rows with missing required fields:",
        paste(msgs, collapse = "; ")
      ),
      rejected_rows = rejected
    ))
  }
  list(ok = TRUE, error = NULL, rejected_rows = list())
}

UNSAFE_CLONE_ID_RE <- "[/\\\\]|\\.\\.|[\x00-\x1f]|[\x7f]|[\"'`$;&|<>*?\\[\\]{}()]"

is_unsafe_clone_id <- function(x) {
  x <- as.character(x)[1]
  if (!nzchar(x)) return(TRUE)
  grepl(UNSAFE_CLONE_ID_RE, x, perl = TRUE) || grepl("\\s", x, perl = TRUE)
}

clone_id_unsafe_reason <- function(x) {
  x <- as.character(x)[1]
  if (!nzchar(x)) return("empty clone ID")
  if (grepl("\\s", x, perl = TRUE)) return("contains whitespace")
  if (grepl("[/\\\\]", x, perl = TRUE)) return("contains path separator")
  if (grepl("\\.\\.", x, perl = TRUE)) return("contains '..'")
  if (grepl("[\x00-\x1f]|[\x7f]", x, perl = TRUE)) return("contains control characters")
  if (grepl("[\"'`]", x, perl = TRUE)) return("contains quotes or backtick")
  if (grepl("[$;&|<>*?]", x, perl = TRUE)) return("contains shell-sensitive character")
  if (grepl("[\\[\\]{}()]", x, perl = TRUE)) return("contains brackets/braces/parentheses")
  "contains unsafe filesystem/regex characters"
}

validate_clone_ids_strict <- function(df, clone_col) {
  ids <- as.character(df[[clone_col]])
  offenders <- list()
  for (i in seq_along(ids)) {
    cid <- ids[i]
    if (!is_unsafe_clone_id(cid)) next
    key <- paste0("__", cid)
    if (is.null(offenders[[key]])) {
      offenders[[key]] <- list(
        clone_id = cid,
        row_indices = integer(0),
        reason = clone_id_unsafe_reason(cid)
      )
    }
    offenders[[key]]$row_indices <- c(offenders[[key]]$row_indices, i)
  }

  if (length(offenders)) {
    parts <- vapply(offenders, function(b) {
      sprintf(
        "clone_id='%s' (rows %s): %s",
        b$clone_id,
        paste(b$row_indices, collapse = ", "),
        b$reason
      )
    }, FUN.VALUE = character(1))
    return(list(
      ok = FALSE,
      error = paste(
        "Unsafe clone IDs rejected. Provide filesystem-safe clone IDs before running BrepPhylo.",
        paste(parts, collapse = "; ")
      )
    ))
  }

  list(ok = TRUE, error = NULL)
}

resolve_or_create_tip_id_column <- function(df, label_col) {
  if (!is.null(label_col) && nzchar(label_col) && label_col %in% names(df)) {
    return(list(df = df, tip_id_col = label_col, generated = FALSE))
  }
  for (cand in c("sequence_id", "Sequence.ID")) {
    if (cand %in% names(df)) {
      return(list(df = df, tip_id_col = cand, generated = FALSE))
    }
  }
  df$.brepphylo_tip_id <- paste0("seq_", seq_len(nrow(df)))
  list(df = df, tip_id_col = ".brepphylo_tip_id", generated = TRUE)
}

escape_regex <- function(x) {
  gsub("([][{}()+*^$|\\\\?.])", "\\\\\\1", as.character(x), perl = TRUE)
}

precheck_label_uniqueness <- function(df, clone_col, label_col) {
  if (is.null(label_col) || !nzchar(label_col)) {
    return(list(ok = TRUE, error = NULL))
  }
  if (!label_col %in% names(df)) {
    return(list(ok = FALSE, error = sprintf("Label column '%s' not found.", label_col)))
  }

  errors <- character(0)
  clones <- unique(as.character(df[[clone_col]]))
  for (cid in clones) {
    sub <- df[df[[clone_col]] == cid, , drop = FALSE]
    labels <- trimws(as.character(sub[[label_col]]))
    labels[is.na(labels) | !nzchar(labels)] <- paste0("_row_", seq_len(sum(is.na(labels) | !nzchar(labels))))
    dup <- labels[duplicated(labels)]
    if (length(dup)) {
      dup_unique <- unique(dup)
      row_ids <- vapply(seq_len(nrow(sub)), function(i) {
        id <- row_identifier(sub, i, label_col, clone_col, NULL)
        id$sequence_id
      }, character(1))
      errors <- c(errors, sprintf(
        "clone_id=%s: duplicate label values [%s] affecting rows/sequence IDs [%s]",
        cid,
        paste(dup_unique, collapse = ", "),
        paste(row_ids[labels %in% dup_unique], collapse = ", ")
      ))
    }
  }

  if (length(errors)) {
    return(list(
      ok = FALSE,
      error = paste(
        "Duplicate labels within clone(s); BrepPhylo requires unique labels per clone:",
        paste(errors, collapse = "; ")
      )
    ))
  }
  list(ok = TRUE, error = NULL)
}

parse_germline_allele <- function(val) {
  val <- trimws(as.character(val)[1])
  if (!nzchar(val) || is.na(val)) return(character(0))
  if (grepl(",", val, fixed = TRUE)) {
    parts <- trimws(strsplit(val, ",", fixed = TRUE)[[1]])
    return(parts[nzchar(parts)])
  }
  val
}

precheck_mixed_germline <- function(df, clone_col, germ_col) {
  clones <- unique(as.character(df[[clone_col]]))
  mixed <- list()
  for (cid in clones) {
    sub <- df[df[[clone_col]] == cid, , drop = FALSE]
    alleles <- unique(unlist(lapply(sub[[germ_col]], parse_germline_allele)))
    alleles <- alleles[nzchar(alleles) & !is.na(alleles)]
    if (length(alleles) > 1L) {
      mixed[[length(mixed) + 1L]] <- list(
        clone_id = cid,
        distinct_germlines = as.list(alleles)
      )
    }
  }
  mixed
}

check_latex_available <- function() {
  pdflatex <- Sys.which("pdflatex")
  latexmk <- Sys.which("latexmk")
  nzchar(pdflatex) || nzchar(latexmk)
}

# BrepPhylo 0.4.2 calls ape::di2multi(..., top = 0.01); current ape uses tol=.
# Apply only around BrepPhylo calls; restore on exit.
# TODO: remove when BrepPhylo upstream accepts tol= (Fraternalilab/BrepPhylo).
with_di2multi_top_alias <- function(expr) {
  ns <- asNamespace("ape")
  original <- get("di2multi", envir = ns)
  patched <- FALSE

  if (!("top" %in% names(formals(original)))) {
    patched_fn <- function(phy, ..., top = NULL) {
      if (!is.null(top)) {
        original(phy, tol = top, ...)
      } else {
        original(phy, ...)
      }
    }
    environment(patched_fn) <- environment()

    was_locked <- bindingIsLocked("di2multi", ns)
    if (was_locked) unlockBinding("di2multi", ns)
    assign("di2multi", patched_fn, envir = ns)
    if (was_locked) lockBinding("di2multi", ns)
    patched <- TRUE
    message("[brepphylo] Compatibility shim: ape::di2multi accepts legacy top= as tol= for this call.")
  }

  on.exit({
    if (patched) {
      was_locked <- bindingIsLocked("di2multi", ns)
      if (was_locked) unlockBinding("di2multi", ns)
      assign("di2multi", original, envir = ns)
      if (was_locked) lockBinding("di2multi", ns)
    }
  }, add = TRUE)

  force(expr)
}
