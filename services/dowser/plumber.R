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

# Raise PCRE limits for robust regex parsing on large inputs.
options(pcre.limit.match     = 1e8)
options(pcre.limit.recursion = 2e6)
Sys.setenv(PCRE2_MATCH_LIMIT="100000000")
Sys.setenv(PCRE2_MATCH_LIMIT_RECURSION="2000000")

# ---------------------------
# Config & Contracts loading
# ---------------------------
IG_EXEC_DEFAULT   <- Sys.getenv("IGPHYML_BIN", Sys.getenv("IG_EXEC_DEFAULT", "igphyml"))
IG_MOTIFS_DEFAULT <- Sys.getenv("IGPHYML_MOTIFS", "")
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
DEFAULT_UI <- list(
  requiresFile = TRUE,
  maxFiles = 1,
  order = c("tree_model", "minseq", "nproc",
            "label_field",
            "tip_color_by", "unknown_value",
            "tipsize")
)

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

  # 3) Try common default (legacy)
  default <- "/usr/local/share/igphyml/src/igphyml"
  if (file.exists(default) && file.access(default, 1) == 0) {
    logf("[dowser] Using igphyml default path: %s", default)
    return(default)
  }

  stop("IgPhyML not found. Set IGPHYML_BIN or install igphyml so it's on $PATH.")
}

# ---------------------------
# IgPhyML resolution (exec + motifs)
# ---------------------------
validate_motifs_dir <- function(path) {
  if (!nzchar(path)) return(FALSE)
  if (!dir.exists(path)) return(FALSE)
  length(list.files(path, all.files = FALSE)) > 0
}

resolve_igphyml <- function(user_exec = IG_EXEC_DEFAULT, user_motifs = NULL, require_ok = TRUE) {
  # --- resolve exec ---
  exec_path <- tryCatch(
    check_igphyml_exec(user_exec),
    error = function(e) if (require_ok) stop(e) else NULL
  )
  if (is.null(exec_path)) {
    return(list(ok = FALSE, error = "IgPhyML executable not found or not executable. Set IGPHYML_BIN or install igphyml on PATH."))
  }

  # --- resolve motifs ---
  candidates <- unique(c(
    user_motifs,
    Sys.getenv("IGPHYML_MOTIFS", ""),
    Sys.getenv("IGPHYML_PATH", ""),
    IG_MOTIFS_DEFAULT,                                           # from top of file
    file.path(dirname(dirname(exec_path)), "share", "igphyml", "src", "motifs"),
    "/usr/local/share/igphyml/src/motifs",
    "/usr/share/igphyml/src/motifs",
    "/opt/igphyml/src/motifs"
  ))

  motifs_dir <- NULL
  for (d in candidates) {
    if (validate_motifs_dir(d)) { motifs_dir <- d; break }
  }

  if (is.null(motifs_dir)) {
    if (require_ok) {
      tried <- paste(Filter(nzchar, candidates), collapse = " | ")
      return(list(
        ok = FALSE,
        error = paste0(
          "IgPhyML hotspot motif tables not found. ",
          "Set IGPHYML_MOTIFS or IGPHYML_PATH to the directory that contains motif tables ",
          "(e.g., '/usr/local/share/igphyml/src/motifs'). ",
          "Tried: ", if (nzchar(tried)) tried else "<none>"
        )
      ))
    }
  } else {
    # Set BOTH env vars for maximum compatibility with igphyml’s own checks
    Sys.setenv(IGPHYML_MOTIFS = motifs_dir)
    Sys.setenv(IGPHYML_PATH   = motifs_dir)
    logf("[dowser] Using motifs dir: %s", motifs_dir)
  }

  list(ok = TRUE, exec = exec_path, motifs = motifs_dir)
}

