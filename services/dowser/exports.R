# Export bundle and visualization helpers.

encode_png <- function(plot, width = 900, height = 520, dpi = 100) {
  tf <- tempfile(fileext = ".png")
  on.exit(if (file.exists(tf)) unlink(tf), add = TRUE)
  ggplot2::ggsave(tf, plot = plot, width = width / 100, height = height / 100, dpi = dpi, bg = "white")
  jsonlite::base64_enc(readBin(tf, "raw", n = file.info(tf)$size))
}

write_json_file <- function(obj, path) {
  jsonlite::write_json(obj, path, auto_unbox = TRUE, null = "null", pretty = TRUE)
}

write_tsv_file <- function(df, path) {
  if (is.null(df) || !is.data.frame(df) || !nrow(df)) {
    return(invisible(NULL))
  }
  readr::write_tsv(df, path)
}

add_artifact_if_exists <- function(artifacts, out_dir, name, rel_path, kind) {
  full_path <- file.path(out_dir, rel_path)
  if (file.exists(full_path) && file.info(full_path)$size >= 0) {
    artifacts[[length(artifacts) + 1]] <- list(
      name = name,
      path = rel_path,
      kind = kind
    )
  }
  artifacts
}

flatten_nodes_df <- function(trees_detail) {
  rows <- list()
  for (tr in trees_detail) {
    if (!length(tr$nodes)) next
    for (nd in tr$nodes) {
      rows[[length(rows) + 1]] <- data.frame(
        clone_id = nd$clone_id,
        node = nd$node,
        node_id = nd$node_id,
        sequence = nd$sequence,
        sequence_alignment = nd$sequence_alignment,
        locus = nd$locus,
        is_internal = nd$is_internal,
        is_observed = nd$is_observed,
        branch_length = nd$branch_length,
        trait_state = nd$trait_state %||% NA_character_,
        stringsAsFactors = FALSE
      )
    }
  }
  if (!length(rows)) return(data.frame())
  do.call(rbind, rows)
}

flatten_all_sequences_df <- function(trees_detail) {
  rows <- list()
  for (tr in trees_detail) {
    for (seq in tr$all_sequences %||% list()) {
      rows[[length(rows) + 1]] <- data.frame(
        clone_id = seq$clone_id %||% tr$clone_id,
        node_id = seq$node_id %||% NA_character_,
        node = seq$node %||% NA_integer_,
        locus = seq$locus %||% NA_character_,
        sequence = seq$sequence %||% "",
        sequence_alignment = seq$sequence_alignment %||% seq$sequence %||% "",
        stringsAsFactors = FALSE
      )
    }
  }
  if (!length(rows)) return(data.frame())
  do.call(rbind, rows)
}

plot_col_in_trees <- function(trees_tbl, col) {
  if (is.null(col) || !nzchar(col)) return(FALSE)
  if (col %in% names(trees_tbl)) return(TRUE)
  data_col <- trees_tbl$data
  if (is.null(data_col) || !length(data_col)) return(FALSE)
  any(vapply(data_col, function(d) is.data.frame(d) && col %in% names(d), logical(1)))
}

render_tree_figures <- function(trees_tbl, p, plot_tip_col, state_overflow, tip_col = NULL) {
  if (!requireNamespace("ggtree", quietly = TRUE) || !requireNamespace("ggplot2", quietly = TRUE)) {
    return(list(figures_b64 = NULL, render = NULL, warnings = "ggtree/ggplot2 not available; no PNG previews."))
  }

  render_warnings <- character(0)
  plot_tips <- NULL
  if (!is.null(plot_tip_col) && nzchar(plot_tip_col) && !state_overflow) {
    if (plot_col_in_trees(trees_tbl, plot_tip_col)) {
      plot_tips <- plot_tip_col
    } else {
      src_col <- tip_col %||% sub("^\\.plot_", "", plot_tip_col)
      render_warnings <- c(
        render_warnings,
        sprintf(
          "Tip coloring was requested using '%s', but the generated plot-only column '%s' was not present after formatClones. Tree was rendered without tip coloring.",
          src_col, plot_tip_col
        )
      )
    }
  }

  show_nodes <- isTRUE(p$show_node_numbers %||% FALSE) ||
    identical(p$analysis_mode, "tree_with_internal_sequences")

  plots <- tryCatch(
    dowser::plotTrees(
      trees_tbl,
      tips = plot_tips,
      tipsize = as.numeric(p$tipsize %||% 2),
      nodes = show_nodes,
      node_nums = show_nodes
    ),
    error = function(e) {
      if (!is.null(plot_tips)) {
        render_warnings <<- c(
          render_warnings,
          sprintf(
            "plotTrees failed with tips='%s': %s. Tree was rendered without tip coloring.",
            plot_tips, conditionMessage(e)
          )
        )
      } else {
        render_warnings <<- c(
          render_warnings,
          sprintf("plotTrees failed: %s. No PNG previews generated.", conditionMessage(e))
        )
      }
      NULL
    }
  )

  if (is.null(plots)) {
    return(list(
      figures_b64 = NULL,
      render = paste0("plotTrees_uncolored_tipsize", p$tipsize),
      warnings = if (length(render_warnings)) render_warnings else NULL
    ))
  }

  figures_b64 <- lapply(plots, encode_png)
  render <- if (is.null(plot_tips)) {
    paste0("plotTrees_uncolored_tipsize", p$tipsize)
  } else {
    paste0("plotTrees_", plot_tips, "_tipsize", p$tipsize)
  }

  list(
    figures_b64 = figures_b64,
    render = render,
    warnings = if (length(render_warnings)) render_warnings else NULL
  )
}

