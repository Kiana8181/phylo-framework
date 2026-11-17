# Runtime is rocker/r-ver:4.4.3 (Ubuntu 24.04, R 4.4.3), not
# immcantation/suite:4.6.0. The suite image is about 10 GB because it also
# carries BLAST, IgBLAST, PROJ, a full TeX Live, and R packages this service
# never loads. BrepPhylo is not the same shape as Dowser: it does not call
# RAxML-NG or dnaml, it does call dnapars and IgPhyML, and
# makeAlignmentPDF (off unless the request asks) runs pdflatex through
# tools::texi2dvi. A small TeX installation stays in this image only.
# Compilers stay in the build stage.
#
# Scientific versions are unchanged: IgPhyML 2.0.0, PHYLIP 3.697, BrepPhylo
# commit 7c52fb66e28ee3839a32633bf809f320f060c876, CRAN snapshot 2026-07-20,
# R 4.4.3. The suite is not upgraded.

FROM rocker/r-ver:4.4.3 AS build

ENV DEBIAN_FRONTEND=noninteractive \
    DOWNLOAD_STATIC_LIBV8=1 \
    MAKEFLAGS=-j1 \
    OMP_NUM_THREADS=1 \
    OMP_THREAD_LIMIT=1 \
    OPENBLAS_NUM_THREADS=1 \
    FLEXIBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    BLIS_NUM_THREADS=1 \
    RCPP_PARALLEL_NUM_THREADS=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      gfortran \
      autoconf \
      automake \
      ca-certificates \
      curl \
      pkg-config \
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
      libbz2-dev \
      liblzma-dev \
    && rm -rf /var/lib/apt/lists/*

# PHYLIP 3.697, the version immcantation/suite:4.6.0 builds. This service
# calls dnapars only.
RUN curl -fsSL -o /tmp/phylip.tar.gz https://phylipweb.github.io/phylip/download/phylip-3.697.tar.gz \
    && tar -xzf /tmp/phylip.tar.gz -C /tmp \
    && sed -i '/double computeAngle/a void makebox(char *, double *, double *, double *, long);' /tmp/phylip-3.697/src/draw.h \
    && make -C /tmp/phylip-3.697/src -f Makefile.unx install CFLAGS='-fcommon' \
    && install -m 0755 /tmp/phylip-3.697/exe/dnapars /usr/local/bin/dnapars \
    && rm -rf /tmp/phylip-3.697 /tmp/phylip.tar.gz \
    && printf '\n' | /usr/local/bin/dnapars 2>&1 | grep -q dnapars

# IgPhyML 2.0.0, the tag immcantation/suite:4.6.0 builds, with the same
# make_phyml_blas_omp script. Motifs stay beside the binary.
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

# Keep native package compilation and BLAS backends within the builder's
# process/thread budget. This also prevents GCC's make integration from
# selecting every visible host CPU during dependency builds.
RUN DOWNLOAD_STATIC_LIBV8=1 R -q -e "options(Ncpus = 1L); install.packages( \
    c('plumber', 'jsonlite', 'httpuv', 'swagger', 'jsonvalidate', 'httr', 'ape', 'igraph', 'remotes'), \
    repos = 'https://packagemanager.posit.co/cran/2026-07-20' \
    )" \
    && R -q -e "options(Ncpus = 1L); install.packages('BiocManager', repos = 'https://packagemanager.posit.co/cran/2026-07-20'); \
    options(repos = c(CRAN = 'https://packagemanager.posit.co/cran/2026-07-20')); \
    bioc_deps <- c('Biostrings','msa','GenomicRanges','GenomicAlignments'); \
    BiocManager::install(bioc_deps, ask = FALSE, update = FALSE, version = '3.20'); \
    stopifnot(all(bioc_deps %in% rownames(installed.packages())))"

# Install BrepPhylo via a codeload tarball, NOT install_github.
# install_github goes through api.github.com which is rate-limited to 60 req/hr
# for unauthenticated users — Docker build retries silently exhausted the quota.
# codeload.github.com serves the raw tarball via CDN, no rate limit. stopifnot
# at the end fails the build loudly if BrepPhylo somehow didn't install.
# BrepPhylo's dependencies that the base image lacks come from the same dated
# CRAN snapshot as everything else, not from the CRAN of the build day (which
# had moved five of them by 2026-10-26); the version check covers those five.
# Install the dependencies and BrepPhylo in separate R processes. Keeping both
# in one remotes::install_local call retains the dependency-build heap until
# remotes forks R CMD build and can fail with ENOMEM on constrained builders.
ARG BREPPHYLO_COMMIT=7c52fb66e28ee3839a32633bf809f320f060c876
RUN curl -fsSL -o /tmp/brepphylo.tar.gz \
      "https://codeload.github.com/Fraternalilab/BrepPhylo/tar.gz/${BREPPHYLO_COMMIT}" \
    && mkdir /tmp/brepphylo-src \
    && tar -xzf /tmp/brepphylo.tar.gz --strip-components=1 -C /tmp/brepphylo-src \
    && rm -f /tmp/brepphylo.tar.gz

RUN R -q -e "options(Ncpus = 1L); \
             stopifnot('msa' %in% rownames(installed.packages())); \
             remotes::install_deps('/tmp/brepphylo-src', dependencies = TRUE, upgrade = 'never', \
                                   repos = 'https://packagemanager.posit.co/cran/2026-07-20')"

RUN R CMD INSTALL --no-multiarch /tmp/brepphylo-src \
    && R -q -e "stopifnot('BrepPhylo' %in% rownames(installed.packages())); \
                pins <- c(combinat = '0.0-8', expm = '1.0-0', optimParallel = '1.0-2', rncl = '0.8.9', vegan = '2.7-5'); \
                stopifnot(identical(vapply(names(pins), function(p) packageDescription(p, fields = 'Version'), ''), pins))" \
    && rm -rf /tmp/brepphylo-src

# paws.storage + digest installed AFTER BrepPhylo so they don't interfere with the
# upstream install chain. Required by services/brepphylo/object_storage.R to
# upload artifact files directly to MinIO.
RUN R -q -e "options(Ncpus = 1L); install.packages(c('paws.storage', 'digest'), repos = 'https://packagemanager.posit.co/cran/2026-07-20'); \
    stopifnot(all(c('paws.storage', 'digest') %in% rownames(installed.packages())))"

FROM rocker/r-ver:4.4.3

ENV DEBIAN_FRONTEND=noninteractive \
    CONTRACTS_DIR=/contracts \
    DNAPARS_PATH=/usr/local/bin/dnapars \
    IGPHYML_BIN=/usr/local/share/igphyml/src/igphyml \
    IGPHYML_MOTIFS=/usr/local/share/igphyml/src/motifs \
    IGPHYML_PATH=/usr/local/share/igphyml/src/motifs \
    STRICT_CONTRACT_ROUTES=true \
    RETICULATE_PYTHON=/usr/bin/python3 \
    MAKEFLAGS=-j1 \
    OMP_NUM_THREADS=1 \
    OMP_THREAD_LIMIT=1 \
    OPENBLAS_NUM_THREADS=1 \
    FLEXIBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    BLIS_NUM_THREADS=1 \
    RCPP_PARALLEL_NUM_THREADS=1 \
    PATH=/opt/TinyTeX/bin/x86_64-linux:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      python3 \
      python3-pip \
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
      libbz2-1.0 \
      liblzma5 \
    && python3 -m pip install --no-cache-dir --break-system-packages networkx==3.4.2 \
    && python3 -c "import networkx; assert networkx.__version__ == '3.4.2'" \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /usr/local/lib/R/site-library /usr/local/lib/R/site-library
COPY --from=build /usr/local/bin/dnapars /usr/local/bin/dnapars
COPY --from=build /usr/local/share/igphyml/src/igphyml /usr/local/share/igphyml/src/igphyml
COPY --from=build /usr/local/share/igphyml/src/motifs /usr/local/share/igphyml/src/motifs

# makeAlignmentPDF is off unless a request sets it. When it is on, BrepPhylo
# calls msaPrettyPrint, which runs pdflatex. TinyTeX is enough; the suite's
# full TeX Live collection is not. texshade is what that PDF uses. This runs
# after the library copy so the copy does not wipe the tinytex package.
RUN R -q -e "install.packages('tinytex', repos = 'https://packagemanager.posit.co/cran/2026-07-20'); \
    tinytex::install_tinytex(dir = '/opt/TinyTeX', force = TRUE)" \
    && /opt/TinyTeX/bin/x86_64-linux/tlmgr install texshade \
    && command -v pdflatex \
    && command -v latexmk

RUN if ldd /usr/local/share/igphyml/src/igphyml | grep -q 'not found'; then \
      ldd /usr/local/share/igphyml/src/igphyml; exit 1; \
    fi \
    && /usr/local/share/igphyml/src/igphyml --version 2>&1 | grep -q '2.0.0' \
    && R -q -e "stopifnot('BrepPhylo' %in% rownames(installed.packages()))"

WORKDIR /srv
COPY validators.R /srv/validators.R
COPY plumber.R /srv/plumber.R
COPY resource_limits.R /srv/resource_limits.R
COPY job_manager.R /srv/job_manager.R
COPY job_runner.R /srv/job_runner.R
COPY artifact_manifest.R /srv/artifact_manifest.R
COPY object_storage.R /srv/object_storage.R

EXPOSE 8003

CMD ["R", "-q", "-e", "pr <- plumber::plumb('/srv/plumber.R'); pr$$run(host='0.0.0.0', port=8003)"]