# When require_ok=TRUE, returns TRUE on success, or a character error message if not found
ensure_igphyml_path <- function(exec, user_path = NULL, require_ok = FALSE) {
  # 1) user param
  if (!is.null(user_path) && nzchar(user_path)) {
    if (validate_motifs_dir(user_path)) {
      Sys.setenv(IGPHYML_MOTIFS = user_path)
      logf("[dowser] IGPHYML_MOTIFS set from override: %s", user_path)
      return(TRUE)
    } else {
      if (require_ok) {
        return(paste0(
          "IgPhyML motifs directory is invalid: '", user_path, "'. ",
          "It must be a readable, non-empty directory containing motif tables. ",
          "Set IGPHYML_MOTIFS or IGPHYML_PATH to the path of igphyml/src/motifs."
        ))
      }
      return(FALSE)
    }
  }

  # 2) env var
  cur <- Sys.getenv("IGPHYML_MOTIFS", "")
  if (validate_motifs_dir(cur)) {
    Sys.setenv(IGPHYML_MOTIFS = cur)
    return(TRUE)
  }

  # 3) common locations
  candidates <- unique(c(
    file.path(dirname(dirname(exec)), "share", "igphyml", "src", "motifs"),
    "/usr/local/share/igphyml/src/motifs",
    "/usr/share/igphyml/src/motifs",
    "/opt/igphyml/src/motifs"
  ))
  for (d in candidates) {
    if (validate_motifs_dir(d)) {
      Sys.setenv(IGPHYML_MOTIFS = d)
      logf("[dowser] IGPHYML_MOTIFS auto-detected: %s", d)
      return(TRUE)
    }
  }

  if (require_ok) {
    return(paste0(
      "IgPhyML hotspot motif tables not found. ",
      "Set IGPHYML_MOTIFS or IGPHYML_PATH to the directory containing the motif tables ",
      "(e.g., '/usr/local/share/igphyml/src/motifs') or set the IGPHYML_PATH environment variable."
    ))
  }

  FALSE
}

# ---------------------------
# Filtering helpers (policy-driven)
# ---------------------------
IUPAC        <- "ACGTRYSWKMBDHVN"
gap_re       <- "[-\\.\\s]"
non_iupac_re <- "[^ACGTRYSWKMBDHVN]"

apply_text_filters <- function(db, p, seq_col="sequence_alignment", germ_col="germline_alignment_d_mask") {
  if (!(seq_col %in% names(db) && germ_col %in% names(db))) {
    return(list(db=db, stats=list(upper=0, gap_rows=0, noniupac_rows=0), dropped=integer(0)))
  }
  s <- as.character(db[[seq_col]]);  s[is.na(s)] <- ""
  g <- as.character(db[[germ_col]]); g[is.na(g)] <- ""
  stats <- list(upper=0L, gap_rows=0L, noniupac_rows=0L)
  drop_mask <- rep(FALSE, nrow(db))

  # Uppercase (if toggled)
  if (isTRUE(p$uppercase)) {
    s2 <- toupper(s); g2 <- toupper(g)
    stats$upper <- sum(s2 != s | g2 != g, na.rm=TRUE)
    s <- s2; g <- g2
  }

  # Gap policy
  has_gap <- grepl(gap_re, s, perl=TRUE) | grepl(gap_re, g, perl=TRUE)
  stats$gap_rows <- sum(has_gap, na.rm=TRUE)
  if (p$gap_policy == "remove") {
    s <- gsub(gap_re, "",  s, perl=TRUE); g <- gsub(gap_re, "",  g, perl=TRUE)
  } else if (p$gap_policy == "replace_N") {
    s <- gsub(gap_re, "N",  s, perl=TRUE); g <- gsub(gap_re, "N",  g, perl=TRUE)
  } else if (p$gap_policy == "replace_NNN") {
    s <- gsub(gap_re, "NNN", s, perl=TRUE); g <- gsub(gap_re, "NNN", g, perl=TRUE)
  } else if (p$gap_policy == "drop_row") {
    drop_mask <- drop_mask | has_gap
  }

  # Non-IUPAC policy
  bad_non <- grepl(non_iupac_re, s, perl=TRUE) | grepl(non_iupac_re, g, perl=TRUE)
  stats$noniupac_rows <- sum(bad_non, na.rm=TRUE)
  if (p$noniupac_policy == "replace_N") {
    s <- gsub(non_iupac_re, "N", s, perl=TRUE)
    g <- gsub(non_iupac_re, "N", g, perl=TRUE)
  } else if (p$noniupac_policy == "drop_row") {
    drop_mask <- drop_mask | bad_non
  }

  db[[seq_col]]  <- s
  db[[germ_col]] <- g
  if (any(drop_mask)) db <- db[!drop_mask, , drop=FALSE]
  list(db=db, stats=stats, dropped=which(drop_mask))
}

