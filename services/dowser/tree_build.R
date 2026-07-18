# Tree building helpers and executable preflight.

validate_motifs_dir <- function(path) {
  if (!nzchar(path)) return(FALSE)
  if (!dir.exists(path)) return(FALSE)
  length(list.files(path, all.files = FALSE)) > 0
}

check_igphyml_exec <- function(user_exec = NULL) {
  if (!is.null(user_exec) && nzchar(user_exec)) {
    path <- normalizePath(user_exec, mustWork = FALSE)
    if (!file.exists(path)) {
      return(list(
        ok = FALSE,
        error = sprintf("IgPhyML path does not exist: %s", user_exec),
        step = "dowser.preflight.igphyml"
      ))
    }
    if (file.access(path, 1) != 0) {
      return(list(
        ok = FALSE,
        error = sprintf("IgPhyML path is not executable: %s", path),
        step = "dowser.preflight.igphyml"
      ))
    }
    return(list(ok = TRUE, exec = path))
  }
  cand <- Sys.which("igphyml")
  if (nzchar(cand)) return(list(ok = TRUE, exec = unname(cand)))
  default <- Sys.getenv("IGPHYML_BIN", "/usr/local/share/igphyml/src/igphyml")
  if (file.exists(default) && file.access(default, 1) == 0) {
    return(list(ok = TRUE, exec = default))
  }
  list(
    ok = FALSE,
    error = "IgPhyML not found. Set IGPHYML_BIN or install igphyml on PATH.",
    step = "dowser.preflight.igphyml"
  )
}

resolve_igphyml <- function(user_exec = NULL, user_motifs = NULL, require_ok = TRUE) {
  exec_res <- check_igphyml_exec(user_exec)
  if (!isTRUE(exec_res$ok)) {
    if (isTRUE(require_ok)) {
      dowser_validation_error(exec_res$error, step = exec_res$step %||% "dowser.preflight.igphyml")
    }
    return(exec_res)
  }
  exec_path <- exec_res$exec

  candidates <- unique(c(
    user_motifs,
    Sys.getenv("IGPHYML_MOTIFS", ""),
    Sys.getenv("IGPHYML_PATH", ""),
    file.path(dirname(dirname(exec_path)), "share", "igphyml", "src", "motifs"),
    "/usr/local/share/igphyml/src/motifs"
  ))

  motifs_dir <- NULL
  for (d in candidates) {
    if (validate_motifs_dir(d)) {
      motifs_dir <- d
      break
    }
  }

  if (is.null(motifs_dir)) {
    motifs_err <- list(
      ok = FALSE,
      error = "IgPhyML hotspot motif tables not found. Set IGPHYML_MOTIFS.",
      step = "dowser.preflight.igphyml"
    )
    if (isTRUE(require_ok)) {
      dowser_validation_error(motifs_err$error, step = motifs_err$step)
    }
    return(motifs_err)
  }

  Sys.setenv(IGPHYML_MOTIFS = motifs_dir, IGPHYML_PATH = motifs_dir)
  list(ok = TRUE, exec = exec_path, motifs = motifs_dir)
}

resolve_phylip <- function(tool = c("dnapars", "dnaml")) {
  tool <- match.arg(tool)
  env_key <- if (tool == "dnapars") "DNAPARS_PATH" else "DNAML_PATH"
  env_val <- Sys.getenv(env_key, "")
  if (nzchar(env_val) && file.exists(env_val) && file.access(env_val, 1) == 0) {
    return(list(ok = TRUE, exec = env_val, tool = tool))
  }
  cand <- Sys.which(tool)
  if (nzchar(cand)) return(list(ok = TRUE, exec = cand, tool = tool))
  list(
    ok = FALSE,
    error = sprintf("%s executable not found. Install PHYLIP or set %s.", tool, env_key),
    step = sprintf("dowser.preflight.%s", tool)
  )
}

resolve_raxml <- function(user_bin = NULL) {
  candidates <- unique(c(
    user_bin,
    Sys.getenv("RAXML_BIN", ""),
    Sys.which("raxml-ng"),
    Sys.which("raxmlNG"),
    "/usr/local/bin/raxml-ng"
  ))
  for (cand in candidates) {
    if (nzchar(cand) && file.exists(cand) && file.access(cand, 1) == 0) {
      return(list(ok = TRUE, exec = cand))
    }
  }
  list(
    ok = FALSE,
    error = "RAxML executable not found. Install RAxML-NG or set RAXML_BIN.",
    step = "dowser.preflight.raxml"
  )
}

preflight_tree_build <- function(build, p) {
  if (build == "igphyml") {
    resolved <- resolve_igphyml(
      user_exec = p$igphyml_exec %||% Sys.getenv("IGPHYML_BIN", "igphyml"),
      user_motifs = p$igphyml_motifs %||% Sys.getenv("IGPHYML_MOTIFS", ""),
      require_ok = TRUE
    )
    if (!isTRUE(resolved$ok)) return(resolved)
    return(list(ok = TRUE, igphyml = resolved))
  }
  if (build == "dnapars") {
    r <- resolve_phylip("dnapars")
    if (!isTRUE(r$ok)) return(r)
    return(list(ok = TRUE, phylip = r))
  }
  if (build == "dnaml") {
    r <- resolve_phylip("dnaml")
    if (!isTRUE(r$ok)) return(r)
    return(list(ok = TRUE, phylip = r))
  }
  if (build == "raxml") {
    r <- resolve_raxml(p$raxml_exec %||% NULL)
    if (!isTRUE(r$ok)) return(r)
    return(list(ok = TRUE, raxml = r))
  }
  list(ok = TRUE)
}

