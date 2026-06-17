# Discrete Trait Analysis (DTA) and class-switching constraints.

MAX_MODELFILE_TEXT_BYTES <- 65536L

normalize_modelfile_text <- function(text) {
  if (is.null(text)) return(NULL)
  text <- as.character(text)[1]
  text <- gsub("\r\n?", "\n", text)
  if (!nzchar(trimws(text))) return(NULL)
  text
}

looks_like_modelfile_text <- function(value) {
  value <- normalize_modelfile_text(value)
  if (is.null(value)) return(FALSE)
  grepl("\n", value, fixed = TRUE) ||
    grepl("^\\s*#BEGIN\\b", value, perl = TRUE) ||
    grepl("#STATES", value, fixed = TRUE)
}

validate_trait_modelfile_text <- function(text) {
  text <- normalize_modelfile_text(text)
  if (is.null(text)) {
    return(list(ok = FALSE, error = "Custom trait model file content is empty."))
  }
  if (nchar(text, type = "bytes") > MAX_MODELFILE_TEXT_BYTES) {
    return(list(
      ok = FALSE,
      error = sprintf(
        "Custom trait model file content is too large (%d bytes > %d bytes).",
        nchar(text, type = "bytes"), MAX_MODELFILE_TEXT_BYTES
      )
    ))
  }

  lines <- trimws(strsplit(text, "\n", fixed = TRUE)[[1]])
  marker_line <- function(marker) which(lines == marker)

  required <- c("#BEGIN", "#STATES", "#CONSTRAINTS", "#AMBIGUOUS")
  missing <- required[!vapply(required, function(m) length(marker_line(m)) == 1L, logical(1))]
  if (length(missing)) {
    return(list(
      ok = FALSE,
      error = sprintf(
        "Custom trait model file must contain exactly one of each required section marker: %s. Missing or duplicated: %s.",
        paste(required, collapse = ", "),
        paste(missing, collapse = ", ")
      )
    ))
  }

  begin_idx <- marker_line("#BEGIN")
  states_idx <- marker_line("#STATES")
  constraints_idx <- marker_line("#CONSTRAINTS")
  ambiguous_idx <- marker_line("#AMBIGUOUS")
  if (!(begin_idx < states_idx && states_idx < constraints_idx && constraints_idx < ambiguous_idx)) {
    return(list(
      ok = FALSE,
      error = "Custom trait model file sections must be ordered as #BEGIN, #STATES, #CONSTRAINTS, #AMBIGUOUS."
    ))
  }
  if (begin_idx + 1L >= states_idx || !grepl("^[0-9]+$", lines[begin_idx + 1L])) {
    return(list(ok = FALSE, error = "#BEGIN must be followed by the number of model states."))
  }

  section_lines <- function(start_idx, end_idx) {
    if (start_idx + 1L > end_idx - 1L) return(character(0))
    lines[(start_idx + 1L):(end_idx - 1L)]
  }

  states <- section_lines(states_idx, constraints_idx)
  states <- states[nzchar(states)]
  if (!length(states)) {
    return(list(ok = FALSE, error = "#STATES must contain at least one trait state."))
  }
  if (anyDuplicated(states)) {
    return(list(ok = FALSE, error = "#STATES contains duplicate trait states."))
  }
  declared_n <- as.integer(lines[begin_idx + 1L])
  if (!identical(declared_n, length(states))) {
    return(list(
      ok = FALSE,
      error = sprintf("#BEGIN declares %d states, but #STATES contains %d.", declared_n, length(states))
    ))
  }

  bad_state <- states[grepl("\\s", states, perl = TRUE)]
  if (length(bad_state)) {
    return(list(
      ok = FALSE,
      error = sprintf("Trait state names must not contain whitespace: %s.", paste(bad_state, collapse = ", "))
    ))
  }

  constraints <- section_lines(constraints_idx, ambiguous_idx)
  constraints <- constraints[nzchar(constraints)]
  for (line in constraints) {
    parts <- strsplit(line, "\\s+", perl = TRUE)[[1]]
    if (length(parts) != 3L || !parts[1] %in% states || !parts[2] %in% states || is.na(suppressWarnings(as.numeric(parts[3])))) {
      return(list(
        ok = FALSE,
        error = sprintf("Invalid #CONSTRAINTS row '%s'; expected '<from_state> <to_state> <numeric_penalty>'.", line)
      ))
    }
  }

  ambiguous <- if (ambiguous_idx < length(lines)) lines[(ambiguous_idx + 1L):length(lines)] else character(0)
  ambiguous <- ambiguous[nzchar(ambiguous)]
  for (line in ambiguous) {
    parts <- strsplit(line, "\\s+", perl = TRUE)[[1]]
    if (length(parts) != 2L || !parts[2] %in% states) {
      return(list(
        ok = FALSE,
        error = sprintf("Invalid #AMBIGUOUS row '%s'; expected '<ambiguous_name> <state>'.", line)
      ))
    }
  }

  normalized_lines <- c(
    "#BEGIN",
    as.character(length(states)),
    "",
    "#STATES",
    states,
    "",
    "#CONSTRAINTS",
    constraints,
    "",
    "",
    "#AMBIGUOUS",
    ambiguous
  )

  list(ok = TRUE, error = NULL, lines = normalized_lines, states = states)
}

