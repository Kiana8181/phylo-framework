# Dowser run handler orchestration.

parse_dowser_params <- function(raw) {
  p <- tryCatch(jsonlite::fromJSON(raw), error = function(e) list())

  removed_err <- reject_removed_params(p)
  if (!is.null(removed_err)) {
    dowser_validation_error(removed_err, step = "dowser.params.removed")
  }

  p$minseq <- as.integer(p$minseq %||% 3L)
  p$nproc <- as.integer(p$nproc %||% 1L)
  p$seed <- as.integer(p$seed %||% 42L)
  p$analysis_mode <- normalize_col(p$analysis_mode, "tree_only")
  mode_err <- validate_analysis_mode(p$analysis_mode)
  if (!is.null(mode_err)) dowser_validation_error(mode_err, step = "dowser.params.analysis_mode")

  build_res <- resolve_tree_build(p)
  if (!isTRUE(build_res$ok)) {
    dowser_validation_error(build_res$error, step = "dowser.params.tree_build")
  }
  p$tree_build <- build_res$build

  tc <- p$tip_color_by %||% NULL
  if (is.character(tc) && length(tc) == 1 && !nzchar(tc)) tc <- NULL
  p$tip_color_by <- tc

  p$annotation_fields <- parse_vec(p$annotation_fields)
  p$numeric_annotation_fields <- parse_vec(p$numeric_annotation_fields)
  p$columns <- parse_vec(p$columns)
  p$unknown_value <- p$unknown_value %||% "unknown"
  p$tipsize <- as.numeric(p$tipsize %||% 2)
  tsb <- p$tip_size_by %||% NULL
  if (is.character(tsb) && length(tsb) == 1 && !nzchar(tsb)) tsb <- NULL
  p$tip_size_by <- tsb
  p$max_tip_categories <- as.integer(p$max_tip_categories %||% 30L)

  p$label_field <- normalize_col(p$label_field, "sequence_id")
  p$collapse_identical_sequences <- as_bool(p$collapse_identical_sequences, TRUE)
  p$collapse_internal_nodes <- as_bool(p$collapse_internal_nodes, TRUE)
  p$check_divergence <- as_bool(p$check_divergence, TRUE)
  p$show_node_numbers <- as_bool(p$show_node_numbers, FALSE)
  p$return_internal_sequences <- as_bool(p$return_internal_sequences, FALSE)
  p$export_all_sequences_fasta <- as_bool(p$export_all_sequences_fasta, FALSE)

  p$mod3 <- as_bool(p$mod3, FALSE)
  p$filterstop <- as_bool(p$filterstop, FALSE)
  p$use_regions <- as_bool(p$use_regions, FALSE)

  if (identical(p$analysis_mode, "tree_with_internal_sequences")) {
    p$return_internal_sequences <- TRUE
    p$show_node_numbers <- as_bool(p$show_node_numbers, TRUE)
  }

  p$trait_field <- normalize_col(p$trait_field, NULL)
  if (!is.null(p$trait_field) && startsWith(p$trait_field, ".plot_")) {
    dowser_validation_error(
      "Plot-only columns cannot be used as biological DTA traits.",
      step = "dowser.validate.trait_field"
    )
  }
  p$trait_model <- normalize_col(p$trait_model, "unconstrained")
  p$permutations <- as.integer(p$permutations %||% 100L)
  p$tip_switch <- as.integer(p$tip_switch %||% 20L)
  p$permute_all <- as_bool(p$permute_all, FALSE)
  p$alternative <- normalize_col(p$alternative, "greater")
  p$run_test_ps <- as_bool(p$run_test_ps, TRUE)
  p$run_test_sp <- as_bool(p$run_test_sp, TRUE)
  p$run_test_sc <- as_bool(p$run_test_sc, TRUE)
  p$modelfile <- normalize_modelfile_text(p$modelfile %||% NULL)
  p$modelfile_text <- normalize_modelfile_text(p$modelfile_text %||% NULL)

  p$partition_model <- normalize_col(p$partition_model, "single")
  p$return_igphyml_parameters <- as_bool(p$return_igphyml_parameters, TRUE)

  p$chain_mode <- normalize_col(p$chain_mode, "H")
  p$heavy_locus <- normalize_col(p$heavy_locus, "IGH")
  p$split_light <- as_bool(p$split_light, FALSE)
  p$light_traits <- as_bool(p$light_traits, FALSE)
  p$majoronly <- as_bool(p$majoronly, FALSE)

  p$time_field <- normalize_col(p$time_field, NULL)
  p$time_permutations <- as.integer(p$time_permutations %||% 100L)
  p$time_as_numeric <- as_bool(p$time_as_numeric, TRUE)

  part_res <- validate_partition_model(p)
  if (!isTRUE(part_res$ok)) {
    dowser_validation_error(part_res$error, step = part_res$step)
  }

  if (identical(p$trait_field, "c_call") && identical(p$trait_model, "unconstrained")) {
    p$trait_model <- "isotype_irreversible"
  }

  p
}

