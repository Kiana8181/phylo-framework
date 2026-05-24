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
  any(vapply(data_col, function(d) {
    df <- meta_data_frame(d)
    is.data.frame(df) && col %in% names(df)
  }, logical(1)))
}

plot_col_is_plottable <- function(trees_tbl, col) {
  if (!plot_col_in_trees(trees_tbl, col)) return(FALSE)
  data_col <- trees_tbl$data
  if (is.null(data_col) || !length(data_col)) return(FALSE)
  all(vapply(data_col, function(d) {
    df <- meta_data_frame(d)
    if (!is.data.frame(df) || !col %in% names(df)) return(FALSE)
    vals <- df[[col]]
    if (is.null(vals)) return(FALSE)
    coerced <- tryCatch(as.character(vals), error = function(e) NULL)
    !is.null(coerced) && length(coerced) == length(vals)
  }, logical(1)))
}

is_airr_clone <- function(x) {
  inherits(x, "airrClone")
}

meta_data_frame <- function(meta) {
  if (is.null(meta)) return(NULL)
  if (is_airr_clone(meta)) {
    df <- slot(meta, "data")
    if (is.data.frame(df)) return(df)
    return(NULL)
  }
  if (inherits(meta, "data.frame")) return(meta)
  NULL
}

set_meta_data_frame <- function(meta, df) {
  if (is_airr_clone(meta)) {
    slot(meta, "data") <- df
    return(meta)
  }
  if (inherits(meta, "data.frame")) return(df)
  meta
}

trees_support_node_coloring <- function(trees_tbl) {
  if (is.null(trees_tbl$trees) || !length(trees_tbl$trees)) return(FALSE)
  all(vapply(trees_tbl$trees, function(phy) {
    if (is.null(phy)) return(FALSE)
    if ("treedata" %in% class(phy)) return(TRUE)
    if (!is.null(phy$pars_recon) && "state" %in% names(phy)) {
      st <- phy$state
      return(!is.null(st) && (is.character(st) || is.factor(st)))
    }
    FALSE
  }, logical(1)))
}

resolve_plot_tipsize <- function(p, staging_tbl) {
  size_by <- p$tip_size_by %||% NULL
  if (is.character(size_by) && length(size_by) == 1 && nzchar(trimws(size_by))) {
    col <- trimws(size_by)
    if (plot_col_in_trees(staging_tbl, col)) return(col)
  }
  tipsize <- as.numeric(p$tipsize %||% 2)[1]
  if (!is.finite(tipsize)) 2 else tipsize
}

clone_row_metadata <- function(clones, clone_id) {
  if (is.null(clones) || !is.data.frame(clones) || !nrow(clones)) return(NULL)
  if (!"clone_id" %in% names(clones) || !"data" %in% names(clones)) return(NULL)
  idx <- match(as.character(clone_id), as.character(clones$clone_id))
  if (is.na(idx)) return(NULL)
  meta <- clones$data[[idx]]
  if (is_airr_clone(meta) || inherits(meta, "data.frame")) meta else NULL
}

assign_tip_color_column <- function(meta, tip_col, tips, color_vals, id_col = "sequence_id") {
  if (!inherits(meta, "data.frame")) return(NULL)
  if (id_col %in% names(meta)) {
    idx <- match(as.character(meta[[id_col]]), tips)
    meta[[tip_col]] <- ifelse(is.na(idx), "Germline", color_vals[idx])
  } else if (nrow(meta) == length(color_vals)) {
    meta[[tip_col]] <- color_vals
  } else {
    return(NULL)
  }
  meta
}

