# Export bundle and visualization helpers.

save_png_file <- function(plot, path, width = 900, height = 520, dpi = 100) {
  ggplot2::ggsave(
    path, plot = plot,
    width = width / 100, height = height / 100, dpi = dpi, bg = "white"
  )
  path
}

write_json_file <- function(obj, path) {
  jsonlite::write_json(obj, path, auto_unbox = TRUE, null = "null", pretty = TRUE)
}

serialize_dowser_result <- function(result) {
  jsonlite::toJSON(prepare_dowser_result(result), auto_unbox = TRUE, null = "null", na = "null")
}

preserve_json_array <- function(x) {
  if (is.null(x)) return(NULL)
  I(x)
}

ensure_json_object <- function(x) {
  if (is.null(x)) return(NULL)
  if (is.list(x) && (is.null(names(x)) || !length(names(x)))) {
    return(structure(list(), names = character(0)))
  }
  x
}

prepare_dowser_result <- function(result) {
  if (!is.null(result$trees)) {
    result$trees <- preserve_json_array(unname(result$trees))
  }
  if (!is.null(result$clones) && is.list(result$clones)) {
    if (!is.null(result$clones$clone_id)) {
      result$clones$clone_id <- preserve_json_array(unname(as.list(result$clones$clone_id)))
    }
    if (!is.null(result$clones$seqs)) {
      result$clones$seqs <- preserve_json_array(unname(as.list(result$clones$seqs)))
    }
  }
  if (!is.null(result$annotations)) {
    result$annotations <- preserve_json_array(result$annotations)
  }
  if (!is.null(result$trees_detail)) {
    result$trees_detail <- preserve_json_array(result$trees_detail)
  }
  if (!is.null(result$figures) && is.list(result$figures) && !is.null(result$figures$phylogeny)) {
    result$figures$phylogeny <- preserve_json_array(unname(result$figures$phylogeny))
  }
  if (!is.null(result$warnings)) {
    result$warnings <- preserve_json_array(result$warnings)
  }
  if (!is.null(result$artifacts)) {
    result$artifacts <- preserve_json_array(result$artifacts)
  }
  if (!is.null(result$artifact_files)) {
    result$artifact_files <- preserve_json_array(unname(result$artifact_files))
  }
  if (!is.null(result$logs)) {
    result$logs <- preserve_json_array(result$logs)
  }
  if (!is.null(result$input_qc)) {
    result$input_qc <- ensure_json_object(result$input_qc)
  }
  if (!is.null(result$data_provenance)) {
    result$data_provenance <- ensure_json_object(result$data_provenance)
  }
  result
}

