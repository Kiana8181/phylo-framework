# Dowser input loading — expects canonical AIRR column names.
# Non-standard headers must be mapped via API prepare (doMapping + column_map).

DOWSER_REQUIRED_COLUMNS <- c(
  "sequence_id",
  "clone_id",
  "sequence_alignment",
  "germline_alignment_d_mask",
  "v_call",
  "j_call"
)

read_airr_from_path <- function(path) {
  ext_err <- validate_fast_extension(path)
  if (!is.null(ext_err)) {
    dowser_validation_error(ext_err, step = "dowser.validate.file_extension")
  }

  ext <- tolower(tools::file_ext(path))
  if (ext %in% c("tsv", "txt")) {
    suppressMessages(readr::read_tsv(path, show_col_types = FALSE))
  } else if (ext == "csv") {
    suppressMessages(readr::read_csv(path, show_col_types = FALSE))
  } else if (ext == "rds") {
    readRDS(path)
  } else if (ext %in% c("rda", "rdata")) {
    e <- new.env()
    load(path, envir = e)
    e[[ls(e)[1]]]
  } else {
    dowser_validation_error(
      sprintf("Unsupported file extension: %s", ext),
      step = "dowser.validate.file_extension"
    )
  }
}

prepare_db_working <- function(db_original, p) {
  db_working <- db_original
  provenance <- list(
    db_original_rows = nrow(db_original),
    db_working_rows = nrow(db_original),
    transformations = list()
  )
  warnings <- character(0)

  err <- validate_required_columns(db_working, DOWSER_REQUIRED_COLUMNS)
  if (!is.null(err)) {
    dowser_validation_error(err, step = "dowser.validate.required_columns")
  }

  db_working$sequence_id <- as.character(db_working$sequence_id)
  db_working$clone_id <- as.character(db_working$clone_id)

  uid <- validate_sequence_id_uniqueness(db_working, "sequence_id")
  if (!isTRUE(uid$ok)) {
    dowser_validation_error(uid$error, step = uid$step)
  }

  has_junc_len <- "junction_length" %in% names(db_working) &&
    any(!is.na(db_working$junction_length) & nzchar(as.character(db_working$junction_length)))

  if (!has_junc_len) {
    if ("junction" %in% names(db_working)) {
      db_working$junction_length <- nchar(as.character(db_working$junction))
      provenance$transformations[[length(provenance$transformations) + 1]] <- list(
        field = "junction_length",
        action = "derived_from_junction",
        source_column = "junction",
        formula = "nchar(junction)"
      )
      warnings <- c(
        warnings,
        "junction_length derived from junction (nchar); recorded in data_provenance."
      )
    } else {
      dowser_validation_error(
        paste0(
          "junction_length is required. Provide junction_length or junction ",
          "(map your column to junction_length/junction via Input Mapping when doMapping is enabled)."
        ),
        step = "dowser.validate.junction_length"
      )
    }
  }

  db_working <- validate_junction_length(db_working)

  list(
    db_working = db_working,
    data_provenance = provenance,
    warnings = warnings
  )
}

prepare_tip_color_column <- function(db, tip_col, unknown_value = "unknown") {
  if (is.null(tip_col) || !nzchar(tip_col)) {
    return(list(
      db = db,
      plot_tip_col = NULL,
      unknown_replaced = 0L,
      n_states = 0L,
      warnings = character(0)
    ))
  }

  warnings <- character(0)
  if (!tip_col %in% names(db)) {
    return(list(
      db = db,
      plot_tip_col = NULL,
      unknown_replaced = 0L,
      n_states = 0L,
      warnings = sprintf(
        "Color-by column '%s' not found; tips will not be colored.",
        tip_col
      )
    ))
  }

  plot_tip_col <- paste0(".plot_", tip_col)
  values <- as.character(db[[tip_col]])
  missing <- is.na(values) | !nzchar(trimws(values))
  values[missing] <- unknown_value
  db[[plot_tip_col]] <- values

  list(
    db = db,
    plot_tip_col = plot_tip_col,
    unknown_replaced = sum(missing),
    n_states = length(unique(values[nzchar(values)])),
    warnings = warnings
  )
}
