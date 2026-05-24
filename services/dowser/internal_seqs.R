# Internal/intermediate node sequence extraction and Newick helpers.

to_newick <- function(phy) {
  tf <- tempfile(fileext = ".nwk")
  on.exit(if (file.exists(tf)) unlink(tf), add = TRUE)
  ape::write.tree(phy, file = tf)
  paste(readLines(tf, warn = FALSE), collapse = "")
}

relabel_phy_tips <- function(phy, from_labels, to_labels) {
  idx <- match(phy$tip.label, from_labels)
  new_labels <- to_labels[idx]
  new_labels[is.na(new_labels)] <- phy$tip.label[is.na(new_labels)]
  phy$tip.label <- new_labels
  phy
}

sanitize_newick_label <- function(label) {
  gsub("[^A-Za-z0-9._-]", "_", as.character(label))
}

build_display_label_map <- function(db, id_col = "sequence_id", label_field = NULL) {
  ids <- as.character(db[[id_col]])
  if (is.null(label_field) || !nzchar(label_field) || identical(label_field, id_col)) {
    tip_label_map <- lapply(seq_along(ids), function(i) {
      list(
        sequence_id = ids[i],
        display_label = ids[i],
        display_label_raw = ids[i],
        display_label_newick_safe = ids[i]
      )
    })
    return(list(
      display_map = setNames(ids, ids),
      newick_safe = setNames(ids, ids),
      tip_label_map = tip_label_map,
      use_display = FALSE
    ))
  }

  if (!label_field %in% names(db)) {
    return(list(
      display_map = setNames(ids, ids),
      newick_safe = setNames(ids, ids),
      tip_label_map = lapply(seq_along(ids), function(i) {
        list(
          sequence_id = ids[i],
          display_label = ids[i],
          display_label_raw = ids[i],
          display_label_newick_safe = ids[i]
        )
      }),
      use_display = FALSE,
      warning = sprintf("Label column '%s' not found; display Newick omitted.", label_field)
    ))
  }

  raw_labels <- as.character(db[[label_field]])
  missing <- is.na(raw_labels) | !nzchar(trimws(raw_labels))
  raw_labels[missing] <- ids[missing]
  safe_labels <- sanitize_newick_label(raw_labels)

  dup <- raw_labels[duplicated(raw_labels)]
  if (length(dup)) {
    return(list(
      display_map = setNames(ids, ids),
      newick_safe = setNames(ids, ids),
      tip_label_map = lapply(seq_along(ids), function(i) {
        list(
          sequence_id = ids[i],
          display_label = ids[i],
          display_label_raw = ids[i],
          display_label_newick_safe = ids[i]
        )
      }),
      use_display = FALSE,
      warning = sprintf(
        "label_field '%s' is not unique (%d duplicated values); display Newick omitted. Canonical Newick uses sequence_id.",
        label_field, length(unique(dup))
      )
    ))
  }

  tip_label_map <- lapply(seq_along(ids), function(i) {
    list(
      sequence_id = ids[i],
      display_label = raw_labels[i],
      display_label_raw = raw_labels[i],
      display_label_newick_safe = safe_labels[i]
    )
  })

  list(
    display_map = setNames(raw_labels, ids),
    newick_safe = setNames(safe_labels, ids),
    tip_label_map = tip_label_map,
    use_display = TRUE
  )
}

safe_get_all_seqs <- function(trees_tbl) {
  tryCatch(
    dowser::getAllSeqs(trees_tbl, imgt_gaps = TRUE),
    error = function(e) {
      warning(sprintf("getAllSeqs failed: %s", conditionMessage(e)))
      NULL
    }
  )
}

seq_df_to_records <- function(df, clone_id = NA_character_) {
  if (is.null(df) || !is.data.frame(df) || !nrow(df)) return(list())
  out <- jsonlite::fromJSON(jsonlite::toJSON(df, dataframe = "rows"), simplifyVector = FALSE)
  lapply(out, function(row) {
    if (is.null(row$clone_id) || !nzchar(as.character(row$clone_id %||% ""))) {
      row$clone_id <- clone_id
    }
    row
  })
}

extract_tree_edges <- function(phy) {
  if (is.null(phy$edge) || !nrow(phy$edge)) {
    return(data.frame(
      parent = integer(0),
      node = integer(0),
      branch_length = numeric(0),
      stringsAsFactors = FALSE
    ))
  }
  data.frame(
    parent = as.integer(phy$edge[, 1]),
    node = as.integer(phy$edge[, 2]),
    branch_length = if (!is.null(phy$edge.length)) as.numeric(phy$edge.length) else NA_real_,
    stringsAsFactors = FALSE
  )
}