write_trait_modelfile_text_tmp <- function(text, tmpdir) {
  validated <- validate_trait_modelfile_text(text)
  if (!isTRUE(validated$ok)) {
    dowser_validation_error(validated$error, step = "dowser.validate.modelfile")
  }
  path <- file.path(tmpdir, "custom_trait_model.txt")
  writeLines(validated$lines, path, useBytes = TRUE)
  normalizePath(path, mustWork = FALSE)
}

resolve_trait_modelfile <- function(p, tmpdir) {
  text <- normalize_modelfile_text(p$modelfile_text %||% NULL)
  raw_value <- normalize_modelfile_text(p$modelfile %||% NULL)
  if (!is.null(text) && !is.null(raw_value)) {
    dowser_validation_error(
      "Provide only one custom trait model source: modelfile_text or modelfile.",
      step = "dowser.validate.modelfile"
    )
  }

  if (!is.null(text)) {
    path <- write_trait_modelfile_text_tmp(text, tmpdir)
    return(list(path = path, source = "text", trait_model = "custom"))
  }
  if (is.null(raw_value)) return(NULL)

  if (looks_like_modelfile_text(raw_value)) {
    path <- write_trait_modelfile_text_tmp(raw_value, tmpdir)
    return(list(path = path, source = "text", trait_model = "custom"))
  }

  path <- normalizePath(raw_value, mustWork = FALSE)
  if (!file.exists(path) || isTRUE(file.info(path)$isdir)) {
    dowser_validation_error(
      sprintf("Custom trait model file path does not exist or is not a file: %s", raw_value),
      step = "dowser.validate.modelfile"
    )
  }
  if (file.access(path, 4) != 0) {
    dowser_validation_error(
      sprintf("Custom trait model file path is not readable: %s", path),
      step = "dowser.validate.modelfile"
    )
  }
  file_text <- paste(readLines(path, warn = FALSE), collapse = "\n")
  valid <- validate_trait_modelfile_text(file_text)
  if (!isTRUE(valid$ok)) {
    dowser_validation_error(valid$error, step = "dowser.validate.modelfile")
  }
  tmp_path <- file.path(tmpdir, "custom_trait_model.txt")
  writeLines(valid$lines, tmp_path, useBytes = TRUE)
  list(path = normalizePath(tmp_path, mustWork = FALSE), source = "path", trait_model = "custom")
}

