#* @apiTitle Dowser microservice
#* @apiDescription Build BCR lineage trees with Dowser (requires AIRR-like input).

library(plumber)
SER <- plumber::serializer_json(
  auto_unbox = TRUE,
  null = "null",
  na = "null",
  dataframe = "rows"
)

library(jsonlite)
library(dowser)
library(alakazam)
library(ape)
library(jsonvalidate)
library(Biostrings)

# Raise PCRE limits (helps multipart parser with long headers)
options(pcre.limit.match     = 1e8)
options(pcre.limit.recursion = 2e6)
Sys.setenv(PCRE2_MATCH_LIMIT="100000000")
Sys.setenv(PCRE2_MATCH_LIMIT_RECURSION="2000000")

# ---------------------------
# Config & Contracts loading
# ---------------------------
CONTRACTS_DIR <- Sys.getenv("CONTRACTS_DIR", "packages/contracts")
METHOD_DIR    <- file.path(CONTRACTS_DIR, "methods", "dowser")

PARAM_SCHEMA_PATH   <- file.path(METHOD_DIR, "param.schema.json")
RESULT_SCHEMA_PATH  <- file.path(METHOD_DIR, "result.schema.json")
SPEC_JSON_PATH      <- file.path(METHOD_DIR, "spec.json")
UI_JSON_PATH        <- file.path(METHOD_DIR, "ui.json")
ROUTES_JSON_PATH    <- file.path(METHOD_DIR, "service.routes.json")

read_json_or <- function(path, default = NULL) {
  if (file.exists(path)) {
    tryCatch(jsonlite::fromJSON(path, simplifyVector = FALSE),
             error = function(e) default)
  } else default
}

PARAM_SCHEMA  <- read_json_or(PARAM_SCHEMA_PATH, list(type="object", properties=list(), required=list()))
RESULT_SCHEMA <- RESULT_SCHEMA_PATH  # jsonvalidate accepts a path

SPEC_JSON     <- read_json_or(SPEC_JSON_PATH, list())
UI_JSON       <- read_json_or(UI_JSON_PATH, list())
ROUTES        <- read_json_or(ROUTES_JSON_PATH, list(spec="/spec", run="/run"))

merge_list <- function(a, b) { a[names(b)] <- b; a }

# NOTE: FASTA removed because read_airr_from_path does not implement FASTA ingestion.
DEFAULT_ACCEPTS <- c("text/csv","text/tab-separated-values","application/x-rds","application/x-rda")
DEFAULT_UI <- list(requiresFile = TRUE, maxFiles = 1, order = c("tree_model", "minseq", "nproc", "tip_color_by", "unknown_value", "tipsize", "include_figures"))

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0 || (is.character(a) && !nzchar(a))) b else a
logf <- function(...) cat(sprintf(...), "\n", file=stderr())

to_newick <- function(phy) {
  tf <- tempfile(fileext = ".nwk")
  on.exit(if (file.exists(tf)) unlink(tf), add = TRUE)
  ape::write.tree(phy, file = tf)
  paste(readLines(tf, warn = FALSE), collapse = "")
}

encode_png <- function(plot, width = 900, height = 520, dpi = 100) {
  tf <- tempfile(fileext = ".png")
  on.exit(if (file.exists(tf)) unlink(tf), add = TRUE)
  ggplot2::ggsave(tf, plot = plot, width = width / 100, height = height / 100, dpi = dpi, bg = "white")
  jsonlite::base64_enc(readBin(tf, "raw", n = file.info(tf)$size))
}

get_content_type <- function(req) {
  ct <- req$HTTP_CONTENT_TYPE %||% req$CONTENT_TYPE %||% ""
  tolower(ct)
}

read_airr_from_path <- function(path) {
  ext <- tolower(tools::file_ext(path))
  if (ext %in% c("tsv", "txt")) {
    suppressMessages(readr::read_tsv(path, show_col_types = FALSE))
  } else if (ext == "csv") {
    suppressMessages(readr::read_csv(path, show_col_types = FALSE))
  } else if (ext == "rds") {
    readRDS(path)
  } else if (ext %in% c("rda","rdata")) {
    e <- new.env(); load(path, envir = e); e[[ls(e)[1]]]
  } else {
    stop(sprintf("Unsupported file extension: %s", ext))
  }
}

