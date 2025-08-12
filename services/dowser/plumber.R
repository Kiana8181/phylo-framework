# services/dowser/plumber.R
#* @apiTitle Dowser microservice
#* @apiDescription Build BCR lineage trees with Dowser (requires AIRR-like input).

library(plumber)
library(jsonlite)
library(dowser)
library(alakazam)
library(ape)

# ---------- /spec ----------
#* @serializer json list(auto_unbox=TRUE)
#* @get /spec
function() {
  list(
    id = "dowser",
    name = "Dowser",
    version = as.character(utils::packageVersion("dowser")),
    accepts = c("text/csv", "text/tab-separated-values", "application/x-rds", "application/x-rda", "text/fasta"),
    paramSchema = list(
      `$schema` = "http://json-schema.org/draft-07/schema#",
      type = "object",
      properties = list(
        tree_model = list(enum = c("mp", "ml", "igphyml"), title = "Tree model", default = "mp"),
        minseq     = list(type = "integer", title = "Min seq per clone", default = 3),
        nproc      = list(type = "integer", title = "Threads", default = 1)
      ),
      required = list("tree_model")
    ),
    uiHints = list(order = c("tree_model", "minseq", "nproc"))
  )
}

to_newick <- function(phy) {
  tf <- tempfile(fileext = ".nwk")
  on.exit(if (file.exists(tf)) unlink(tf), add = TRUE)
  ape::write.tree(phy, file = tf)
  paste(readLines(tf, warn = FALSE), collapse = "")
}

encode_png <- function(plot, width = 900, height = 520, dpi = 100) {
  tf <- tempfile(fileext = ".png")
  on.exit(if (file.exists(tf)) unlink(tf), add = TRUE)
  ggplot2::ggsave(tf, plot = plot, width = width / 100, height = height / 100, dpi = dpi, bg = "white")
  jsonlite::base64_enc(readBin(tf, "raw", n = file.info(tf)$size))
}

