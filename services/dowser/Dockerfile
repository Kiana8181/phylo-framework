# Runtime is rocker/r-ver:4.4.3 (Ubuntu 24.04, R 4.4.3), not
# immcantation/suite:4.6.0. The suite image is about 10 GB because it also
# carries BLAST, IgBLAST, PROJ, a full TeX Live, and hundreds of R packages
# this service never loads. Dowser's own R sources do not call pdflatex, so
# TeX is not installed here. Compilers stay in the build stage.
#
# Scientific versions are the ones the suite image and the previous Dockerfile
# already pinned: IgPhyML 2.0.0 (built the same way, ./make_phyml_blas_omp),
# PHYLIP 3.697 (dnapars and dnaml only), RAxML-NG 1.2.2, Dowser 2.4.1,
# alakazam 1.4.3, shazam 1.3.2. R stays 4.4.3. The suite is not upgraded.

FROM rocker/r-ver:4.4.3 AS build

ENV DEBIAN_FRONTEND=noninteractive \
    DOWNLOAD_STATIC_LIBV8=1 \
    MAKEFLAGS=-j2

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      gfortran \
      autoconf \
      automake \
      ca-certificates \
      curl \
      pkg-config \
      unzip \
      libcurl4-openssl-dev \
      libssl-dev \
      libxml2-dev \
      libpng-dev \
      libjpeg-dev \
      libtiff-dev \
      libfontconfig1-dev \
      libfreetype6-dev \
      libfribidi-dev \
      libharfbuzz-dev \
      libopenblas-dev \
      liblapack-dev \
      libsodium-dev \
      libuv1-dev \
      zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# PHYLIP 3.697, the version immcantation/suite:4.6.0 builds. Only dnapars and
# dnaml are copied; the rest of the PHYLIP executables are drawing programs
# this service does not call. The makebox line is the same Debian patch the
# suite applies so the draw headers compile with current GCC, even though
# those programs are not installed.
RUN curl -fsSL -o /tmp/phylip.tar.gz https://phylipweb.github.io/phylip/download/phylip-3.697.tar.gz \
    && tar -xzf /tmp/phylip.tar.gz -C /tmp \
    && sed -i '/double computeAngle/a void makebox(char *, double *, double *, double *, long);' /tmp/phylip-3.697/src/draw.h \
    && make -C /tmp/phylip-3.697/src -f Makefile.unx install CFLAGS='-fcommon' \
    && install -m 0755 /tmp/phylip-3.697/exe/dnapars /tmp/phylip-3.697/exe/dnaml /usr/local/bin/ \
    && rm -rf /tmp/phylip-3.697 /tmp/phylip.tar.gz \
    && printf '\n' | /usr/local/bin/dnapars 2>&1 | grep -q dnapars \
    && printf '\n' | /usr/local/bin/dnaml 2>&1 | grep -q dnaml

# RAxML-NG 1.2.2 is the static linux binary the previous image downloaded.
# It is not a dynamic executable, so it runs on this Ubuntu base unchanged.
RUN curl -fsSL -o /tmp/raxml.zip https://github.com/amkozlov/raxml-ng/releases/download/1.2.2/raxml-ng_v1.2.2_linux_x86_64.zip \
    && unzip -q /tmp/raxml.zip -d /tmp/raxml \
    && install -m 0755 /tmp/raxml/raxml-ng /usr/local/bin/raxml-ng \
    && rm -rf /tmp/raxml /tmp/raxml.zip \
    && /usr/local/bin/raxml-ng --version | grep -q '1.2.2'