# Dowser wants clone+germline fields typical of *clone-pass.tsv*
validate_airr_for_dowser <- function(db) {
  req <- c("sequence_id","clone_id","sequence_alignment","germline_alignment_d_mask","v_call","j_call","junction")
  missing <- setdiff(req, names(db))
  if (length(missing)) {
    stop(paste0(
      "Input missing required columns for Dowser: ",
      paste(missing, collapse=", "),
      ". Upload a Change-O clone table (e.g. *clone-pass.tsv*)."
    ))
  }
}

spec_handler_impl <- function() {
  pkg_ver <- as.character(utils::packageVersion("dowser"))
  name    <- SPEC_JSON$name %||% "Dowser"
  version <- SPEC_JSON$version %||% pkg_ver
  accepts <- SPEC_JSON$accepts; if (is.null(accepts) || !length(accepts)) accepts <- DEFAULT_ACCEPTS
  ui_hints <- merge_list(DEFAULT_UI, UI_JSON)
  list(id="dowser", name=name, version=version, accepts=accepts, paramSchema=PARAM_SCHEMA, uiHints=ui_hints)
}

# Validate / auto-detect IgPhyML executable
check_igphyml_exec <- function(user_exec = NULL) {
  # 1) If user provided a path, normalize and validate it
  if (!is.null(user_exec) && nzchar(user_exec)) {
    path <- normalizePath(user_exec, mustWork = FALSE)
    if (!file.exists(path)) {
      stop(sprintf("IgPhyML path does not exist: %s", user_exec))
    }
    if (file.access(path, 1) != 0) {
      stop(sprintf("IgPhyML path is not executable: %s (try: chmod +x)", path))
    }
    # Optionally sanity check it runs
    try({
      v <- suppressWarnings(system2(path, "--version", stdout = TRUE, stderr = TRUE))
      logf("[dowser] igphyml --version: %s", paste(v, collapse=" | "))
    }, silent = TRUE)
    return(path)
  }

  # 2) Try PATH
  cand <- Sys.which("igphyml")
  if (nzchar(cand)) {
    logf("[dowser] Using igphyml from PATH: %s", cand)
    return(cand)
  }

  # 3) Try common default (your previous default)
  default <- "/usr/local/share/igphyml/src/igphyml"
  if (file.exists(default) && file.access(default, 1) == 0) {
    logf("[dowser] Using igphyml default path: %s", default)
    return(default)
  }

  stop("IgPhyML not found. Provide 'exec' (absolute path) or install igphyml so it's on $PATH.")
}

# Keep only valid DNA letters; remove gaps/spaces; uppercase
clean_nt <- function(x) {
  s <- toupper(as.character(x))
  s[is.na(s)] <- ""
  # remove gap-like chars and spaces
  s <- gsub("[-\\.\\s]", "", s, perl = TRUE)
  # replace anything not IUPAC DNA with N
  s <- gsub("[^ACGTRYSWKMBDHVN]", "N", s, perl = TRUE)
  s
}

# TRUE if (cleaned) nucleotide seq has a stop codon when translated
has_stop_codon <- function(nt_vec) {
  nt_vec <- clean_nt(nt_vec)
  ok_len <- (nchar(nt_vec) %% 3) == 0
  out <- logical(length(nt_vec))
  if (any(ok_len)) {
    aa <- translate(DNAStringSet(nt_vec[ok_len]), if.fuzzy.codon = "X")
    out[ok_len] <- grepl("\\*", as.character(aa))
  }
  # Not multiple of 3 → "bad for IgPhyML"
  out[!ok_len] <- TRUE
  out
}

