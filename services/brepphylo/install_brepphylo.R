tarball <- Sys.getenv("BREPPHYLO_TARBALL", "/tmp/brepphylo.tar.gz")
stopifnot(file.exists(tarball))

extract_dir <- tempfile(pattern = "brepphylo-src-")
dir.create(extract_dir)
utils::untar(tarball, exdir = extract_dir)
src_dirs <- list.dirs(extract_dir, recursive = FALSE, full.names = TRUE)
stopifnot(length(src_dirs) >= 1)
src_dir <- src_dirs[[1]]

# R CMD INSTALL avoids remotes/processx fork chain that OOM'd on low-memory hosts.
status <- system2(
  "R",
  c("CMD", "INSTALL", "--no-multiarch", "--with-keep.source=no", shQuote(src_dir)),
  stdout = "",
  stderr = ""
)
if (status != 0) stop("R CMD INSTALL failed with status ", status)

stopifnot("BrepPhylo" %in% rownames(installed.packages()))