# IgPhyML 2.0.0, tag used by immcantation/suite:4.6.0, built with the same
# make_phyml_blas_omp script so the binary is the OpenMP BLAS build (the
# string it prints is "IgPhyML 2.0.0"). Motifs stay beside the binary; that
# is the path IGPHYML_MOTIFS points at.
RUN curl -fsSL -o /tmp/igphyml.tar.gz https://github.com/immcantation/igphyml/archive/refs/tags/2.0.0.tar.gz \
    && mkdir -p /usr/local/share/igphyml \
    && tar -xzf /tmp/igphyml.tar.gz -C /usr/local/share/igphyml --strip-components 1 \
    && rm -f /tmp/igphyml.tar.gz \
    && cd /usr/local/share/igphyml \
    && chmod +x make_phyml_blas_omp \
    && ./make_phyml_blas_omp \
    && src/igphyml --version 2>&1 | grep -q '2.0.0' \
    && test -d src/motifs \
    && find src -name '*.o' -delete

# One package at a time. The builders this image is compiled on have run out
# of memory when several of these C++ packages compiled at once.
ENV MAKEFLAGS=-j1

RUN DOWNLOAD_STATIC_LIBV8=1 R -q -e "options(Ncpus = 1L); \
    install.packages('BiocManager', repos = 'https://packagemanager.posit.co/cran/2026-07-20')"

# R packages at the versions of the image that produced the v3.0.0 runs
# (Dowser 2.4.1, alakazam 1.4.3, shazam 1.3.2). CRAN packages come from the
# 2026-07-27 snapshot, the first that holds all of these versions, and
# BiocParallel and pwalign from Bioconductor 3.20. The build fails if any
# version differs. Biostrings and ggtree are installed afterwards with
# update = FALSE so this pin set is not upgraded to whatever Bioconductor
# would consider current.
RUN R -q -e "options(Ncpus = 1L, repos = c(CRAN = 'https://packagemanager.posit.co/cran/2026-07-27')); \
    pins <- c( \
      BH = '1.90.0-1', BiocParallel = '1.40.2', MASS = '7.3-66', Matrix = '1.7-6', \
      Rcpp = '1.1.2', RcppArmadillo = '15.4.2-1', S7 = '0.2.2', V8 = '8.2.0', \
      ade4 = '1.7-24', airr = '2.0.0', alakazam = '1.4.3', aplot = '0.3.1', \
      base64enc = '0.1-6', bit64 = '4.8.2', cli = '3.6.6', clipr = '0.8.1', \
      commonmark = '2.0.0', cpp11 = '0.5.5', curl = '7.1.0', digest = '0.6.39', \
      diptest = '0.77-2', dowser = '2.4.1', dplyr = '1.2.1', fastmatch = '1.1-8', \
      futile.logger = '1.4.9', generics = '0.1.4', ggfun = '0.2.1', ggplot2 = '4.0.3', \
      ggplotify = '0.1.3', glue = '1.8.1', gridExtra = '2.3.1', hms = '1.1.4', \
      httpuv = '1.6.17', httr = '1.4.8', httr2 = '1.3.0', igraph = '2.3.3', \
      isoband = '0.3.0', jsonvalidate = '1.5.0', later = '1.4.8', lattice = '0.22-9', \
      lazyeval = '0.2.3', lifecycle = '1.0.5', litedown = '0.10', magrittr = '2.0.5', \
      nlme = '3.1-170', openssl = '2.4.2', otel = '0.2.0', patchwork = '1.3.2', \
      paws.common = '0.8.10', paws.storage = '0.10.0', pillar = '1.11.1', \
      pixmap = '0.4-14', plumber = '1.3.3', promises = '1.5.0', purrr = '1.2.2', \
      pwalign = '1.2.0', rappdirs = '0.3.4', readr = '2.2.0', rlang = '1.3.0', \
      scales = '1.4.0', segmented = '2.2-1', seqinr = '4.2-44', shazam = '1.3.2', \
      sp = '2.2-3', stringr = '1.6.0', swagger = '5.32.1', tibble = '3.3.1', \
      tidyr = '1.3.2', tidytree = '0.4.8', utf8 = '1.2.6', vctrs = '0.7.3', \
      viridisLite = '0.4.3', vroom = '1.7.1', webutils = '1.2.3', withr = '3.0.3', \
      xfun = '0.60', xml2 = '1.6.0', yaml = '2.3.12', yulab.utils = '0.2.4'); \
    installed <- function() vapply(names(pins), function(p) \
      as.character(suppressWarnings(packageDescription(p, fields = 'Version'))), ''); \
    current <- installed(); \
    install.packages(names(pins)[is.na(current) | current != pins], repos = BiocManager::repositories()); \
    current <- installed(); \
    differ <- is.na(current) | current != pins; \
    print(cbind(pinned = pins, installed = current)[differ, , drop = FALSE]); \
    stopifnot(!any(differ))"