inject_plot_metadata_from_db <- function(staging_tbl, db, tip_col, plot_tip_col = NULL, id_col = "sequence_id", clones = NULL) {
  if (is.null(staging_tbl) || !nrow(staging_tbl) || is.null(db) || !is.data.frame(db) || !nrow(db)) {
    return(staging_tbl)
  }
  if (is.null(tip_col) || !nzchar(tip_col)) return(staging_tbl)
  if (!id_col %in% names(db)) return(staging_tbl)

  color_col <- if (!is.null(plot_tip_col) && nzchar(plot_tip_col) && plot_tip_col %in% names(db)) {
    plot_tip_col
  } else if (tip_col %in% names(db)) {
    tip_col
  } else {
    return(staging_tbl)
  }

  clone_ids <- if ("clone_id" %in% names(staging_tbl)) {
    as.character(staging_tbl$clone_id)
  } else {
    rep(NA_character_, nrow(staging_tbl))
  }

  if (!length(staging_tbl$trees)) return(staging_tbl)

  if (is.null(staging_tbl$data)) {
    staging_tbl$data <- vector("list", nrow(staging_tbl))
  }

  for (i in seq_len(nrow(staging_tbl))) {
    phy <- staging_tbl$trees[[i]]
    if (is.null(phy) || is.null(phy$tip.label)) next

    tips <- as.character(phy$tip.label)
    db_sub <- db
    cid <- clone_ids[[i]]
    if (!is.na(cid) && nzchar(cid) && "clone_id" %in% names(db)) {
      db_sub <- db[as.character(db$clone_id) == cid, , drop = FALSE]
    }
    if (!nrow(db_sub)) db_sub <- db

    jj <- match(tips, as.character(db_sub[[id_col]]))
    color_vals <- ifelse(
      is.na(jj),
      "Germline",
      as.character(db_sub[[color_col]][jj])
    )

    meta <- staging_tbl$data[[i]]
    meta_df <- meta_data_frame(meta)

    if (is.null(meta_df)) {
      fallback <- clone_row_metadata(clones, cid)
      if (!is.null(fallback)) {
        meta <- fallback
        meta_df <- meta_data_frame(meta)
      }
    } else if (!id_col %in% names(meta_df)) {
      fallback <- clone_row_metadata(clones, cid)
      fallback_df <- meta_data_frame(fallback)
      if (!is.null(fallback_df)) {
        meta <- fallback
        meta_df <- fallback_df
      }
    }

    if (is.null(meta_df)) {
      next
    }

    updated_df <- assign_tip_color_column(meta_df, tip_col, tips, color_vals, id_col)
    if (is.null(updated_df)) {
      next
    }

    staging_tbl$data[[i]] <- set_meta_data_frame(meta, updated_df)
  }

  staging_tbl
}

prepare_trees_tbl_for_plot <- function(trees_tbl, tip_col = NULL, plot_tip_col = NULL, db = NULL, clones = NULL) {
  if (is.null(trees_tbl) || !nrow(trees_tbl)) {
    return(list(tbl = trees_tbl, tips_field = NULL, rehydrated = FALSE))
  }

  staging <- trees_tbl
  if (requireNamespace("tibble", quietly = TRUE) && is.data.frame(staging)) {
    staging <- tibble::as_tibble(staging)
  }
  tips_field <- NULL
  rehydrated <- FALSE

  if (!is.null(staging$trees) && length(staging$trees)) {
    staging$trees <- lapply(staging$trees, function(phy) {
      if (is.null(phy)) return(phy)
      if (!is.null(phy$tip.label)) phy$tip.label <- as.character(phy$tip.label)
      phy
    })
  }

  if (!is.null(staging$data) && length(staging$data)) {
    staging$data <- lapply(staging$data, function(meta) {
      df <- meta_data_frame(meta)
      if (is.null(df)) return(meta)
      if (!is.null(plot_tip_col) && nzchar(plot_tip_col) && plot_tip_col %in% names(df)) {
        df[[plot_tip_col]] <- as.character(df[[plot_tip_col]])
      }
      if (!is.null(tip_col) && nzchar(tip_col) && tip_col %in% names(df)) {
        if (!is.null(plot_tip_col) && nzchar(plot_tip_col) && plot_tip_col %in% names(df)) {
          df[[tip_col]] <- as.character(df[[plot_tip_col]])
        } else {
          df[[tip_col]] <- as.character(df[[tip_col]])
        }
      }
      set_meta_data_frame(meta, df)
    })
  }

  if (!is.null(tip_col) && nzchar(tip_col) && plot_col_is_plottable(staging, tip_col)) {
    tips_field <- tip_col
  } else if (!is.null(plot_tip_col) && nzchar(plot_tip_col)) {
    stripped <- sub("^\\.plot_", "", plot_tip_col)
    if (nzchar(stripped) && !identical(stripped, plot_tip_col) && plot_col_is_plottable(staging, stripped)) {
      tips_field <- stripped
    } else if (plot_col_is_plottable(staging, plot_tip_col)) {
      tips_field <- plot_tip_col
    }
  }

  if (is.null(tips_field) && !is.null(db) && is.data.frame(db) && nrow(db) > 0 &&
      !is.null(tip_col) && nzchar(tip_col)) {
    staging <- inject_plot_metadata_from_db(staging, db, tip_col, plot_tip_col, clones = clones)
    if (plot_col_is_plottable(staging, tip_col)) {
      tips_field <- tip_col
      rehydrated <- TRUE
    }
  }

  list(tbl = staging, tips_field = tips_field, rehydrated = rehydrated)
}