run_handler_impl <- function(req, res) {
  warnings <- character(0)
  logs <- list()
  add_log <- function(step, ok, out = "") {
    logs[[length(logs) + 1]] <<- list(
      step = as.character(step),
      ok = isTRUE(ok),
      out = as.character(out %||% "")
    )
  }
  fail_local <- function(msg, status = 400, step = "dowser.error", details = NULL) {
    if (!is.null(step) && nzchar(step)) add_log(step, FALSE, msg)
    if (is.null(res$status) || res$status == 200) res$status <- status
    out <- list(
      ok = FALSE,
      error = as.character(msg),
      step = step,
      logs = logs,
      warnings = as.list(as.character(warnings))
    )
    if (!is.null(details)) out$details <- details
    out
  }

  tryCatch({
    ct <- get_content_type(req)
    add_log("dowser.request.contentType", TRUE, sprintf("content-type=%s", ct))

    if (!grepl("application/json", ct, fixed = TRUE)) {
      return(fail_local(
        "Unsupported content type. Use application/json with {\"file_path\": \"...\", \"params\": {...}}.",
        status = 415,
        step = "dowser.request.validate"
      ))
    }

    body_raw <- req$postBody
    if (is.raw(body_raw)) body_raw <- rawToChar(body_raw)
    body <- tryCatch(jsonlite::fromJSON(body_raw, simplifyVector = FALSE), error = function(e) e)
    if (inherits(body, "error") || !is.list(body)) {
      return(fail_local("Invalid JSON body.", step = "dowser.request.parse"))
    }

    file_path <- body$file_path %||% NULL
    if (is.null(file_path) || !file.exists(file_path) || isTRUE(file.info(file_path)$isdir)) {
      return(fail_local("file_path is required and must exist on the server.", step = "dowser.request.validate"))
    }
    if (file.access(file_path, 4) != 0) {
      return(fail_local("file_path exists but is not readable.", step = "dowser.request.validate"))
    }

    p <- tryCatch(
      parse_dowser_params(jsonlite::toJSON(body$params %||% list())),
      error = function(e) e
    )
    if (inherits(p, "error")) {
      step <- p$step %||% "dowser.params.parse"
      details <- p$details %||% NULL
      return(fail_local(conditionMessage(p), step = step, details = details))
    }

    add_log("dowser.params.parse", TRUE, sprintf(
      "analysis_mode=%s, tree_build=%s, minseq=%d",
      p$analysis_mode, p$tree_build, p$minseq
    ))

    db_original <- read_airr_from_path(file_path)
    add_log("dowser.input.read", TRUE, sprintf("Loaded %d rows.", nrow(db_original)))

    input_qc <- init_input_qc(db_original, "clone_id", "sequence_id")

    prep <- prepare_db_working(db_original, p)
    db_working <- prep$db_working
    data_provenance <- prep$data_provenance
    warnings <- c(warnings, prep$warnings)
    input_qc$n_rows_after_derived_fields <- nrow(db_working)

    excluded_rows <- integer(0)
    if (identical(p$analysis_mode, "discrete_trait_analysis")) {
      tv <- validate_trait_for_dta(db_working, p$trait_field, exclude_missing = TRUE)
      if (!isTRUE(tv$ok)) {
        return(fail_local(tv$error, step = tv$step))
      }
      if (length(tv$excluded_rows)) {
        excluded_rows <- tv$excluded_rows
        input_qc$excluded_missing_trait <- build_excluded_missing_trait(
          db_working, excluded_rows, p$trait_field, "clone_id", "sequence_id"
        )
        data_provenance$transformations[[length(data_provenance$transformations) + 1]] <- list(
          action = "exclude_missing_trait",
          trait_field = p$trait_field,
          n_excluded = length(excluded_rows)
        )
        db_working <- db_working[-excluded_rows, , drop = FALSE]
        warnings <- c(warnings, sprintf(
          "Excluded %d records with missing trait_field '%s' from DTA.",
          length(excluded_rows), p$trait_field
        ))
      }
      if (identical(p$trait_model, "isotype_irreversible") && identical(p$trait_field, "c_call")) {
        iso_order <- parse_vec(p$isotype_order)
        if (!length(iso_order)) iso_order <- DEFAULT_ISOTYPE_ORDER
        iso <- validate_isotype_states(db_working, p$trait_field, iso_order)
        if (!isTRUE(iso$ok)) {
          return(fail_local(iso$error, step = iso$step, details = iso$details))
        }
      }
    }

    input_qc$n_rows_after_trait_exclusion <- nrow(db_working)
    input_qc$n_clones_after_trait_exclusion <- length(unique(as.character(db_working$clone_id)))

    if (identical(p$analysis_mode, "time_evolution")) {
      tv <- validate_time_field(db_working, p$time_field, p$time_as_numeric)
      if (!isTRUE(tv$ok)) return(fail_local(tv$error, step = tv$step))
      db_working <- tv$db
    }

    validate_sequence_ids_for_mapping(db_working)

    tip_col <- p$tip_color_by
    tc <- prepare_tip_color_column(db_working, tip_col, p$unknown_value)
    db_working <- tc$db
    plot_tip_col <- tc$plot_tip_col
    warnings <- c(warnings, tc$warnings)
    state_overflow <- tc$n_states > p$max_tip_categories

    if (!is.null(plot_tip_col) && nzchar(plot_tip_col)) {
      p$annotation_fields <- unique(c(parse_vec(p$annotation_fields), plot_tip_col))
      p$columns <- unique(c(parse_vec(p$columns), plot_tip_col))
    }

    validate_alignment_presence(db_working)

    clone_consistency <- validate_clone_consistency(
      db_working,
      "clone_id",
      "sequence_alignment",
      "germline_alignment_d_mask",
      "junction_length",
      "v_call",
      "j_call",
      "sequence_id"
    )
    input_qc$length_mismatch <- clone_consistency$length_mismatch
    if (clone_consistency$n_length_mismatch > 0) {
      return(fail_local(
        sprintf("Found %d rows with sequence/germline length mismatch.", clone_consistency$n_length_mismatch),
        step = "dowser.validate.alignment_length",
        details = list(length_mismatch = clone_consistency$length_mismatch)
      ))
    }

    label_check <- validate_label_field_uniqueness(db_working, p$label_field, "sequence_id")
    if (!is.null(label_check$warning)) warnings <- c(warnings, label_check$warning)

    preflight <- preflight_tree_build(p$tree_build, p)
    if (!isTRUE(preflight$ok)) {
      return(fail_local(preflight$error, step = preflight$step %||% "dowser.preflight"))
    }

    if (identical(p$analysis_mode, "discrete_trait_analysis") && is.null(preflight$igphyml)) {
      ig_res <- resolve_igphyml(
        user_exec = p$igphyml_exec %||% Sys.getenv("IGPHYML_BIN", "igphyml"),
        user_motifs = p$igphyml_motifs %||% Sys.getenv("IGPHYML_MOTIFS", ""),
        require_ok = TRUE
      )
      if (!isTRUE(ig_res$ok)) {
        return(fail_local(
          ig_res$error,
          step = ig_res$step %||% "dowser.preflight.igphyml.dta",
          details = ig_res$details %||% NULL
        ))
      }
      preflight$igphyml <- ig_res
    }

    fc <- run_format_clones(db_working, p)
    clones <- fc$clones
    chain_qc <- fc$chain_qc
    if (nrow(clones) == 0) {
      return(fail_local(sprintf("No clones met minseq=%d.", p$minseq), step = "dowser.clones.format"))
    }
    input_qc$n_clones_after_formatClones <- nrow(clones)

    if (identical(p$tree_build, "igphyml")) {
      igv <- validate_igphyml_sequences_after_format_clones(clones)
      if (!isTRUE(igv$ok)) {
        return(fail_local(igv$error, step = igv$step, details = igv$details))
      }
      if (length(igv$warnings %||% character(0))) {
        warnings <- c(warnings, igv$warnings)
      }
      if (length(igv$details %||% list())) {
        input_qc$igphyml_sequence_validity <- igv$details
      }
    }

    data_provenance$transformations[[length(data_provenance$transformations) + 1]] <- list(
      action = "dowser_formatClones",
      collapse = isTRUE(p$collapse_identical_sequences),
      traits = as.list(fc$format_args$traits %||% list()),
      text_fields = as.list(fc$format_args$text_fields %||% list()),
      num_fields = as.list(fc$format_args$num_fields %||% list()),
      columns = as.list(fc$format_args$columns %||% list()),
      minseq = p$minseq,
      mod3 = p$mod3,
      filterstop = p$filterstop,
      use_regions = p$use_regions,
      note = paste(
        "Dowser formatClones may collapse identical sequences unless separated by traits;",
        "text_fields may be concatenated and num_fields may be aggregated according to Dowser behavior."
      )
    )

    add_log("dowser.clones.format", TRUE, sprintf("%d clones formatted.", nrow(clones)))

    tmpdir <- tempfile("dowser_run_")
    dir.create(tmpdir, showWarnings = FALSE)
    # Note: do NOT unlink(tmpdir) on exit — artifact_files in the result point
    # at files under tmpdir, and materialize_artifacts (running in job_runner
    # *after* this handler returns) needs to copy them into the run's
    # artifact dir. The R session's normal tempdir cleanup handles eventual
    # removal when the worker process exits.

    modelfile_info <- NULL
    if (identical(p$analysis_mode, "discrete_trait_analysis")) {
      modelfile_info <- resolve_trait_modelfile(p, tmpdir)
      if (is.null(modelfile_info) && identical(p$trait_model, "isotype_irreversible")) {
        modelfile_info <- build_trait_modelfile(p, tmpdir)
      }
      if (!is.null(modelfile_info)) {
        p$modelfile <- modelfile_info$path
      }
      if (isTRUE(p$collapse_internal_nodes) && !identical(p$tree_build, "igphyml")) {
        p$collapse_internal_nodes <- FALSE
        warnings <- c(warnings, paste(
          "collapse_internal_nodes was disabled for discrete_trait_analysis with",
          sprintf("tree_build='%s'", p$tree_build),
          "because Dowser trait reconstruction can fail during collapseNodes."
        ))
      }
    } else if (!is.null(p$modelfile) || !is.null(p$modelfile_text)) {
      warnings <- c(warnings, "Custom trait model file is ignored unless analysis_mode is discrete_trait_analysis.")
    }

    tb <- run_get_trees(clones, p, preflight, tmpdir, basename(tmpdir))
    trees_tbl <- tb$trees_tbl
    add_log("dowser.trees.build", TRUE, sprintf("Built %d trees with %s.", length(trees_tbl$trees), p$tree_build))

    tree_out <- build_tree_outputs(trees_tbl, db_working, p, label_check)
    trees_detail <- tree_out$trees_detail
    trees_tbl <- tree_out$trees_tbl
    if (length(tree_out$node_warnings)) warnings <- c(warnings, tree_out$node_warnings)

    annos <- build_annotations(trees_tbl, db_working, p, tip_col, plot_tip_col)

    figures_dir <- file.path(tmpdir, "figures")
    dir.create(figures_dir, recursive = TRUE, showWarnings = FALSE)
    fig <- render_tree_figures(
      trees_tbl, p, plot_tip_col, state_overflow, tip_col,
      db = db_working, clones = clones,
      figures_out_dir = figures_dir
    )
    if (!is.null(fig$warnings)) warnings <- c(warnings, fig$warnings)

    discrete_trait_analysis <- NULL
    if (identical(p$analysis_mode, "discrete_trait_analysis")) {
      discrete_trait_analysis <- run_dta_analysis(
        clones, trees_tbl, p,
        modelfile_info$path %||% NULL,
        preflight
      )
      add_log("dowser.dta", TRUE, "Discrete trait analysis complete.")
    }

    time_evolution <- NULL
    if (identical(p$analysis_mode, "time_evolution")) {
      time_evolution <- run_time_evolution(trees_tbl, p, db_working)
      add_log("dowser.time_evolution", TRUE, "Time evolution analysis complete.")
    }

    igphyml_out <- NULL
    if (identical(p$tree_build, "igphyml") && isTRUE(p$return_igphyml_parameters)) {
      igphyml_out <- extract_igphyml_metadata(trees_tbl, preflight, p)
    }

    clones_meta <- list(
      clone_id = unname(as.list(as.character(clones$clone_id))),
      seqs = unname(as.list(as.integer(clones$seqs)))
    )

    requested_part <- p$partition_model %||% "single"
    effective_part <- if (identical(p$tree_build, "igphyml")) requested_part else "single"
    partition_supported <- identical(p$tree_build, "igphyml") &&
      requested_part %in% PARTITION_MODEL_ENUM
    partition_output_detected <- any(c("partition", "parameters") %in% names(trees_tbl))

    stats <- list(
      n_clones = length(unique(db_working$clone_id)),
      n_trees = length(trees_tbl$trees),
      total_seqs = nrow(db_working),
      analysis_mode = p$analysis_mode,
      tree_build = p$tree_build,
      seed = p$seed,
      label_field = p$label_field,
      tip_color_by = tip_col,
      tip_size_by = p$tip_size_by,
      unknown_value = p$unknown_value,
      unknown_replaced_in_input = tc$unknown_replaced,
      n_tip_states = tc$n_states,
      tip_states_capped = state_overflow,
      canonical_ids = "sequence_id",
      requested_partition_model = requested_part,
      effective_partition_model = effective_part,
      partition_model_supported = partition_supported,
      partition_model_output_detected = partition_output_detected
    )

    export_dir <- file.path(tmpdir, "exports")
    artifacts <- build_export_bundle(export_dir, list(
      trees_detail = trees_detail,
      input_qc = input_qc,
      data_provenance = data_provenance,
      discrete_trait_analysis = discrete_trait_analysis,
      igphyml = igphyml_out,
      figure_paths = fig$figure_paths,
      trees_tbl = trees_tbl
    ), p)

    artifact_zip <- zip_export_bundle(export_dir)

    # Build the artifact_files descriptor list — file paths only, no base64.
    # materialize_artifacts (job_runner.R) copies these into the run's
    # artifact staging dir and the API worker uploads them to object storage.
    artifact_files <- list()
    if (!is.null(fig$figure_paths) && length(fig$figure_paths)) {
      for (i in seq_along(fig$figure_paths)) {
        fp <- fig$figure_paths[[i]]
        if (is.null(fp) || !nzchar(fp) || !file.exists(fp)) next
        artifact_files[[length(artifact_files) + 1L]] <- list(
          path = fp,
          filename = sprintf("phylogeny_%d.png", i),
          kind = "image",
          role = "phylogeny",
          content_type = "image/png",
          previewable = TRUE,
          tree_index = i - 1L
        )
      }
    }
    if (!is.null(artifact_zip$path) && file.exists(artifact_zip$path)) {
      artifact_files[[length(artifact_files) + 1L]] <- list(
        path = artifact_zip$path,
        filename = artifact_zip$name %||% "dowser_artifacts.zip",
        kind = "zip",
        role = "clone_bundle_zip",
        content_type = "application/zip",
        previewable = FALSE
      )
    }

    if (!is.null(tip_col) && tc$unknown_replaced > 0) {
      warnings <- c(warnings, sprintf(
        "Column '%s' had %d empty values filled with '%s' in plot-only column '%s'.",
        tip_col, tc$unknown_replaced, p$unknown_value, plot_tip_col
      ))
    }
    if (state_overflow) {
      warnings <- c(warnings, sprintf(
        "Column '%s' has %d unique values (> max_tip_categories=%d). Plotted without tip coloring.",
        tip_col, tc$n_states, p$max_tip_categories
      ))
    }

    legacy_newicks <- vapply(trees_detail, function(x) x$canonical_newick, character(1))

    result <- prepare_dowser_result(list(
      ok = TRUE,
      trees = unname(legacy_newicks),
      trees_detail = trees_detail,
      clones = clones_meta,
      annotations = annos,
      figures = NULL,
      stats = stats,
      input_qc = input_qc,
      data_provenance = data_provenance,
      discrete_trait_analysis = discrete_trait_analysis,
      time_evolution = time_evolution,
      igphyml = igphyml_out,
      chain_qc = chain_qc,
      artifacts = artifacts,
      artifact_files = artifact_files,
      artifact_name = artifact_zip$name %||% "dowser_artifacts.zip",
      warnings = as.list(as.character(unique(warnings))),
      logs = logs,
      render = fig$render
    ))

    if (!validate_dowser_result_contract(result, RESULT_SCHEMA_PATH)) {
      return(fail_local("Result failed contract validation.", status = 500, step = "dowser.contract.validate"))
    }

    add_log("dowser.contract.validate", TRUE, "Result validated.")
    result
  }, error = function(e) {
    logf("[dowser][ERROR] %s", conditionMessage(e))
    step <- e$step %||% "dowser.unhandled"
    details <- e$details %||% NULL
    status_code <- if (inherits(e, "dowser_validation")) 400 else 500
    fail_local(conditionMessage(e), status = status_code, step = step, details = details)
  })
}
