# Discrete Trait Analysis (DTA) and class-switching constraints.

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