render_tree_figures <- function(trees_tbl, p, plot_tip_col, state_overflow, tip_col = NULL, db = NULL, clones = NULL) {
  if (!requireNamespace("ggtree", quietly = TRUE) || !requireNamespace("ggplot2", quietly = TRUE)) {
    return(list(figures_b64 = NULL, render = NULL, warnings = "ggtree/ggplot2 not available; no PNG previews."))
  }

  render_warnings <- character(0)
  prepared <- prepare_trees_tbl_for_plot(trees_tbl, tip_col, plot_tip_col, db = db, clones = clones)
  staging_tbl <- prepared$tbl
  plot_tips <- if (isTRUE(state_overflow)) NULL else prepared$tips_field

  if (isTRUE(prepared$rehydrated)) {
    render_warnings <- c(
      render_warnings,
      "Tip coloring column rehydrated from input data for Method Output PNG (column not retained in getTrees output)."
    )
  }

  if (!is.null(plot_tip_col) && nzchar(plot_tip_col) && !state_overflow && is.null(plot_tips)) {
    src_col <- tip_col %||% sub("^\\.plot_", "", plot_tip_col)
    render_warnings <- c(
      render_warnings,
      sprintf(
        "Tip coloring was requested using '%s', but no plottable metadata column was found after formatClones. Tree was rendered without tip coloring.",
        src_col
      )
    )
  }

  show_node_nums <- isTRUE(p$show_node_numbers %||% FALSE)
  internal_seqs_requested <- isTRUE(p$return_internal_sequences %||% FALSE) ||
    identical(p$analysis_mode, "tree_with_internal_sequences")
  show_node_coloring <- internal_seqs_requested && trees_support_node_coloring(staging_tbl)

  if (internal_seqs_requested && !show_node_coloring) {
    render_warnings <- c(
      render_warnings,
      "Internal node trait coloring skipped in Method Output PNG (requires discrete trait reconstruction). Tip colors are still applied; use the Lineage tab for internal node sequences."
    )
  }

  if (internal_seqs_requested && exists("safe_get_all_seqs", mode = "function")) {
    if (is.null(safe_get_all_seqs(staging_tbl))) {
      render_warnings <- c(
        render_warnings,
        "Internal node sequence reconstruction unavailable (getAllSeqs failed); use Lineage tab when available."
      )
    }
  }

  plot_tipsize <- resolve_plot_tipsize(p, staging_tbl)

  call_plot_trees <- function(tbl, use_tips, use_nodes, use_node_nums) {
    args <- list(
      trees = tbl,
      tipsize = plot_tipsize,
      nodes = use_nodes,
      node_nums = use_node_nums
    )
    if (!is.null(use_tips) && is.character(use_tips) && length(use_tips) == 1 && nzchar(use_tips)) {
      args$tips <- use_tips
    }
    do.call(dowser::plotTrees, args)
  }

  attempts <- list()
  if (!is.null(plot_tips) && show_node_coloring) {
    attempts[[length(attempts) + 1]] <- list(
      tips = plot_tips, nodes = TRUE, node_nums = show_node_nums, label = "colored_nodes"
    )
  }
  if (!is.null(plot_tips)) {
    attempts[[length(attempts) + 1]] <- list(
      tips = plot_tips, nodes = FALSE, node_nums = show_node_nums, label = "colored_no_nodes"
    )
  }
  attempts[[length(attempts) + 1]] <- list(
    tips = NULL, nodes = FALSE, node_nums = show_node_nums, label = "uncolored_plain"
  )

  plots <- NULL
  render_mode <- NULL
  for (attempt in attempts) {
    plots <- tryCatch(
      call_plot_trees(staging_tbl, attempt$tips, attempt$nodes, attempt$node_nums),
      error = function(e) {
        if (identical(attempt$label, "colored_nodes") && !is.null(plot_tips)) {
          render_warnings <<- c(
            render_warnings,
            sprintf(
              "plotTrees failed with tips='%s' and internal nodes: %s. Retrying without internal node labels.",
              plot_tips, conditionMessage(e)
            )
          )
        } else if (identical(attempt$label, "colored_no_nodes") && !is.null(plot_tips)) {
          render_warnings <<- c(
            render_warnings,
            sprintf(
              "plotTrees failed with tips='%s': %s. Retrying without tip coloring.",
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
    if (!is.null(plots)) {
      render_mode <- attempt$label
      break
    }
  }

  if (is.null(plots)) {
    return(list(
      figures_b64 = NULL,
      render = paste0("plotTrees_uncolored_tipsize", plot_tipsize),
      warnings = if (length(render_warnings)) render_warnings else NULL
    ))
  }

  figures_b64 <- lapply(plots, encode_png)
  render <- switch(
    render_mode,
    colored_nodes = paste0("plotTrees_", plot_tips, "_nodes_tipsize", plot_tipsize),
    colored_no_nodes = paste0("plotTrees_", plot_tips, "_tipsize", plot_tipsize),
    paste0("plotTrees_uncolored_tipsize", plot_tipsize)
  )

  list(
    figures_b64 = figures_b64,
    render = render,
    warnings = if (length(render_warnings)) render_warnings else NULL
  )
}

zip_export_bundle <- function(export_dir, zip_name = "dowser_artifacts.zip") {
  all_files <- list.files(export_dir, recursive = TRUE, full.names = TRUE)
  all_files <- all_files[basename(all_files) != zip_name]
  if (!length(all_files)) {
    return(list(b64 = NULL, name = NULL))
  }

  zip_path <- file.path(export_dir, zip_name)
  if (file.exists(zip_path)) file.remove(zip_path)

  old_wd <- getwd()
  setwd(export_dir)
  on.exit(setwd(old_wd), add = TRUE)

  rel_paths <- unique(sub(paste0("^", export_dir, "/?"), "", all_files, fixed = FALSE))
  rel_paths <- rel_paths[nzchar(rel_paths)]
  if (!length(rel_paths)) {
    return(list(b64 = NULL, name = NULL))
  }

  utils::zip(zipfile = zip_path, files = rel_paths)
  sz <- file.info(zip_path)$size
  if (is.na(sz) || sz <= 0) {
    return(list(b64 = NULL, name = NULL))
  }

  zip_raw <- readBin(zip_path, what = "raw", n = sz)
  list(b64 = jsonlite::base64_enc(zip_raw), name = zip_name)
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