build_trait_modelfile <- function(p, tmpdir) {
  trait_model <- p$trait_model %||% "unconstrained"
  if (!identical(trait_model, "isotype_irreversible")) return(NULL)

  isotype_order <- parse_vec(p$isotype_order)
  if (!length(isotype_order)) isotype_order <- DEFAULT_ISOTYPE_ORDER

  exceptions <- parse_vec(p$isotype_exceptions)
  if (!length(exceptions)) exceptions <- DEFAULT_ISOTYPE_EXCEPTIONS

  modelfile <- file.path(tmpdir, "isotype_model.txt")
  dowser::makeModelFile(
    file = modelfile,
    states = isotype_order,
    constraints = "irrev",
    exceptions = exceptions
  )
  list(
    path = modelfile,
    isotype_order = isotype_order,
    isotype_exceptions = exceptions,
    trait_model = trait_model
  )
}

dataframe_to_records <- function(df) {
  if (is.null(df) || !is.data.frame(df) || !nrow(df)) return(list())
  jsonlite::fromJSON(jsonlite::toJSON(df, dataframe = "rows"), simplifyVector = FALSE)
}

extract_dowser_test_result <- function(x) {
  if (is.null(x)) {
    return(list(summary = list(), raw = list(), available_fields = list()))
  }

  summary_df <- NULL
  raw_df <- NULL

  if (!is.null(x$summary) && is.data.frame(x$summary)) summary_df <- x$summary
  if (is.null(summary_df) && !is.null(x$means) && is.data.frame(x$means)) summary_df <- x$means
  if (is.null(summary_df) && is.data.frame(x)) summary_df <- x

  if (!is.null(x$raw) && is.data.frame(x$raw)) raw_df <- x$raw
  if (is.null(raw_df) && !is.null(x$reps) && is.data.frame(x$reps)) raw_df <- x$reps
  if (is.null(raw_df) && !is.null(x$replicates) && is.data.frame(x$replicates)) raw_df <- x$replicates
  if (is.null(raw_df) && !is.null(x$permutations) && is.data.frame(x$permutations)) raw_df <- x$permutations

  list(
    summary = if (!is.null(summary_df)) dataframe_to_records(summary_df) else list(),
    raw = if (!is.null(raw_df)) dataframe_to_records(raw_df) else list(),
    available_fields = as.list(names(x))
  )
}

find_switches_input_arg <- function(switch_input) {
  if (!requireNamespace("dowser", quietly = TRUE)) return("clones")
  fs <- tryCatch(formals(dowser::findSwitches), error = function(e) NULL)
  if (is.null(fs)) return("clones")
  names(fs)[1]
}

build_find_switches_args <- function(switch_input, p, modelfile_path = NULL, preflight = NULL, fixtrees = TRUE) {
  trait <- p$trait_field
  permutations <- as.integer(p$permutations %||% 100L)
  tip_switch <- as.integer(p$tip_switch %||% 20L)

  ig_exec <- NULL
  if (!is.null(preflight$igphyml)) ig_exec <- preflight$igphyml$exec

  first_arg <- find_switches_input_arg(switch_input)
  switch_args <- list(
    permutations = permutations,
    trait = trait,
    fixtrees = fixtrees,
    tip_switch = tip_switch,
    nproc = as.integer(p$nproc %||% 1L)
  )
  switch_args[[first_arg]] <- switch_input
  if (!is.null(ig_exec)) switch_args$igphyml <- ig_exec
  if (!is.null(modelfile_path) && file.exists(modelfile_path)) switch_args$modelfile <- modelfile_path
  switch_args
}

call_testPS <- function(sw_df) {
  args <- list(sw_df)
  if ("permuteAll" %in% names(formals(dowser::testPS))) {
    # testPS does not support permuteAll; never forward it.
  }
  list(
    result = do.call(dowser::testPS, args),
    warnings = character(0)
  )
}

call_testSP <- function(sw_df, alternative, permute_all) {
  args <- list(sw_df, alternative = alternative)
  warnings <- character(0)
  if ("permuteAll" %in% names(formals(dowser::testSP))) {
    args$permuteAll <- isTRUE(permute_all)
  } else if (isTRUE(permute_all)) {
    warnings <- c(warnings, "permuteAll is not supported by the installed Dowser testSP; ignoring permute_all.")
  }
  list(
    result = do.call(dowser::testSP, args),
    warnings = warnings
  )
}