detect_stops_and_frame <- function(seq_vec) {
  x <- toupper(gsub(gap_re, "", as.character(seq_vec), perl=TRUE))
  x[is.na(x)] <- ""
  frame_bad <- (nchar(x) %% 3) != 0
  stop_bad  <- logical(length(x))
  ok <- !frame_bad & nzchar(x)
  if (any(ok)) {
    aa <- translate(DNAStringSet(x[ok]), if.fuzzy.codon="X")
    stop_bad[ok] <- grepl("\\*", as.character(aa))
  }
  list(stop=stop_bad, frame_bad=frame_bad)
}

# Small helper: parse vectors from JSON (array OR "a,b c;d")
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

# -------------------------------------------------
# Main run handler
# -------------------------------------------------
run_handler_impl <- function(req, res) {
  library(jsonlite); library(readr); library(dowser); library(ape)
  warnings <- character(0)
  logs <- list()
  add_log <- function(step, ok, out = "") {
    logs[[length(logs) + 1]] <<- list(
      step = as.character(step),
      ok = isTRUE(ok),
      out = as.character(out %||% "")
    )
  }
  fail_local <- function(msg, status = 400, step = "dowser.error") {
    if (!is.null(step) && nzchar(step)) add_log(step, FALSE, msg)
    if (is.null(res$status) || res$status == 200) res$status <- status
    list(
      ok = FALSE,
      error = as.character(msg),
      logs = logs,
      warnings = as.list(as.character(warnings))
    )
  }

  tryCatch({
    ct <- get_content_type(req)
    logf("[dowser] content-type: %s", ct)
    add_log("dowser.request.contentType", TRUE, sprintf("content-type=%s", ct))

    # ---- Parse, normalize params ----
    parse_params <- function(raw) {
      p <- tryCatch(jsonlite::fromJSON(raw), error = function(e) list())

      p$minseq     <- as.integer(p$minseq %||% 3L)
      p$nproc      <- as.integer(p$nproc  %||% 1L)
      p$tree_model <- p$tree_model %||% "mp"

      # tip coloring: empty string => NULL
      tc <- p$tip_color_by %||% NULL
      if (is.character(tc) && length(tc) == 1 && !nzchar(tc)) tc <- NULL
      p$tip_color_by <- tc

      # annotation fields (array OR comma/space separated string)
      p$annotation_fields <- parse_vec(p$annotation_fields)

      p$unknown_value   <- p$unknown_value %||% "unknown"
      p$tipsize         <- as.numeric(p$tipsize %||% 2)

      p$label_field <- p$label_field %||% ""
      if (is.character(p$label_field) && length(p$label_field) == 1) {
        p$label_field <- trimws(p$label_field)
      }
      if (!nzchar(p$label_field)) p$label_field <- "sequence_id"

      p$max_tip_categories <- as.integer(p$max_tip_categories %||% 30L)

      # Filters (fully optional; run only when TRUE)
      p$apply_filters   <- isTRUE(p$apply_filters %||% FALSE)
      p$uppercase       <- isTRUE(p$uppercase %||% FALSE)
      p$len_policy      <- p$len_policy %||% "ignore"            # ignore | drop_seqs | drop_clone | error
      p$gap_policy      <- p$gap_policy %||% "keep"              # keep | remove | replace_N | replace_NNN | drop_row
      p$noniupac_policy <- p$noniupac_policy %||% "keep"         # keep | replace_N | drop_row

      # IgPhyML stop policy (consulted during preflight)
      p$ig_stop_policy  <- p$ig_stop_policy %||% "drop_seqs"     # drop_seqs | fallback_ml | error

      p
    }

    db <- NULL
    p  <- NULL

    # ---- JSON only: { file_path, params } ----
    if (!grepl("application/json", ct, fixed = TRUE)) {
      return(fail_local(
        "Unsupported content type. Use application/json with {\"file_path\": \"/path/to/file\", \"params\": {...}}.",
        status = 415,
        step = "dowser.request.validate"
      ))
    }

    body_raw <- req$postBody
    if (is.raw(body_raw)) body_raw <- rawToChar(body_raw)
    body <- tryCatch(
      jsonlite::fromJSON(body_raw, simplifyVector = FALSE),
      error = function(e) e
    )
    if (inherits(body, "error") || !is.list(body)) {
      return(fail_local(
        "Invalid JSON body. Expected an object with file_path and optional params.",
        status = 400,
        step = "dowser.request.parse"
      ))
    }

    file_path <- body$file_path %||% NULL
    if (is.null(file_path) || !nzchar(file_path)) {
      return(fail_local(
        "file_path is required and must exist on the server",
        status = 400,
        step = "dowser.request.validate"
      ))
    }
    if (!file.exists(file_path) || isTRUE(file.info(file_path)$isdir)) {
      return(fail_local(
        "file_path is required and must exist on the server",
        status = 400,
        step = "dowser.request.validate"
      ))
    }
    if (file.access(file_path, 4) != 0) {
      return(fail_local(
        "file_path exists but is not readable on the server",
        status = 400,
        step = "dowser.request.validate"
      ))
    }
    add_log("dowser.request.validate", TRUE, sprintf("Validated JSON request and file path: %s", file_path))

    p <- parse_params(jsonlite::toJSON(body$params %||% list()))
    add_log(
      "dowser.params.parse",
      TRUE,
      sprintf(
        "Normalized params: tree_model=%s, minseq=%d, nproc=%d, apply_filters=%s.",
        p$tree_model, p$minseq, p$nproc, if (isTRUE(p$apply_filters)) "true" else "false"
      )
    )
    db <- read_airr_from_path(file_path)
    add_log(
      "dowser.input.read",
      TRUE,
      sprintf("Loaded input table from %s with %d rows and %d columns.", file_path, nrow(db), ncol(db))
    )

    # ---- Sanity & cleaning ----
    logf("[dowser] rows=%d cols=%d", nrow(db), ncol(db))
    validate_airr_for_dowser(db)

    # enforce character IDs and drop empties
    if ("sequence_id" %in% names(db)) db$sequence_id <- as.character(db$sequence_id)
    if ("clone_id"    %in% names(db)) db$clone_id    <- as.character(db$clone_id)
    db <- db[!is.na(db$sequence_id) & nzchar(db$sequence_id) &
               !is.na(db$clone_id)    & nzchar(db$clone_id), , drop=FALSE]
    add_log(
      "dowser.input.validate",
      TRUE,
      sprintf("Validated AIRR fields and retained %d rows after removing empty sequence_id/clone_id.", nrow(db))
    )

    # --- label column existence & coercion ---
    if (!p$label_field %in% names(db)) {
      warnings <- c(warnings, sprintf("Label column '%s' not found; using 'sequence_id'.", p$label_field))
      p$label_field <- "sequence_id"
    }
    db[[p$label_field]] <- as.character(db[[p$label_field]])
    is_bad_label <- is.na(db[[p$label_field]]) | !nzchar(trimws(db[[p$label_field]]))
    if (any(is_bad_label)) {
      db[[p$label_field]][is_bad_label] <- as.character(db$sequence_id[is_bad_label])
    }

    # ---- Tip-color column handling (optional) ----
    tip_col <- p$tip_color_by
    unknown_replaced_total <- 0L
    n_states <- 0L
    state_overflow <- FALSE

    if (!is.null(tip_col)) {
      if (!tip_col %in% names(db)) {
        # Gracefully create an NA column and warn
        db[[tip_col]] <- NA_character_
        warnings <- c(warnings, sprintf("Color-by column '%s' not found; tips will be treated as '%s'.", tip_col, p$unknown_value))
      }
      orig_vals  <- as.character(db[[tip_col]])
      is_missing <- is.na(orig_vals) | !nzchar(trimws(orig_vals))
      db[[tip_col]] <- as.character(db[[tip_col]])
      db[[tip_col]][is_missing] <- p$unknown_value
      unknown_replaced_total <- sum(is_missing, na.rm = TRUE)

      tip_values <- as.character(db[[tip_col]])
      n_states   <- length(unique(tip_values[!is.na(tip_values)]))
      state_overflow <- n_states > p$max_tip_categories
    }

    # ---- Filters (run only if apply_filters = TRUE) ----
    filter_stats <- list(upper=0L, gap_rows=0L, noniupac_rows=0L)
    n_len_mismatch <- 0L
    n_clones_len_mismatch <- 0L
    n_dropped_stops <- 0L
    n_bad_frame <- 0L
    ig_fallback <- FALSE

    if (isTRUE(p$apply_filters)) {
      # Text-level edits (uppercase, gap policy, non-IUPAC)
      ft <- apply_text_filters(db, p)
      db <- ft$db
      filter_stats <- ft$stats

      # Unequal seq/germline length policy
      seqlen <- nchar(db[["sequence_alignment"]])
      glen   <- nchar(db[["germline_alignment_d_mask"]])
      bad_len <- is.na(seqlen) | is.na(glen) | (seqlen != glen)

      n_len_mismatch <- sum(bad_len, na.rm = TRUE)
      if (n_len_mismatch > 0L) {
        bad_clones <- unique(as.character(db$clone_id[bad_len]))
        n_clones_len_mismatch <- length(bad_clones)

        if (p$len_policy == "drop_seqs") {
          db <- db[!bad_len, , drop = FALSE]
          logf("[dowser] Dropped %d rows with unequal seq/germline lengths across %d clones.", n_len_mismatch, n_clones_len_mismatch)
        } else if (p$len_policy == "drop_clone") {
          drop_mask <- db$clone_id %in% bad_clones
          dropped <- sum(drop_mask, na.rm=TRUE)
          db <- db[!drop_mask, , drop = FALSE]
          logf("[dowser] Dropped %d rows by removing %d mismatched clones.", dropped, n_clones_len_mismatch)
        } else if (p$len_policy == "error") {
          return(fail_local(
            sprintf(
              "Unequal sequence/germline lengths for %d rows across %d clones (e.g., %s).",
              n_len_mismatch, n_clones_len_mismatch, if (n_clones_len_mismatch) bad_clones[1] else "NA"
            ),
            status = 400,
            step = "dowser.filters.lengthPolicy"
          ))
        } # ignore => no action
      }
      add_log(
        "dowser.filters.apply",
        TRUE,
        sprintf(
          "Applied filters with len_policy=%s; upper=%d, gap_rows=%d, noniupac_rows=%d, len_mismatch_rows=%d.",
          p$len_policy, filter_stats$upper, filter_stats$gap_rows, filter_stats$noniupac_rows, n_len_mismatch
        )
      )
    } else {
      add_log("dowser.filters.apply", TRUE, "apply_filters=FALSE; skipped optional text/length filters.")
    }

    # ---- IgPhyML preflight (ALWAYS if igphyml chosen) ----
    if (identical(p$tree_model, "igphyml")) {
      det <- detect_stops_and_frame(db$sequence_alignment)
      n_dropped_stops <- sum(det$stop, na.rm=TRUE)
      n_bad_frame     <- sum(det$frame_bad, na.rm=TRUE)

      if (n_dropped_stops > 0L || n_bad_frame > 0L) {
        if (p$ig_stop_policy == "drop_seqs") {
          keep <- !(det$stop | det$frame_bad)
          dropped <- sum(!keep, na.rm=TRUE)
          db <- db[keep, , drop=FALSE]
          logf("[dowser] IgPhyML: dropped %d rows with stop codons and/or out-of-frame.", dropped)
          if (nrow(db) == 0) {
            return(fail_local(
              sprintf(
                "All sequences removed for IgPhyML: %d had stop codons and %d were out-of-frame.",
                n_dropped_stops, n_bad_frame
              ),
              status = 400,
              step = "dowser.igphyml.preflight"
            ))
          }
        } else if (p$ig_stop_policy == "fallback_ml") {
          p$tree_model <- "ml"
          ig_fallback <- TRUE
          logf("[dowser] IgPhyML fallback -> ML due to stops/frame (stop=%d, frame=%d).",
               n_dropped_stops, n_bad_frame)
        } else { # "error"
          return(fail_local(
            sprintf(
              "IgPhyML blocked: %d sequences contain stop codons and %d are out-of-frame.",
              n_dropped_stops, n_bad_frame
            ),
            status = 400,
            step = "dowser.igphyml.preflight"
          ))
        }
      }
      add_log(
        "dowser.igphyml.preflight",
        TRUE,
        sprintf(
          "IgPhyML preflight complete; stop_rows=%d, frame_rows=%d, policy=%s, effective_model=%s.",
          n_dropped_stops, n_bad_frame, p$ig_stop_policy, p$tree_model
        )
      )
    }

    # ---- Build clones & trees ----
    keep_text <- unique(c(
      if (!is.null(tip_col)) tip_col
    ))

    clones <- dowser::formatClones(
      db,
      text_fields = keep_text,
      minseq = p$minseq
    )
    if (nrow(clones) == 0) {
      return(fail_local(
        sprintf("No clones met the criteria (minseq=%d).", p$minseq),
        status = 400,
        step = "dowser.clones.format"
      ))
    }
    add_log(
      "dowser.clones.format",
      TRUE,
      sprintf("Formatted clones successfully: %d clones (minseq=%d).", nrow(clones), p$minseq)
    )

    build <- switch(p$tree_model,
      "ml"      = "pml",
      "igphyml" = "igphyml",
      "mp"      = "pratchet",
      "pratchet"
    )

    args <- list(clones, nproc = p$nproc)
    if (build != "pratchet") args$build <- build

    # IgPhyML exec resolution & validation
    if (build == "igphyml") {
      resolved <- tryCatch(
        resolve_igphyml(user_exec = IG_EXEC_DEFAULT, user_motifs = IG_MOTIFS_DEFAULT, require_ok = TRUE),
        error = function(e) {
          return(structure(list(.error = TRUE, msg = conditionMessage(e)), class = "exec_error"))
        }
      )

      if (inherits(resolved, "exec_error")) {
        return(fail_local(resolved$msg, status = 400, step = "dowser.igphyml.resolve"))
      }
      if (!isTRUE(resolved$ok)) {
        return(fail_local(resolved$error, status = 400, step = "dowser.igphyml.resolve"))
      }

      args$exec <- resolved$exec
      add_log(
        "dowser.igphyml.resolve",
        TRUE,
        sprintf("Resolved IgPhyML executable: %s", resolved$exec)
      )
    }

    trees_tbl <- tryCatch(
      do.call(dowser::getTrees, args),
      error = function(e) {
        msg <- conditionMessage(e)
        if (grepl("stop codon|out[- ]of[- ]frame", msg, ignore.case = TRUE)) {
          return(fail_local(
            paste0(
              "IgPhyML failed due to stop codons/frame issues. ",
              "Use 'ig_stop_policy' = 'drop_seqs' (recommended) or 'fallback_ml'."
            ),
            status = 400,
            step = "dowser.trees.build"
          ))
        }
        if (grepl("Hotspot tables not found|IGPHYML_PATH", msg, ignore.case = TRUE)) {
          return(fail_local(
            paste0(
              "IgPhyML hotspot motif tables not found. ",
              "Set IGPHYML_MOTIFS or $IGPHYML_PATH to the motifs directory."
            ),
            status = 400,
            step = "dowser.trees.build"
          ))
        }
        stop(e)
      }
    )
    if (is.list(trees_tbl) && identical(trees_tbl$ok, FALSE)) return(trees_tbl)
    add_log(
      "dowser.trees.build",
      TRUE,
      sprintf("Constructed %d trees using model '%s'.", length(trees_tbl$trees), build)
    )

    # ---- Outputs ----
    newicks <- lapply(trees_tbl$trees, to_newick)

    figures_b64 <- NULL
    plot_label <- NULL

    # Always try to produce figures (uncolored if too many states or no tip column)
    if (requireNamespace("ggtree", quietly = TRUE) &&
        requireNamespace("ggplot2", quietly = TRUE)) {
      plot_tips <- if (!is.null(tip_col) && !state_overflow) tip_col else NULL
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
    } else {
      logf("[dowser][WARN] ggtree/ggplot2 not available; no PNG previews will be returned.")
    }
    add_log(
      "dowser.figures.render",
      TRUE,
      sprintf(
        "Figure rendering complete; previews=%d, render_tag=%s.",
        if (is.null(figures_b64)) 0 else length(figures_b64),
        plot_label %||% "<none>"
      )
    )

    # Per-tree annotations (tip column optional) + extras
    trees_relabelled <- vector("list", length(trees_tbl$trees))
    annos <- vector("list", length(trees_tbl$trees))

    for (i in seq_along(trees_tbl$trees)) {
      phy  <- trees_tbl$trees[[i]]
      tips <- phy$tip.label

      # Match original tips (sequence_id) back to db rows
      jj <- match(tips, db$sequence_id)

      # Build display labels
      disp <- ifelse(
        is.na(jj), 
        "Germline",
        as.character(db[[p$label_field]][jj])
      )

      # Relabel tree for Newick export (display labels)
      phy$tip.label <- disp
      trees_relabelled[[i]] <- phy

      # Base annotation record: display label + original sequence_id
      out <- data.frame(
        label        = disp,
        sequence_id  = ifelse(is.na(jj), NA_character_, as.character(db$sequence_id[jj])),
        stringsAsFactors = FALSE
      )

      # Add coloring column (if set)
      if (!is.null(tip_col)) {
        out[[tip_col]] <- ifelse(is.na(jj), "Germline", as.character(db[[tip_col]][jj]))
      }

      # Add requested annotation fields that *exist*
      if (length(p$annotation_fields)) {
        present <- intersect(p$annotation_fields, names(db))
        if (length(present)) {
          for (fld in present) {
            out[[fld]] <- ifelse(is.na(jj), NA_character_, as.character(db[[fld]][jj]))
          }
        }
      }

      annos[[i]] <- out
    }

    # Use relabelled trees for Newick + plotting
    newicks <- lapply(trees_relabelled, to_newick)

    if (requireNamespace("ggtree", quietly = TRUE) &&
        requireNamespace("ggplot2", quietly = TRUE)) {
      plot_tips <- if (!is.null(tip_col) && !state_overflow) tip_col else NULL
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
    } else {
      logf("[dowser][WARN] ggtree/ggplot2 not available; no PNG previews will be returned.")
    }
    add_log(
      "dowser.figures.renderFinal",
      TRUE,
      sprintf(
        "Final figure payload prepared; previews=%d, render_tag=%s.",
        if (is.null(figures_b64)) 0 else length(figures_b64),
        plot_label %||% "<none>"
      )
    )

    unknown_tips_per_tree <- if (!is.null(tip_col)) {
      vapply(annos, function(df) sum(df[[tip_col]] == p$unknown_value, na.rm=TRUE), integer(1))
    } else integer(length(annos))
    add_log(
      "dowser.annotations.build",
      TRUE,
      sprintf("Built annotations for %d trees with label_field='%s'.", length(annos), p$label_field)
    )

    clones_meta <- list(
      clone_id = unname(as.list(as.character(clones$clone_id))),
      seqs     = unname(as.list(as.integer(clones$seqs)))
    )

    stats <- list(
      n_clones   = length(unique(db$clone_id)),
      n_trees    = length(trees_tbl$trees),
      total_seqs = nrow(db),

      tip_color_by = if (is.null(tip_col)) NULL else tip_col,
      unknown_value = p$unknown_value,
      unknown_replaced_in_input = unknown_replaced_total,
      unknown_tips_per_tree = unname(as.list(unknown_tips_per_tree)),
      n_tip_states = if (is.null(tip_col)) 0 else n_states,
      tip_states_capped = if (is.null(tip_col)) FALSE else state_overflow,

      # filter stats
      filters_applied = isTRUE(p$apply_filters),
      uppercased_rows = filter_stats$upper,
      gap_rows_touched = filter_stats$gap_rows,
      noniupac_rows_touched = filter_stats$noniupac_rows,
      len_mismatch_rows = n_len_mismatch,
      len_mismatch_clones = n_clones_len_mismatch,
      len_mismatch_policy = p$len_policy,

      # IgPhyML preflight outcomes
      igphyml_fallback_to_ml = ig_fallback,
      igphyml_stop_rows = n_dropped_stops,
      igphyml_frame_rows = n_bad_frame
    )
    stats$label_field <- p$label_field

    # --- Warnings aggregation ---
    if (!is.null(tip_col) && unknown_replaced_total > 0) {
      warnings <- c(warnings, sprintf(
        "Column '%s' had %d empty/NA values → set to '%s' for tip coloring.",
        tip_col, unknown_replaced_total, p$unknown_value
      ))
    }
    if (!is.null(tip_col) && state_overflow) {
      warnings <- c(warnings, sprintf(
        "Column '%s' has %d unique values (> max_tip_categories=%d). Plotted without tip coloring.",
        tip_col, n_states, p$max_tip_categories
      ))
    }

    # --- IgPhyML preflight warnings (always, if relevant) ---
    if (ig_fallback) {
      warnings <- c(warnings, sprintf(
        "IgPhyML fallback: switched to nucleotide ML (pml) because %d rows had stop codons and %d were out-of-frame.",
        n_dropped_stops, n_bad_frame
      ))
    }

    if (identical(p$ig_stop_policy, "drop_seqs") && (n_dropped_stops > 0L || n_bad_frame > 0L)) {
      warnings <- c(warnings, sprintf(
        "IgPhyML: dropped %d sequences with stop codons and %d out-of-frame sequences (policy=drop_seqs).",
        n_dropped_stops, n_bad_frame
      ))
    }

    if (isTRUE(p$apply_filters)) {
      if (isTRUE(p$uppercase) && filter_stats$upper > 0)
        warnings <- c(warnings, sprintf("Uppercased %d rows.", filter_stats$upper))

      if (p$gap_policy == "remove" && filter_stats$gap_rows > 0)
        warnings <- c(warnings, sprintf("Removed gaps in %d rows.", filter_stats$gap_rows))
      if (p$gap_policy %in% c("replace_N","replace_NNN") && filter_stats$gap_rows > 0)
        warnings <- c(warnings, sprintf("Replaced gaps in %d rows.", filter_stats$gap_rows))
      if (p$gap_policy == "drop_row" && filter_stats$gap_rows > 0)
        warnings <- c(warnings, sprintf("Dropped %d rows due to gap characters.", filter_stats$gap_rows))

      if (p$noniupac_policy == "replace_N" && filter_stats$noniupac_rows > 0)
        warnings <- c(warnings, sprintf("Replaced non-IUPAC letters in %d rows.", filter_stats$noniupac_rows))
      if (p$noniupac_policy == "drop_row" && filter_stats$noniupac_rows > 0)
        warnings <- c(warnings, sprintf("Dropped %d rows with non-IUPAC letters.", filter_stats$noniupac_rows))
      if (n_len_mismatch > 0L) {
        if (p$len_policy == "drop_seqs") {
          warnings <- c(warnings, sprintf(
            "Dropped %d sequences with unequal sequence/germline lengths across %d clones.",
            n_len_mismatch, n_clones_len_mismatch
          ))
        } else if (p$len_policy == "drop_clone") {
          warnings <- c(warnings, sprintf(
            "Dropped %d clones due to unequal sequence/germline lengths.",
            n_clones_len_mismatch
          ))
        }
      }
    }  

    # --- Force warnings to be a JSON array ([] or ["..."]) ---
    if (is.null(warnings)) warnings <- character(0)
    warnings <- as.character(warnings)
    warnings_json <- unname(as.list(warnings))

    result <- list(
      ok = TRUE,
      trees = unname(newicks),
      clones = clones_meta,
      annotations = annos,
      figures = if (is.null(figures_b64)) NULL else list(phylogeny = unname(figures_b64)),
      stats = stats,
      warnings = warnings_json,
      logs = logs,
      render = plot_label
    )
    add_log(
      "dowser.outputs.assemble",
      TRUE,
      sprintf("Prepared output payload: trees=%d, figures=%d.", length(newicks), if (is.null(figures_b64)) 0 else length(figures_b64))
    )
    result$logs <- logs

    if (!jsonvalidate::json_validate(
      jsonlite::toJSON(result, auto_unbox = TRUE, null = "null"),
      RESULT_SCHEMA_PATH, verbose = TRUE
    )) {
      return(fail_local("Internal server error", status = 500, step = "dowser.contract.validate"))
    }

    add_log("dowser.contract.validate", TRUE, "Result payload validated against contract schema.")
    result$logs <- logs
    return(result)
  }, error = function(e) {
    logf("[dowser][ERROR] %s", as.character(e))
    status_code <- if (is.null(res$status) || res$status == 200) 500 else res$status
    fail_local(conditionMessage(e), status = status_code, step = "dowser.unhandled")
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