validate_dowser_result_contract <- function(result, schema_path) {
  if (is.null(schema_path) || !nzchar(schema_path) || !file.exists(schema_path)) {
    return(FALSE)
  }
  jsonvalidate::json_validate(
    serialize_dowser_result(result),
    schema_path,
    verbose = TRUE
  )
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

# Returns TRUE only when, for every tree in the staging table, the metadata
# data.frame has at least one row per node (tips + internals). plotTrees(nodes=TRUE)
# joins ggtree's combined (tip + internal) node table to the colour-aesthetic
# column; if the column only covers tips, ggtree raises
# "Aesthetics must be either length 1 or the same as the data (<ntips>)".
tree_supports_node_color_aesthetic <- function(trees_tbl) {
  if (is.null(trees_tbl$trees) || !length(trees_tbl$trees)) return(FALSE)
  if (is.null(trees_tbl$data) || !length(trees_tbl$data)) return(FALSE)
  n <- length(trees_tbl$trees)
  if (length(trees_tbl$data) != n) return(FALSE)
  for (i in seq_len(n)) {
    phy <- trees_tbl$trees[[i]]
    if (is.null(phy) || is.null(phy$tip.label)) return(FALSE)
    meta_df <- meta_data_frame(trees_tbl$data[[i]])
    if (is.null(meta_df)) return(FALSE)
    needed <- length(phy$tip.label) + (phy$Nnode %||% 0L)
    if (nrow(meta_df) < needed) return(FALSE)
  }
  TRUE
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

render_tree_figures <- function(trees_tbl, p, plot_tip_col, state_overflow, tip_col = NULL, db = NULL, clones = NULL, figures_out_dir = NULL) {
  if (!requireNamespace("ggtree", quietly = TRUE) || !requireNamespace("ggplot2", quietly = TRUE)) {
    return(list(figure_paths = character(0), render = NULL, warnings = "ggtree/ggplot2 not available; no PNG previews."))
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
  node_color_reconstruction_ok <- trees_support_node_coloring(staging_tbl)
  # Even when Dowser produced a node-state reconstruction, the staging
  # metadata data.frame may only cover tips (e.g. PML + discrete_trait_analysis).
  # In that case ggtree's colour aesthetic length wouldn't match the joined
  # tip+internal node table, so skip the colored_nodes plotTrees attempt.
  node_color_data_ok <- tree_supports_node_color_aesthetic(staging_tbl)
  show_node_coloring <- internal_seqs_requested &&
    node_color_reconstruction_ok && node_color_data_ok

  if (internal_seqs_requested && !show_node_coloring) {
    msg <- if (!node_color_reconstruction_ok) {
      "Internal node trait coloring skipped in Method Output PNG (requires discrete trait reconstruction). Tip colors are still applied; use the Lineage tab for internal node sequences."
    } else {
      # Reconstruction succeeded but the per-node metadata isn't shaped for
      # ggtree's colour aesthetic — typical for tree_build='pml' with
      # discrete_trait_analysis where Dowser does not expose per-internal-node
      # trait values to plotTrees.
      "Internal node trait coloring is not available for this tree configuration (Dowser does not expose per-internal-node trait reconstructions compatible with plotTrees). Tip colors are still applied; use the Lineage tab for internal node sequences."
    }
    render_warnings <- c(render_warnings, msg)
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
      figure_paths = character(0),
      render = paste0("plotTrees_uncolored_tipsize", plot_tipsize),
      warnings = if (length(render_warnings)) render_warnings else NULL
    ))
  }

  # Write PNGs straight to disk — no base64 round-trip in RAM. If no out dir
  # was provided, fall back to a tempdir so the caller can still find files
  # (legacy behavior). The caller is responsible for the dir's lifetime.
  if (is.null(figures_out_dir) || !nzchar(figures_out_dir)) {
    figures_out_dir <- tempfile("dowser_figs_")
  }
  dir.create(figures_out_dir, recursive = TRUE, showWarnings = FALSE)
  figure_paths <- character(0)
  for (i in seq_along(plots)) {
    p_path <- file.path(figures_out_dir, sprintf("phylogeny_%d.png", i))
    saved <- tryCatch(save_png_file(plots[[i]], p_path), error = function(e) NULL)
    if (!is.null(saved) && file.exists(p_path)) figure_paths <- c(figure_paths, p_path)
  }

  render <- switch(
    render_mode,
    colored_nodes = paste0("plotTrees_", plot_tips, "_nodes_tipsize", plot_tipsize),
    colored_no_nodes = paste0("plotTrees_", plot_tips, "_tipsize", plot_tipsize),
    paste0("plotTrees_uncolored_tipsize", plot_tipsize)
  )

  list(
    figure_paths = figure_paths,
    render = render,
    warnings = if (length(render_warnings)) render_warnings else NULL
  )
}

zip_export_bundle <- function(export_dir, zip_name = "dowser_artifacts.zip") {
  all_files <- list.files(export_dir, recursive = TRUE, full.names = TRUE)
  all_files <- all_files[basename(all_files) != zip_name]
  if (!length(all_files)) {
    return(list(path = NULL, name = NULL))
  }

  zip_path <- file.path(export_dir, zip_name)
  if (file.exists(zip_path)) file.remove(zip_path)

  old_wd <- getwd()
  setwd(export_dir)
  on.exit(setwd(old_wd), add = TRUE)

  rel_paths <- unique(sub(paste0("^", export_dir, "/?"), "", all_files, fixed = FALSE))
  rel_paths <- rel_paths[nzchar(rel_paths)]
  if (!length(rel_paths)) {
    return(list(path = NULL, name = NULL))
  }

  utils::zip(zipfile = zip_path, files = rel_paths)
  sz <- file.info(zip_path)$size
  if (is.na(sz) || sz <= 0) {
    return(list(path = NULL, name = NULL))
  }

  # Return the on-disk path. The caller (handlers.R / materialize_artifacts)
  # moves it into the artifact staging directory — no base64 in RAM.
  list(path = zip_path, name = zip_name)
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
    seed = p$seed,
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

  # Copy the rendered PNG files (already on disk) into the export bundle so
  # they ship inside the zip. No base64 round-trip — file → file.
  fig_paths <- result_parts$figure_paths
  if (!is.null(fig_paths) && length(fig_paths)) {
    for (i in seq_along(fig_paths)) {
      src <- fig_paths[[i]]
      if (is.null(src) || !nzchar(src) || !file.exists(src)) next
      dst <- file.path(out_dir, sprintf("tree_plot_%02d.png", i))
      tryCatch(file.copy(src, dst, overwrite = TRUE), error = function(e) NULL)
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