RUN R -q -e "options(Ncpus = 1L, repos = c(CRAN = 'https://packagemanager.posit.co/cran/2026-07-20')); \
    BiocManager::install(c('Biostrings', 'ggtree'), ask = FALSE, update = FALSE, version = '3.20'); \
    stopifnot(all(c('Biostrings', 'ggtree', 'dowser', 'alakazam', 'shazam', 'plumber') %in% rownames(installed.packages())))"

FROM rocker/r-ver:4.4.3

ENV DEBIAN_FRONTEND=noninteractive \
    CONTRACTS_DIR=/contracts \
    DNAPARS_PATH=/usr/local/bin/dnapars \
    DNAML_PATH=/usr/local/bin/dnaml \
    RAXML_BIN=/usr/local/bin/raxml-ng \
    IGPHYML_BIN=/usr/local/share/igphyml/src/igphyml \
    IGPHYML_MOTIFS=/usr/local/share/igphyml/src/motifs \
    IGPHYML_PATH=/usr/local/share/igphyml/src/motifs \
    STRICT_CONTRACT_ROUTES=true

# Shared libraries the compiled R packages and the rebuilt IgPhyML link
# against. No compilers, no TeX, no Python: Dowser does not call them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      libcurl4t64 \
      libssl3t64 \
      libxml2 \
      libpng16-16t64 \
      libjpeg-turbo8 \
      libtiff6 \
      libfontconfig1 \
      libfreetype6 \
      libfribidi0 \
      libharfbuzz0b \
      libopenblas0 \
      liblapack3 \
      libgomp1 \
      libgfortran5 \
      libsodium23 \
      libuv1t64 \
      zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /usr/local/lib/R/site-library /usr/local/lib/R/site-library
COPY --from=build /usr/local/bin/dnapars /usr/local/bin/dnapars
COPY --from=build /usr/local/bin/dnaml /usr/local/bin/dnaml
COPY --from=build /usr/local/bin/raxml-ng /usr/local/bin/raxml-ng
COPY --from=build /usr/local/share/igphyml/src/igphyml /usr/local/share/igphyml/src/igphyml
COPY --from=build /usr/local/share/igphyml/src/motifs /usr/local/share/igphyml/src/motifs

RUN if ldd /usr/local/share/igphyml/src/igphyml | grep -q 'not found'; then \
      ldd /usr/local/share/igphyml/src/igphyml; exit 1; \
    fi \
    && /usr/local/share/igphyml/src/igphyml --version 2>&1 | grep -q '2.0.0' \
    && /usr/local/bin/raxml-ng --version | grep -q '1.2.2' \
    && R -q -e "stopifnot(packageVersion('dowser') == '2.4.1', packageVersion('alakazam') == '1.4.3', packageVersion('shazam') == '1.3.2')"

WORKDIR /srv
COPY validators.R data_io.R format_clones.R tree_build.R dta.R time_evolution.R internal_seqs.R exports.R handlers.R plumber.R resource_limits.R job_manager.R job_runner.R artifact_manifest.R object_storage.R /srv/

EXPOSE 8001

CMD ["R", "-q", "-e", "pr <- plumber::plumb('/srv/plumber.R'); pr$$run(host='0.0.0.0', port=8001)"]