call_testSC <- function(sw_df, alternative, permute_all) {
  args <- list(sw_df)
  if ("alternative" %in% names(formals(dowser::testSC))) {
    args$alternative <- alternative
  }
  warnings <- character(0)
  if ("permuteAll" %in% names(formals(dowser::testSC))) {
    args$permuteAll <- isTRUE(permute_all)
  } else if (isTRUE(permute_all)) {
    warnings <- c(warnings, "permuteAll is not supported by the installed Dowser testSC; ignoring permute_all.")
  }
  list(
    result = do.call(dowser::testSC, args),
    warnings = warnings
  )
}

run_dta_analysis <- function(clones, trees_tbl, p, modelfile_path = NULL, preflight = NULL) {
  trait <- p$trait_field
  permutations <- as.integer(p$permutations %||% 100L)
  tip_switch <- as.integer(p$tip_switch %||% 20L)
  permute_all <- isTRUE(p$permute_all %||% FALSE)
  alternative <- p$alternative %||% "greater"
  if (!alternative %in% ALTERNATIVE_ENUM) alternative <- "greater"

  fixtrees <- TRUE
  switch_input <- if (isTRUE(fixtrees)) trees_tbl else clones
  switch_args <- build_find_switches_args(switch_input, p, modelfile_path, preflight, fixtrees = fixtrees)

  dta_warnings <- character(0)

  switches <- tryCatch(
    do.call(dowser::findSwitches, switch_args),
    error = function(e) {
      dowser_validation_error(
        sprintf("findSwitches failed: %s", conditionMessage(e)),
        step = "dowser.dta.findSwitches"
      )
    }
  )

  sw_df <- if (is.data.frame(switches)) {
    switches
  } else if (!is.null(switches$switches) && is.data.frame(switches$switches)) {
    switches$switches
  } else {
    dowser_validation_error(
      "findSwitches returned unexpected structure (expected data.frame or list with $switches).",
      step = "dowser.dta.findSwitches"
    )
  }

  ps <- NULL
  if (isTRUE(p$run_test_ps %||% TRUE)) {
    ps_call <- tryCatch(
      call_testPS(sw_df),
      error = function(e) {
        dowser_validation_error(
          sprintf("testPS failed: %s", conditionMessage(e)),
          step = "dowser.dta.testPS"
        )
      }
    )
    ps <- ps_call$result
  }

  sp <- NULL
  if (isTRUE(p$run_test_sp %||% TRUE)) {
    sp_call <- tryCatch(
      call_testSP(sw_df, alternative, permute_all),
      error = function(e) {
        dowser_validation_error(
          sprintf("testSP failed: %s", conditionMessage(e)),
          step = "dowser.dta.testSP"
        )
      }
    )
    dta_warnings <- c(dta_warnings, sp_call$warnings)
    sp <- sp_call$result
  }

  sc <- NULL
  if (isTRUE(p$run_test_sc %||% TRUE)) {
    sc_call <- tryCatch(
      call_testSC(sw_df, alternative, permute_all),
      error = function(e) {
        dowser_validation_error(
          sprintf("testSC failed: %s", conditionMessage(e)),
          step = "dowser.dta.testSC"
        )
      }
    )
    dta_warnings <- c(dta_warnings, sc_call$warnings)
    sc <- sc_call$result
  }

  ps_out <- extract_dowser_test_result(ps)
  sp_out <- extract_dowser_test_result(sp)
  sc_out <- extract_dowser_test_result(sc)

  list(
    trait_field = trait,
    trait_model = p$trait_model %||% "unconstrained",
    permutations = permutations,
    tip_switch = tip_switch,
    permute_all = permute_all,
    alternative = alternative,
    switches = dataframe_to_records(sw_df),
    ps = ps_out,
    sp = sp_out,
    sc = sc_out,
    warnings = as.list(as.character(unique(dta_warnings))),
    interpretation_warning = paste(
      "Significant trait transitions are evidence of tree/trait association, not direct proof of",
      "migration, differentiation, or class switching."
    )
  )
}