# ---------- /run ----------
#* @serializer json list(auto_unbox=TRUE)
#* @post /run
function(req, res) {
  # ---- libs ----
  library(jsonlite)
  library(readr)
  library(dowser)
  library(ape)

  # ---- helpers ----
  `%||%` <- function(a, b) if (is.null(a) || length(a) == 0 || (is.character(a) && !nzchar(a))) b else a

  to_newick <- function(phy) {
    tf <- tempfile(fileext = ".nwk")
    on.exit(if (file.exists(tf)) unlink(tf), add = TRUE)
    ape::write.tree(phy, file = tf)
    paste(readLines(tf, warn = FALSE), collapse = "")
  }

  encode_png <- function(plot, width = 900, height = 520, dpi = 100) {
    tf <- tempfile(fileext = ".png")
    on.exit(if (file.exists(tf)) unlink(tf), add = TRUE)
    ggplot2::ggsave(tf, plot = plot, width = width / 100, height = height / 100, dpi = dpi, bg = "white")
    jsonlite::base64_enc(readBin(tf, "raw", n = file.info(tf)$size))
  }

  tryCatch(
    {
      # ---- parse multipart ----
      mp <- mime::parse_multipart(req)

      raw_params <- mp$params %||% mp$config %||% "{}"
      if (is.list(raw_params) && !is.null(raw_params$value)) raw_params <- raw_params$value
      if (length(raw_params) > 1) raw_params <- raw_params[[1]]
      p <- tryCatch(jsonlite::fromJSON(raw_params), error = function(e) list())
      if (is.null(p$minseq)) p$minseq <- 3L
      if (is.null(p$nproc)) p$nproc <- 1L

      # ---- find file part ----
      f <- NULL
      if (!is.null(mp$file) && is.list(mp$file) && !is.null(mp$file$datapath)) f <- mp$file
      if (is.null(f)) {
        idx <- which(vapply(mp, function(x) is.list(x) && !is.null(x$datapath), logical(1)))
        if (length(idx)) f <- mp[[idx[1]]]
      }
      if (is.null(f) || is.null(f$datapath) || !nzchar(f$datapath)) {
        res$status <- 400
        return(list(ok = FALSE, error = "file is required (AIRR TSV/CSV/RDS/RDA)"))
      }

      filename <- f$filename %||% f$name %||% basename(f$datapath) %||% "upload.bin"
      ctype <- f$content_type %||% f$type %||% ""
      ext <- tolower(tools::file_ext(filename))

      # infer from content-type if missing
      if (ext == "" && nzchar(ctype)) {
        if (grepl("csv", ctype, ignore.case = TRUE)) {
          ext <- "csv"
        } else if (grepl("tab|tsv", ctype, ignore.case = TRUE)) {
          ext <- "tsv"
        } else if (grepl("rds", ctype, ignore.case = TRUE)) {
          ext <- "rds"
        } else if (grepl("rda|rdata", ctype, ignore.case = TRUE)) ext <- "rda"
      }
      # sniff delimiter if still unknown
      if (ext == "") {
        head1 <- try(readLines(f$datapath, n = 1, warn = FALSE), silent = TRUE)
        if (!inherits(head1, "try-error") && length(head1)) {
          if (grepl("\t", head1)) {
            ext <- "tsv"
          } else if (grepl(",", head1)) ext <- "csv"
        }
      }

      # ---- read data ----
      db <- NULL
      load_ok <- FALSE
      if (ext %in% c("tsv", "txt")) {
        db <- suppressMessages(readr::read_tsv(f$datapath, show_col_types = FALSE))
      } else if (ext == "csv") {
        db <- suppressMessages(readr::read_csv(f$datapath, show_col_types = FALSE))
      } else if (ext == "rds") {
        db <- readRDS(f$datapath)
        load_ok <- TRUE
      } else if (ext %in% c("rda", "rdata")) {
        e <- new.env()
        load(f$datapath, envir = e)
        db <- e[[ls(e)[1]]]
        load_ok <- TRUE
      } else {
        # last-resort guesses
        try(
          {
            db <- readRDS(f$datapath)
            load_ok <- TRUE
          },
          silent = TRUE
        )
        if (!load_ok) {
          try(
            {
              e <- new.env()
              load(f$datapath, envir = e)
              db <- e[[ls(e)[1]]]
              load_ok <- TRUE
            },
            silent = TRUE
          )
        }
        if (!load_ok) {
          try(
            {
              db <- suppressMessages(readr::read_tsv(f$datapath, show_col_types = FALSE))
            },
            silent = TRUE
          )
        }
        if (is.null(db)) {
          try(
            {
              db <- suppressMessages(readr::read_csv(f$datapath, show_col_types = FALSE))
            },
            silent = TRUE
          )
        }
      }

      if (is.null(db)) {
        res$status <- 400
        return(list(
          ok = FALSE,
          error = sprintf("Unsupported file type: filename='%s' content_type='%s'. Expect AIRR TSV/CSV or RDS/RDA.", filename, ctype)
        ))
      }

      # ---- sanity ----
      req_cols <- c("clone_id", "sequence_id")
      if (!all(req_cols %in% names(db))) {
        res$status <- 400
        return(list(
          ok = FALSE,
          error = paste0(
            "Input missing required columns: ",
            paste(setdiff(req_cols, names(db)), collapse = ", "),
            ". Expect AIRR columns including clone_id and sequence_id."
          )
        ))
      }
      if (!"c_call" %in% names(db)) db$c_call <- "unknown"

      # ---- clones & trees ----
      # NOTE: use dowser::formatClones (not alakazam)
      clones <- dowser::formatClones(db, traits = "c_call", minseq = as.integer(p$minseq))
      trees_tbl <- dowser::getTrees(clones, nproc = as.integer(p$nproc))

      # ---- outputs ----
      newicks <- lapply(trees_tbl$trees, to_newick)

      figures_b64 <- NULL
      if (requireNamespace("ggtree", quietly = TRUE) && requireNamespace("ggplot2", quietly = TRUE)) {
        plots <- dowser::plotTrees(trees_tbl, tips = "c_call", tipsize = 2)
        figures_b64 <- lapply(plots, encode_png)
      }

      annos <- lapply(trees_tbl$trees, function(phy) {
        tips <- phy$tip.label
        jj <- match(tips, db$sequence_id)
        data.frame(
          label = tips,
          c_call = ifelse(is.na(jj), "Germline", as.character(db$c_call[jj])),
          stringsAsFactors = FALSE
        )
      })

      clones_meta <- list(
        clone_id = as.character(clones$clone_id),
        seqs     = as.integer(clones$seqs)
      )

      stats <- list(
        n_clones   = length(unique(db$clone_id)),
        n_trees    = length(trees_tbl$trees),
        total_seqs = nrow(db)
      )

      list(
        ok = TRUE,
        trees = unname(newicks),
        clones = clones_meta,
        annotations = annos,
        figures = if (is.null(figures_b64)) NULL else list(png_base64 = unname(figures_b64)),
        stats = stats,
        render = if (is.null(figures_b64)) NULL else "plotTrees_c_call_tipsize2"
      )
    },
    error = function(e) {
      res$status <- 500
      list(ok = FALSE, error = as.character(e))
    }
  )
}