build_export_bundle <- function(out_dir, result_parts, p) {
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
  artifacts <- list()

  write_json_file(result_parts$input_qc, file.path(out_dir, "input_qc.json"))
  artifacts <- add_artifact_if_exists(artifacts, out_dir, "input_qc.json", "input_qc.json", "json")

  write_json_file(result_parts$data_provenance, file.path(out_dir, "data_provenance.json"))
  artifacts <- add_artifact_if_exists(artifacts, out_dir, "data_provenance.json", "data_provenance.json", "json")

  run_meta <- list(
    analysis_mode = p$analysis_mode,
    tree_build = p$tree_build,
    timestamp = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
  )
  write_json_file(run_meta, file.path(out_dir, "run_metadata.json"))
  artifacts <- add_artifact_if_exists(artifacts, out_dir, "run_metadata.json", "run_metadata.json", "json")

  trees_detail <- result_parts$trees_detail %||% list()
  canonical <- vapply(trees_detail, function(x) x$canonical_newick %||% "", character(1))
  writeLines(canonical, file.path(out_dir, "canonical_newick.nwk"))
  artifacts <- add_artifact_if_exists(artifacts, out_dir, "canonical_newick.nwk", "canonical_newick.nwk", "newick")

  display <- vapply(trees_detail, function(x) x$display_newick %||% "", character(1))
  if (any(nzchar(display))) {
    writeLines(display, file.path(out_dir, "display_newick.nwk"))
    artifacts <- add_artifact_if_exists(artifacts, out_dir, "display_newick.nwk", "display_newick.nwk", "newick")
  }

  nodes_df <- flatten_nodes_df(trees_detail)
  if (nrow(nodes_df)) {
    write_tsv_file(nodes_df, file.path(out_dir, "lineage_nodes.tsv"))
    write_json_file(jsonlite::fromJSON(jsonlite::toJSON(nodes_df, dataframe = "rows")), file.path(out_dir, "lineage_nodes.json"))
    internal <- nodes_df[nodes_df$is_internal %in% TRUE, , drop = FALSE]
    write_tsv_file(internal, file.path(out_dir, "internal_sequences.tsv"))
    write_json_file(jsonlite::fromJSON(jsonlite::toJSON(internal, dataframe = "rows")), file.path(out_dir, "internal_sequences.json"))
    artifacts <- add_artifact_if_exists(artifacts, out_dir, "lineage_nodes.tsv", "lineage_nodes.tsv", "tsv")
    artifacts <- add_artifact_if_exists(artifacts, out_dir, "internal_sequences.tsv", "internal_sequences.tsv", "tsv")
  }

  all_df <- flatten_all_sequences_df(trees_detail)
  if (nrow(all_df)) {
    write_tsv_file(all_df, file.path(out_dir, "all_sequences.tsv"))
    write_json_file(jsonlite::fromJSON(jsonlite::toJSON(all_df, dataframe = "rows")), file.path(out_dir, "all_sequences.json"))
    artifacts <- add_artifact_if_exists(artifacts, out_dir, "all_sequences.tsv", "all_sequences.tsv", "tsv")
    if (isTRUE(p$export_all_sequences_fasta %||% FALSE) && exists("dfToFasta", where = asNamespace("dowser"))) {
      fasta_path <- file.path(out_dir, "all_sequences.fasta")
      tryCatch(dowser::dfToFasta(all_df, fasta_path), error = function(e) NULL)
      artifacts <- add_artifact_if_exists(artifacts, out_dir, "all_sequences.fasta", "all_sequences.fasta", "fasta")
    }
  }

  dta <- result_parts$discrete_trait_analysis
  if (!is.null(dta)) {
    if (length(dta$switches)) write_json_file(dta$switches, file.path(out_dir, "switches.json"))
    if (length(dta$ps$summary)) write_json_file(dta$ps$summary, file.path(out_dir, "ps_results.json"))
    if (length(dta$sp$summary)) write_json_file(dta$sp$summary, file.path(out_dir, "sp_results.json"))
    if (length(dta$sc$summary)) write_json_file(dta$sc$summary, file.path(out_dir, "sc_results.json"))
    artifacts <- add_artifact_if_exists(artifacts, out_dir, "switches.json", "switches.json", "json")
    artifacts <- add_artifact_if_exists(artifacts, out_dir, "ps_results.json", "ps_results.json", "json")
    artifacts <- add_artifact_if_exists(artifacts, out_dir, "sp_results.json", "sp_results.json", "json")
    artifacts <- add_artifact_if_exists(artifacts, out_dir, "sc_results.json", "sc_results.json", "json")
  }

  ig <- result_parts$igphyml
  if (!is.null(ig)) {
    write_json_file(ig, file.path(out_dir, "igphyml_parameters.json"))
    artifacts <- add_artifact_if_exists(artifacts, out_dir, "igphyml_parameters.json", "igphyml_parameters.json", "json")
  }

  if (!is.null(result_parts$figures_b64) && length(result_parts$figures_b64)) {
    for (i in seq_along(result_parts$figures_b64)) {
      png_path <- file.path(out_dir, sprintf("tree_plot_%02d.png", i))
      raw <- jsonlite::base64_dec(result_parts$figures_b64[[i]])
      writeBin(raw, png_path)
    }
    artifacts <- add_artifact_if_exists(artifacts, out_dir, "tree_plot.png", "tree_plot_01.png", "png")
  }

  if (exists("treesToPDF", where = asNamespace("dowser")) && !is.null(result_parts$trees_tbl)) {
    pdf_path <- file.path(out_dir, "tree_plot.pdf")
    tryCatch(dowser::treesToPDF(result_parts$trees_tbl, file = pdf_path), error = function(e) NULL)
    artifacts <- add_artifact_if_exists(artifacts, out_dir, "tree_plot.pdf", "tree_plot.pdf", "pdf")
  }

  artifacts
}
