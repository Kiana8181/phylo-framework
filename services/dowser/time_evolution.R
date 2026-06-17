# Time-based measurable evolution analysis.

validate_time_field <- function(db, time_field, time_as_numeric = TRUE) {
  if (is.null(time_field) || !nzchar(time_field)) {
    return(list(ok = FALSE, error = "time_field is required for time_evolution analysis.", step = "dowser.validate.time_field"))
  }
  if (!time_field %in% names(db)) {
    return(list(ok = FALSE, error = sprintf("time_field '%s' not found.", time_field), step = "dowser.validate.time_field"))
  }
  vals <- db[[time_field]]
  missing <- is.na(vals) | (is.character(vals) & !nzchar(trimws(vals)))
  if (any(missing)) {
    return(list(
      ok = FALSE,
      error = sprintf(
        "time_field '%s' has %d missing values; missing times cannot be silently converted.",
        time_field, sum(missing)
      ),
      step = "dowser.validate.time_field"
    ))
  }
  if (isTRUE(time_as_numeric)) {
    if (is.character(vals)) vals <- suppressWarnings(as.numeric(vals))
    if (!is.numeric(vals) || any(is.na(vals))) {
      return(list(
        ok = FALSE,
        error = sprintf("time_field '%s' must be numeric or parseable to numeric.", time_field),
        step = "dowser.validate.time_field"
      ))
    }
    db[[time_field]] <- vals
  }
  list(ok = TRUE, db = db)
}

TIME_EVOLUTION_OBJECT_COLS <- c("data", "trees", "test_trees")

TIME_EVOLUTION_STAT_COLS <- c(
  "clone_id", "locus", "seqs",
  "slope", "p", "correlation", "random_correlation",
  "min_p", "nposs", "nclust", "p_gt", "p_lt"
)

extract_time_evolution_results <- function(res) {
  if (is.null(res)) return(list())
  if (!is.data.frame(res) || !nrow(res)) {
    return(if (is.list(res)) res else list())
  }

  keep <- intersect(TIME_EVOLUTION_STAT_COLS, names(res))
  if (!length(keep)) {
    keep <- setdiff(names(res), TIME_EVOLUTION_OBJECT_COLS)
  }

  df <- res[, keep, drop = FALSE]
  for (col in names(df)) {
    if (!is.list(df[[col]])) next
    sample_val <- df[[col]][[which(!vapply(df[[col]], is.null, logical(1)))[1]]]
    if (length(sample_val) && (isS4(sample_val) || inherits(sample_val, "phylo"))) {
      df[[col]] <- NULL
    }
  }

  dataframe_to_records(df)
}

resolve_correlation_test_fn <- function() {
  if (!requireNamespace("dowser", quietly = TRUE)) {
    dowser_validation_error(
      "dowser package is required for time evolution analysis.",
      step = "dowser.time_evolution.correlationTest"
    )
  }

  exports <- getNamespaceExports("dowser")
  if ("correlationTest" %in% exports) {
    return(getFromNamespace("correlationTest", "dowser"))
  }
  if ("runCorrelationTest" %in% exports) {
    return(getFromNamespace("runCorrelationTest", "dowser"))
  }

  ns <- asNamespace("dowser")
  for (name in c("correlationTest", "runCorrelationTest")) {
    if (exists(name, envir = ns, inherits = FALSE, mode = "function")) {
      return(get(name, envir = ns))
    }
  }

  dowser_validation_error(
    "No supported Dowser time-evolution test function found (correlationTest).",
    step = "dowser.time_evolution.correlationTest"
  )
}

run_time_evolution <- function(trees_tbl, p, db) {
  time_field <- p$time_field
  permutations <- as.integer(p$time_permutations %||% 100L)

  v <- validate_time_field(db, time_field, isTRUE(p$time_as_numeric %||% TRUE))
  if (!isTRUE(v$ok)) {
    dowser_validation_error(v$error, step = v$step)
  }

  fn <- resolve_correlation_test_fn()

  res <- tryCatch(
    fn(
      trees_tbl,
      time = time_field,
      permutations = permutations
    ),
    error = function(e) {
      dowser_validation_error(
        sprintf("Time evolution correlation test failed: %s", conditionMessage(e)),
        step = "dowser.time_evolution.correlationTest"
      )
    }
  )

  results <- extract_time_evolution_results(res)

  list(
    time_field = time_field,
    permutations = permutations,
    results = results,
    plots = list(),
    interpretation_warning = paste(
      "Correlation with sampling time suggests measurable evolution, but depends on sampling design",
      "and tree uncertainty."
    )
  )
}
