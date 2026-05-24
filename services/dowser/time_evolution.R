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

run_time_evolution <- function(trees_tbl, p, db) {
  time_field <- p$time_field
  permutations <- as.integer(p$time_permutations %||% 100L)

  v <- validate_time_field(db, time_field, isTRUE(p$time_as_numeric %||% TRUE))
  if (!isTRUE(v$ok)) {
    dowser_validation_error(v$error, step = v$step)
  }

  fn <- if (exists("runCorrelationTest", where = asNamespace("dowser"), inherits = FALSE)) {
    dowser::runCorrelationTest
  } else {
    dowser::correlationTest
  }

  res <- fn(
    trees_tbl,
    time = time_field,
    permutations = permutations
  )

  results <- if (is.data.frame(res)) {
    jsonlite::fromJSON(jsonlite::toJSON(res, dataframe = "rows"), simplifyVector = FALSE)
  } else if (is.list(res)) {
    res
  } else {
    list()
  }

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