build_get_trees_args <- function(clones, p, preflight, tmpdir, run_id) {
  build <- p$tree_build
  trait <- normalize_col(p$trait_field, NULL)
  mode <- p$analysis_mode %||% "tree_only"
  if (identical(mode, "discrete_trait_analysis") && !is.null(trait)) {
    # trait passed to getTrees for DTA
  } else if (!identical(mode, "discrete_trait_analysis")) {
    trait <- NULL
  }

  args <- list(
    clones,
    nproc = as.integer(p$nproc %||% 1L),
    collapse = isTRUE(p$collapse_internal_nodes %||% TRUE),
    check_divergence = isTRUE(p$check_divergence %||% TRUE)
  )

  if (!identical(build, "pratchet")) args$build <- build
  if (!is.null(trait)) args$trait <- trait
  if (!is.null(p$modelfile) && nzchar(p$modelfile) && file.exists(p$modelfile)) {
    args$modelfile <- p$modelfile
  }

  if (build == "igphyml") {
    args$exec <- preflight$igphyml$exec
    part <- p$partition_model %||% "single"
    if (!part %in% PARTITION_MODEL_ENUM) part <- "single"
    args$partition <- part
  }
  if (!is.null(trait) && !is.null(preflight$igphyml$exec) && !identical(build, "igphyml")) {
    args$igphyml <- preflight$igphyml$exec
  }
  if (build == "raxml" && !is.null(preflight$raxml$exec)) {
    args$exec <- preflight$raxml$exec
  }
  if (build %in% c("dnapars", "dnaml") && !is.null(preflight$phylip$exec)) {
    args$exec <- preflight$phylip$exec
  }

  if (!is.null(tmpdir) && nzchar(tmpdir)) {
    args$dir <- tmpdir
    args$id <- run_id %||% "dowser_run"
  }

  # Forward the seed as rseed only to builders that accept it. getTrees passes
  # `...` straight into the per-clone build function; in dowser 2.4.1 only
  # buildRAxML / buildIgphyml take rseed (and a `...`), while buildPratchet /
  # buildPML / buildPhylo (dnapars, dnaml) take neither — passing rseed to them
  # would raise "unused argument". R's set.seed() in run_get_trees covers the
  # pratchet ratchet, multi2di resolution and pml; rseed covers the external
  # RAxML-NG (--seed) and IgPhyML (--r_seed) binaries, which ignore R's RNG.
  if (build %in% c("raxml", "igphyml")) {
    args$rseed <- as.integer(p$seed %||% 42L)
  }

  args
}

run_get_trees <- function(clones, p, preflight, tmpdir = NULL, run_id = NULL) {
  args <- build_get_trees_args(clones, p, preflight, tmpdir, run_id)

  # Seed the stochastic tree search so a stored parameter set is reproducible.
  # L'Ecuyer-CMRG gives reproducible parallel streams when getTrees builds
  # clones via parallel::mclapply (nproc > 1); set.seed() covers the pratchet
  # parsimony ratchet and the ape::multi2di(random = TRUE) multifurcation
  # resolution. Builders that ignore R's RNG are seeded via args$rseed above.
  effective_seed <- as.integer(p$seed %||% 42L)
  RNGkind("L'Ecuyer-CMRG")
  set.seed(effective_seed)

  trees_tbl <- do.call(dowser::getTrees, args)
  list(trees_tbl = trees_tbl, build_args = args)
}

extract_igphyml_metadata <- function(trees_tbl, preflight, p) {
  if (is.null(trees_tbl) || !is.data.frame(trees_tbl)) return(NULL)
  params <- list()
  param_cols <- intersect(
    c("parameters", "kappa", "omega", "LL", "loglik", "partition"),
    names(trees_tbl)
  )
  for (col in param_cols) {
    params[[col]] <- trees_tbl[[col]]
  }

  requested <- p$partition_model %||% "single"
  effective <- if (identical(p$tree_build, "igphyml")) requested else "single"
  output_detected <- any(c("partition", "parameters") %in% names(trees_tbl))
  supported <- identical(p$tree_build, "igphyml") &&
    requested %in% PARTITION_MODEL_ENUM
  warning_msg <- if (!output_detected && !identical(effective, "single")) {
    "Partition model was passed to Dowser/IgPhyML according to service validation, but no partition-specific output column was detected."
  } else {
    NULL
  }

  list(
    exec = preflight$igphyml$exec %||% NULL,
    motifs = preflight$igphyml$motifs %||% NULL,
    partition_model = effective,
    requested_partition_model = requested,
    effective_partition_model = effective,
    partition_model_requested = requested,
    partition_model_effective = effective,
    partition_model_supported = supported,
    partition_model_output_detected = output_detected,
    partition_model_warning = warning_msg,
    parameters = params,
    warnings = if (!is.null(warning_msg)) list(warning_msg) else list()
  )
}

log_dependency_versions <- function() {
  logf <- function(...) cat(sprintf(...), "\n", file = stderr())
  logf("[dowser] dowser version: %s", as.character(utils::packageVersion("dowser")))
  for (tool in c("dnapars", "dnaml", "raxml-ng", "igphyml")) {
    path <- Sys.which(tool)
    if (nzchar(path)) logf("[dowser] %s: %s", tool, path)
  }
}