lookup_seq_row <- function(all_seqs_df, node_num, node_label = NULL) {
  if (is.null(all_seqs_df) || !is.data.frame(all_seqs_df) || !nrow(all_seqs_df)) {
    return(list(sequence = "", sequence_alignment = "", locus = "N", node_id = NA_character_))
  }

  row <- NULL
  if ("node" %in% names(all_seqs_df)) {
    idx <- which(as.integer(all_seqs_df$node) == as.integer(node_num))
    if (length(idx)) row <- all_seqs_df[idx[1], , drop = FALSE]
  }
  if (is.null(row) && !is.null(node_label) && "node_id" %in% names(all_seqs_df)) {
    idx <- which(as.character(all_seqs_df$node_id) == as.character(node_label))
    if (length(idx)) row <- all_seqs_df[idx[1], , drop = FALSE]
  }

  if (is.null(row)) {
    return(list(sequence = "", sequence_alignment = "", locus = "N", node_id = NA_character_))
  }

  seq_val <- as.character(row$sequence %||% "")
  seq_aln <- as.character(row$sequence_alignment %||% seq_val)
  list(
    sequence = seq_val,
    sequence_alignment = seq_aln,
    locus = as.character(row$locus %||% "N"),
    node_id = as.character(row$node_id %||% NA_character_)
  )
}

lookup_named <- function(map, key, default = NULL) {
  key <- as.character(key)
  if (is.list(map)) {
    val <- map[[key]]
    if (is.null(val)) return(default)
    return(val)
  }
  idx <- match(key, names(map))
  if (is.na(idx)) return(default)
  map[[idx]]
}

build_lineage_nodes <- function(phy, clone_id, all_seqs_for_clone = NULL) {
  edges <- extract_tree_edges(phy)
  n_tips <- length(phy$tip.label)
  if (!nrow(edges) && n_tips == 0) return(list())

  node_nums <- if (nrow(edges)) unique(c(edges$parent, edges$node)) else seq_len(n_tips)
  children_map <- split(edges$node, edges$parent)
  parent_map <- setNames(as.character(edges$parent), as.character(edges$node))
  branch_map <- setNames(as.numeric(edges$branch_length), as.character(edges$node))

  lapply(node_nums, function(node_num) {
    node_key <- as.character(node_num)
    is_tip <- node_num <= n_tips
    tip_label <- if (is_tip) phy$tip.label[node_num] else NA_character_
    seq_info <- lookup_seq_row(all_seqs_for_clone, node_num, tip_label)
    node_id <- if (!is.na(seq_info$node_id) && nzchar(seq_info$node_id)) {
      seq_info$node_id
    } else if (is_tip && !is.na(tip_label)) {
      tip_label
    } else {
      paste0("node_", node_num)
    }

    children <- lookup_named(children_map, node_key, integer(0))
    parent_val <- lookup_named(parent_map, node_key, NA_character_)
    branch_val <- lookup_named(branch_map, node_key, 0)

    list(
      clone_id = clone_id,
      node = as.integer(node_num),
      node_id = node_id,
      sequence = seq_info$sequence,
      sequence_alignment = seq_info$sequence_alignment,
      locus = seq_info$locus,
      is_internal = !is_tip,
      is_observed = is_tip,
      parent = if (is.na(parent_val) || !nzchar(parent_val)) NA_integer_ else as.integer(parent_val),
      children = as.list(as.integer(children)),
      branch_length = as.numeric(branch_val),
      trait_state = NULL
    )
  })
}