run_handler_impl <- function(req, res) {
  library(jsonlite); library(readr); library(dowser); library(ape)

  tryCatch({
    ct <- get_content_type(req)
    logf("[dowser] content-type: %s", ct)

    # ---- Parse, normalize params ----
    parse_params <- function(raw) {
      p <- tryCatch(jsonlite::fromJSON(raw), error = function(e) list())
      p$minseq            <- as.integer(p$minseq %||% 3L)
      p$nproc             <- as.integer(p$nproc  %||% 1L)
      p$tree_model        <- p$tree_model %||% "mp"
      p$tip_color_by      <- p$tip_color_by %||% "c_call"
      p$unknown_value     <- p$unknown_value %||% "unknown"
      p$tipsize           <- as.numeric(p$tipsize %||% 2)
      p$include_figures   <- isTRUE(p$include_figures %||% TRUE)
      p$annotation_fields <- unique(as.character(p$annotation_fields %||% character(0)))
      p$exec              <- p$exec %||% NULL
      p$max_tip_categories <- as.integer(p$max_tip_categories %||% 30L)
      p$disable_figures_on_many_states <- isTRUE(p$disable_figures_on_many_states %||% FALSE)
      p$ig_stop_policy <- p$ig_stop_policy %||% "drop_seqs" 
      p
    }


    db <- NULL
    p  <- NULL

    # ---- Accept big files via JSON { file_path, params } ----
    if (grepl("application/json", ct, fixed = TRUE)) {
      body_raw <- req$postBody
      if (is.raw(body_raw)) body_raw <- rawToChar(body_raw)
      body <- jsonlite::fromJSON(body_raw, simplifyVector = FALSE)
      file_path <- body$file_path %||% NULL
      p <- parse_params(jsonlite::toJSON(body$params %||% list()))
      if (is.null(file_path) || !file.exists(file_path)) {
        res$status <- 400; return(list(ok=FALSE, error="file_path is required and must exist on the server"))
      }
      db <- read_airr_from_path(file_path)

    } else {
      # ---- Fallback: multipart (for small files only) ----
      mp <- tryCatch(mime::parse_multipart(req), error = function(e) e)
      if (inherits(mp, "error")) {
        res$status <- 413
        return(list(
          ok = FALSE,
          error = paste0("Failed to parse multipart (too large?). ",
                         "Prefer JSON {\"file_path\": \"/path/to/file\", \"params\": {...}}. ",
                         mp$message)
        ))
      }

      raw_params <- mp$params %||% mp$config %||% "{}"
      if (is.list(raw_params) && !is.null(raw_params$value)) raw_params <- raw_params$value
      if (length(raw_params) > 1) raw_params <- raw_params[[1]]
      p <- parse_params(raw_params)

      f <- NULL
      if (!is.null(mp$file) && is.list(mp$file) && !is.null(mp$file$datapath)) f <- mp$file
      if (is.null(f)) {
        idx <- which(vapply(mp, function(x) is.list(x) && !is.null(x$datapath), logical(1)))
        if (length(idx)) f <- mp[[idx[1]]]
      }
      if (is.null(f) || is.null(f$datapath) || !nzchar(f$datapath)) {
        res$status <- 400; return(list(ok=FALSE, error="file is required (AIRR TSV/CSV/RDS/RDA)"))
      }
      db <- read_airr_from_path(f$datapath)
    }

    # ---- Sanity & cleaning ----
    logf("[dowser] rows=%d cols=%d", nrow(db), ncol(db))
    validate_airr_for_dowser(db)

    # enforce character IDs and drop empties
    if ("sequence_id" %in% names(db)) db$sequence_id <- as.character(db$sequence_id)
    if ("clone_id"    %in% names(db)) db$clone_id    <- as.character(db$clone_id)
    db <- db[!is.na(db$sequence_id) & nzchar(db$sequence_id) &
               !is.na(db$clone_id)    & nzchar(db$clone_id), , drop=FALSE]

        # ---- Tip-color column handling: fill unknowns & count ----
        tip_col <- as.character(p$tip_color_by %||% "c_call")
        if (length(tip_col) != 1 || is.na(tip_col) || !nzchar(tip_col)) tip_col <- "c_call"

        if (!tip_col %in% names(db)) db[[tip_col]] <- NA_character_

        orig_vals   <- as.character(db[[tip_col]])
        is_missing  <- is.na(orig_vals) | !nzchar(trimws(orig_vals))
        db[[tip_col]] <- as.character(db[[tip_col]])
        db[[tip_col]][is_missing] <- p$unknown_value
        unknown_replaced_total <- sum(is_missing, na.rm = TRUE)

        # Count distinct states (post fill)
        tip_values  <- as.character(db[[tip_col]])
        n_states    <- length(unique(tip_values[!is.na(tip_values)]))
        state_overflow <- n_states > p$max_tip_categories

        # ---- Clean alignment & germline columns (remove gaps, uppercase, non-IUPAC->N) ----
        seq_col  <- "sequence_alignment"
        germ_col <- "germline_alignment_d_mask"

        n_altered_seq  <- 0L
        n_altered_germ <- 0L
        if (seq_col %in% names(db)) {
          orig <- as.character(db[[seq_col]])
          cleaned <- clean_nt(orig)
          n_altered_seq <- sum(is.na(orig) | (gsub("[-\\.\\s]", "", toupper(orig), perl=TRUE) != cleaned), na.rm = TRUE)
          db[[seq_col]] <- cleaned
        }
        if (germ_col %in% names(db)) {
          orig <- as.character(db[[germ_col]])
          cleaned <- clean_nt(orig)
          n_altered_germ <- sum(is.na(orig) | (gsub("[-\\.\\s]", "", toupper(orig), perl=TRUE) != cleaned), na.rm = TRUE)
          db[[germ_col]] <- cleaned
        }

        # ---- IgPhyML preflight: stop-codon / frame checks ----
        n_dropped_stops <- 0L
        n_bad_frame     <- 0L
        ig_fallback     <- FALSE

        # ---- Clean alignment column for downstream translation/model checks ----
        seq_aln_col <- "sequence_alignment"
        n_altered <- 0L
        if (seq_aln_col %in% names(db)) {
          orig <- as.character(db[[seq_aln_col]])
          cleaned <- clean_nt(orig)
          n_altered <- sum(is.na(orig) | nzchar(orig) & (cleaned != toupper(gsub("[-\\.\\s]", "", orig, perl = TRUE))), na.rm = TRUE)
          db[[seq_aln_col]] <- cleaned
        }

        if (identical(p$tree_model, "igphyml")) {
          if (!"sequence_alignment" %in% names(db)) {
            stop("IgPhyML requires 'sequence_alignment'.")
          }
          sc <- has_stop_codon(db$sequence_alignment)
          n_dropped_stops <- sum(sc, na.rm = TRUE)
          n_bad_frame <- sum((nchar(as.character(db$sequence_alignment)) %% 3) != 0, na.rm = TRUE)

          if (n_dropped_stops > 0L || n_bad_frame > 0L) {
            policy <- p$ig_stop_policy
            if (identical(policy, "drop_seqs")) {
              keep <- !(sc)
              dropped <- sum(!keep, na.rm = TRUE)
              db <- db[keep, , drop = FALSE]
              # If everything got dropped, bail clearly
              if (nrow(db) == 0) {
                res$status <- 400
                return(list(ok=FALSE, error=sprintf(
                  "IgPhyML cannot run: %d sequences contain stop codons and %d are out-of-frame. Set 'ig_stop_policy' to 'drop_seqs' or 'fallback_ml' to proceed.",
                  n_dropped_stops, n_bad_frame
                )))
              }
              logf("[dowser] IgPhyML: dropped %d seqs with stop codons / bad frame", dropped)
            } else if (identical(policy, "fallback_ml")) {
              # Switch to nucleotide ML (pml)
              p$tree_model <- "ml"
              ig_fallback <- TRUE
              logf("[dowser] IgPhyML: fallback to ML (pml) due to stop codons / bad frame (n_stop=%d, n_frame=%d)",
                  n_dropped_stops, n_bad_frame)
            } else {
              res$status <- 400
              return(list(ok=FALSE, error=sprintf(
                "IgPhyML cannot run: %d sequences contain stop codons and %d are out-of-frame. Set 'ig_stop_policy' to 'drop_seqs' or 'fallback_ml' to proceed.",
                n_dropped_stops, n_bad_frame
              )))
            }
          }
        }

        # ---- Alignment length harmonization: seq vs germline must be equal length ----
        n_len_mismatch <- 0L
        n_clones_len_mismatch <- 0L
        len_policy <- (p$ig_len_policy %||% "drop_seqs")  # "drop_seqs" | "drop_clone" | "error"

        if (all(c(seq_col, germ_col) %in% names(db))) {
          seqlen  <- nchar(db[[seq_col]])
          glen    <- nchar(db[[germ_col]])
          bad_len <- is.na(seqlen) | is.na(glen) | (seqlen != glen)

          n_len_mismatch <- sum(bad_len, na.rm = TRUE)
          if (n_len_mismatch > 0L) {
            bad_clones <- unique(as.character(db$clone_id[bad_len]))
            n_clones_len_mismatch <- length(bad_clones)

            if (identical(len_policy, "drop_seqs")) {
              db <- db[!bad_len, , drop = FALSE]
              logf("[dowser] Dropped %d sequences with unequal seq/germline lengths across %d clones (policy=drop_seqs).",
                  n_len_mismatch, n_clones_len_mismatch)

              if (nrow(db) == 0) {
                res$status <- 400
                return(list(ok=FALSE, error=sprintf(
                  "All sequences removed due to unequal sequence/germline lengths (%d rows across %d clones).",
                  n_len_mismatch, n_clones_len_mismatch
                )))
              }
            } else if (identical(len_policy, "drop_clone")) {
              drop_mask <- db$clone_id %in% bad_clones
              dropped <- sum(drop_mask, na.rm = TRUE)
              db <- db[!drop_mask, , drop = FALSE]
              logf("[dowser] Dropped %d rows by removing %d mismatched clones (policy=drop_clone).",
                  dropped, n_clones_len_mismatch)

              if (nrow(db) == 0) {
                res$status <- 400
                return(list(ok=FALSE, error=sprintf(
                  "All data removed because all clones had unequal sequence/germline lengths (%d clones).",
                  n_clones_len_mismatch
                )))
              }
            } else {
              res$status <- 400
              return(list(ok=FALSE, error=sprintf(
                "Unequal sequence/germline lengths detected for %d rows across %d clones (e.g., clone %s). Set 'ig_len_policy' to 'drop_seqs' or 'drop_clone' to proceed.",
                n_len_mismatch, n_clones_len_mismatch,
                if (n_clones_len_mismatch) bad_clones[1] else "NA"
              )))
            }
          }
        }

        # ---- Build clones & trees ----
        keep_text <- unique(c(tip_col, p$annotation_fields))
        clones <- dowser::formatClones(
          db,
          text_fields = keep_text,
          minseq = p$minseq
        )
        if (nrow(clones) == 0) {
          res$status <- 400
          return(list(ok=FALSE, error=sprintf("No clones met the criteria (minseq=%d).", p$minseq)))
        }

        build <- switch(p$tree_model,
          "ml"      = "pml",
          "igphyml" = "igphyml",
          "mp"      = "pratchet",
          "pratchet"
        )

        args <- list(clones, nproc = p$nproc)
        if (build != "pratchet") args$build <- build

        # ---- IgPhyML exec resolution & validation
        if (build == "igphyml") {
          exec_path <- NULL
          # p$exec may be "" or NULL; check_igphyml_exec handles both
          exec_path <- tryCatch(check_igphyml_exec(p$exec),
                                error = function(e) {
                                  res$status <- 400
                                  stop(e)  # bubble up with a clear 400 error message
                                })
          args$exec <- exec_path
        }

        trees_tbl <- do.call(dowser::getTrees, args)

        # ---- Outputs ----
        newicks <- lapply(trees_tbl$trees, to_newick)

        figures_b64 <- NULL
        plot_label <- NULL

        if (isTRUE(p$include_figures) &&
            requireNamespace("ggtree", quietly = TRUE) &&
            requireNamespace("ggplot2", quietly = TRUE)) {

          # If too many categories, draw uncolored instead of skipping
          plot_tips <- if (state_overflow) NULL else tip_col

          plots <- tryCatch(
            dowser::plotTrees(trees_tbl, tips = plot_tips, tipsize = p$tipsize),
            error = function(e) {
              logf("[dowser][WARN] plotTrees failed: %s", as.character(e))
              dowser::plotTrees(trees_tbl, tips = NULL, tipsize = p$tipsize)
            }
          )
          figures_b64 <- lapply(plots, encode_png)
          plot_label <- if (is.null(plot_tips)) "plotTrees_uncolored_tipsize" else sprintf("plotTrees_%s_tipsize", tip_col)
          plot_label <- paste0(plot_label, as.character(p$tipsize))
        }

        # Per-tree annotations: label + tip_col + optional extras
        annos <- lapply(seq_along(trees_tbl$trees), function(i) {
          phy  <- trees_tbl$trees[[i]]
          tips <- phy$tip.label
          jj <- match(tips, db$sequence_id)
          out <- data.frame(label = tips, stringsAsFactors = FALSE)
          out[[tip_col]] <- ifelse(is.na(jj), "Germline", as.character(db[[tip_col]][jj]))
          if (length(p$annotation_fields)) {
            for (af in p$annotation_fields) {
              if (af %in% names(db)) out[[af]] <- ifelse(is.na(jj), NA, as.character(db[[af]][jj]))
            }
          }
          out
        })

        unknown_tips_per_tree <- vapply(annos, function(df) sum(df[[tip_col]] == p$unknown_value, na.rm=TRUE), integer(1))

        clones_meta <- list(
          clone_id = unname(as.list(as.character(clones$clone_id))),
          seqs     = unname(as.list(as.integer(clones$seqs)))
        )

        stats <- list(
          n_clones   = length(unique(db$clone_id)),
          n_trees    = length(trees_tbl$trees),
          total_seqs = nrow(db),
          tip_color_by = tip_col,
          unknown_value = p$unknown_value,
          unknown_replaced_in_input = unknown_replaced_total,
          unknown_tips_per_tree = unname(as.list(unknown_tips_per_tree)),
          n_tip_states = n_states,
          tip_states_capped = state_overflow,
          igphyml_fallback_to_ml = ig_fallback,
          igphyml_dropped_stop_seqs = n_dropped_stops,
          igphyml_bad_frame_seqs = n_bad_frame,
          seq_alignment_cleaned = n_altered_seq,
          germ_alignment_cleaned = n_altered_germ,
          len_mismatch_rows = n_len_mismatch,
          len_mismatch_clones = n_clones_len_mismatch,
          len_mismatch_policy = len_policy
        )

        warnings <- NULL
        if (unknown_replaced_total > 0) {
          warnings <- c(warnings, sprintf(
            "Column '%s' had %d empty/NA values → set to '%s' for tip coloring.",
            tip_col, unknown_replaced_total, p$unknown_value
          ))
        }
        if (state_overflow) {
          warnings <- c(warnings, sprintf(
            "Column '%s' has %d unique values (> max_tip_categories=%d). Plotted without tip coloring.",
            tip_col, n_states, p$max_tip_categories
          ))
        }
        if (n_altered > 0L) {
          warnings <- c(warnings, sprintf(
            "Sanitized 'sequence_alignment' for translation (removed gaps, replaced non-DNA with N) in %d sequences.",
            n_altered
          ))
        }
        if (ig_fallback) {
          warnings <- c(warnings, sprintf(
            "IgPhyML fallback: switched to nucleotide ML (pml) because %d sequences had stop codons and %d were out-of-frame.",
            n_dropped_stops, n_bad_frame
          ))
        } else if (n_dropped_stops > 0L || n_bad_frame > 0L) {
          warnings <- c(warnings, sprintf(
            "IgPhyML: dropped %d sequences with stop codons and %d out-of-frame sequences (policy=drop_seqs).",
            n_dropped_stops, n_bad_frame
          ))
        }
        if (n_altered_seq > 0L || n_altered_germ > 0L) {
          warnings <- c(warnings, sprintf(
            "Sanitized alignments: %d sequence rows and %d germline rows (removed gaps, non-IUPAC→N).",
            n_altered_seq, n_altered_germ
          ))
        }
        if (n_len_mismatch > 0L) {
          if (identical(len_policy, "drop_seqs")) {
            warnings <- c(warnings, sprintf(
              "Dropped %d sequences with unequal sequence/germline lengths across %d clones.",
              n_len_mismatch, n_clones_len_mismatch
            ))
          } else if (identical(len_policy, "drop_clone")) {
            warnings <- c(warnings, sprintf(
              "Dropped %d clones due to unequal sequence/germline lengths (removed %d rows).",
              n_clones_len_mismatch,
              NA_integer_  # optional: you can track 'dropped' count above if you want exact rows
            ))
          }
        }

        result <- list(
          ok = TRUE,
          trees = unname(newicks),
          clones = clones_meta,
          annotations = annos,
          figures = if (is.null(figures_b64)) NULL else list(png_base64 = unname(figures_b64)),
          stats = stats,
          warnings = warnings,
          render = plot_label
        )


    if (!jsonvalidate::json_validate(
      jsonlite::toJSON(result, auto_unbox = TRUE, null = "null"),
      RESULT_SCHEMA_PATH, verbose = TRUE
    )) {
      res$status <- 500
      return(list(ok = FALSE, error = "Result does not match schema"))
    }

    return(result)
  }, error = function(e) {
    logf("[dowser][ERROR] %s", as.character(e))
    res$status <- 500
    list(ok = FALSE, error = as.character(e))
  })
}

STRICT_CONTRACT <- tolower(Sys.getenv("STRICT_CONTRACT_ROUTES", "true")) %in% c("1","true","yes")

#* @plumber
function(pr) {
  if (!STRICT_CONTRACT) {
    pr$handle("GET",  "/spec", serializer = SER, function(req, res) spec_handler_impl())
    pr$handle("POST", "/run",  serializer = SER, function(req, res) run_handler_impl(req, res))
  }
  pr$handle("GET",  ROUTES$spec, serializer = SER, function(req, res) spec_handler_impl())
  pr$handle("POST", ROUTES$run,  serializer = SER, function(req, res) run_handler_impl(req, res))

  pr_set_error(pr, function(req, res, err){
    res$status <- 500
    list(ok = FALSE, error = as.character(err))
  })
  pr
}