build_tree_outputs <- function(trees_tbl, db, p, label_check) {
  label_field <- p$label_field %||% "sequence_id"
  show_nodes <- isTRUE(p$show_node_numbers %||% FALSE) ||
    identical(p$analysis_mode, "tree_with_internal_sequences") ||
    isTRUE(p$return_internal_sequences %||% FALSE)

  return_internal <- isTRUE(p$return_internal_sequences %||% FALSE) ||
    identical(p$analysis_mode, "tree_with_internal_sequences")

  if (isTRUE(p$collapse_internal_nodes %||% TRUE) && exists("collapseNodes", where = asNamespace("dowser"))) {
    trees_tbl <- tryCatch(dowser::collapseNodes(trees_tbl), error = function(e) trees_tbl)
  }

  all_seqs_df <- if (return_internal) safe_get_all_seqs(trees_tbl) else NULL
  node_warnings <- character(0)
  if (return_internal && is.null(all_seqs_df)) {
    node_warnings <- c(node_warnings, "getAllSeqs failed; node sequences omitted but tree output retained.")
  }

  label_map <- build_display_label_map(
    db,
    id_col = "sequence_id",
    label_field = if (isTRUE(label_check$use_display)) label_field else "sequence_id"
  )
  if (!is.null(label_map$warning)) node_warnings <- c(node_warnings, label_map$warning)
  use_display <- isTRUE(label_check$use_display) && isTRUE(label_map$use_display)

  tree_list <- vector("list", length(trees_tbl$trees))
  legacy_newicks <- character(length(trees_tbl$trees))

  clone_ids <- if ("clone_id" %in% names(trees_tbl)) {
    as.character(trees_tbl$clone_id)
  } else {
    paste0("clone_", seq_along(trees_tbl$trees))
  }

  for (i in seq_along(trees_tbl$trees)) {
    phy <- trees_tbl$trees[[i]]
    cid <- clone_ids[i]

    canonical <- to_newick(phy)
    display <- NULL
    lineage <- canonical

    if (use_display) {
      mapped <- label_map$newick_safe[phy$tip.label]
      unmapped <- is.na(mapped)
      if (any(unmapped)) {
        mapped[unmapped] <- phy$tip.label[unmapped]
        node_warnings <- c(
          node_warnings,
          sprintf("Clone %s: %d tree tips could not be mapped to display labels.", cid, sum(unmapped))
        )
      }
      disp_phy <- relabel_phy_tips(phy, phy$tip.label, mapped)
      display <- to_newick(disp_phy)
      lineage <- display
    }

    sub_all_seqs <- NULL
    if (return_internal && !is.null(all_seqs_df)) {
      sub_all_seqs <- all_seqs_df
      if ("clone_id" %in% names(sub_all_seqs)) {
        sub_all_seqs <- sub_all_seqs[sub_all_seqs$clone_id == cid, , drop = FALSE]
      }
    }

    nodes <- if (return_internal) build_lineage_nodes(phy, cid, sub_all_seqs) else list()
    all_seq <- if (return_internal && !is.null(sub_all_seqs)) {
      seq_df_to_records(sub_all_seqs, cid)
    } else {
      list()
    }

    tree_list[[i]] <- list(
      clone_id = cid,
      canonical_newick = canonical,
      display_newick = display,
      lineage_newick = lineage,
      tip_label_map = label_map$tip_label_map,
      nodes = nodes,
      all_sequences = all_seq,
      show_node_numbers = show_nodes
    )
    legacy_newicks[i] <- canonical
  }

  list(
    trees_detail = tree_list,
    legacy_newicks = legacy_newicks,
    trees_tbl = trees_tbl,
    node_warnings = unique(node_warnings)
  )
}

build_annotations <- function(trees_tbl, db, p, tip_col, plot_tip_col = NULL) {
  label_field <- p$label_field %||% "sequence_id"
  annos <- vector("list", length(trees_tbl$trees))
  color_col <- plot_tip_col %||% tip_col

  for (i in seq_along(trees_tbl$trees)) {
    phy <- trees_tbl$trees[[i]]
    tips <- phy$tip.label
    jj <- match(tips, db$sequence_id)

    disp <- ifelse(is.na(jj), "Germline", as.character(db[[label_field]][jj]))
    disp[is.na(jj)] <- "Germline"

    out <- data.frame(
      label = disp,
      final_tip_label = tips,
      sequence_id = ifelse(is.na(jj), NA_character_, as.character(db$sequence_id[jj])),
      stringsAsFactors = FALSE
    )

    if (!is.null(color_col) && color_col %in% names(db)) {
      out[[tip_col %||% color_col]] <- ifelse(is.na(jj), "Germline", as.character(db[[color_col]][jj]))
    }

    for (fld in parse_vec(p$annotation_fields)) {
      if (fld %in% names(db)) {
        out[[fld]] <- ifelse(is.na(jj), NA_character_, as.character(db[[fld]][jj]))
      }
    }

    num_fields <- unique(c(
      parse_vec(p$numeric_annotation_fields),
      "duplicate_count",
      "umi_count",
      "clone_count",
      "consensus_count"
    ))
    for (fld in num_fields) {
      if (fld %in% names(db)) {
        vals <- suppressWarnings(as.numeric(db[[fld]][jj]))
        out[[fld]] <- ifelse(is.na(jj), NA_real_, vals)
      }
    }

    annos[[i]] <- out
  }
  annos
}
