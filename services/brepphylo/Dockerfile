FROM immcantation/suite:4.6.0

ENV DEBIAN_FRONTEND=noninteractive \
    CONTRACTS_DIR=/contracts \
    DNAPARS_PATH=/usr/local/bin/dnapars \
    IGPHYML_BIN=/usr/local/share/igphyml/src/igphyml \
    IGPHYML_MOTIFS=/usr/local/share/igphyml/src/motifs \
    IGPHYML_PATH=/usr/local/share/igphyml/src/motifs \
    STRICT_CONTRACT_ROUTES=true \
    MAKEFLAGS=-j1

RUN set -eux; \
    dnf -y install --setopt=install_weak_deps=False \
      libcurl-devel \
      openssl-devel \
      libxml2-devel \
      libgit2-devel \
      libpng-devel \
      libjpeg-turbo-devel \
      libtiff-devel \
      fontconfig-devel \
      freetype-devel \
      libuv-devel \
      fribidi-devel \
      harfbuzz-devel; \
    dnapars_bin="$(command -v dnapars || true)"; \
    if [ -n "$dnapars_bin" ]; then \
      if [ "$dnapars_bin" != "/usr/local/bin/dnapars" ]; then \
        ln -sf "$dnapars_bin" /usr/local/bin/dnapars; \
      else \
        echo "INFO: dnapars already at /usr/local/bin/dnapars"; \
      fi; \
    else \
      echo 'WARN: dnapars not found in base image'; \
    fi; \
    dnf clean all; \
    rm -rf /var/cache/dnf

RUN DOWNLOAD_STATIC_LIBV8=1 R -q -e "install.packages( \
    c('plumber', 'jsonlite', 'httpuv', 'swagger', 'jsonvalidate', 'httr', 'ape', 'igraph', 'remotes'), \
    repos = 'https://packagemanager.posit.co/cran/2026-07-20', \
    Ncpus = 1 \
    )" \
    && R -q -e "install.packages('BiocManager', repos = 'https://packagemanager.posit.co/cran/2026-07-20'); \
    bioc_deps <- c('Biostrings','msa','GenomicRanges','GenomicAlignments'); \
    BiocManager::install(bioc_deps, ask = FALSE, update = FALSE, Ncpus = 1); \
    stopifnot(all(bioc_deps %in% rownames(installed.packages())))"

# Pre-install BrepPhylo Imports in a separate layer so R CMD INSTALL does not
# run in the same RUN as the full transitive dependency tree. On ~6GB hosts,
# that combined step OOM'd with "Cannot fork (ENOMEM)".
RUN R -q -e " \
    cran_repo <- 'https://packagemanager.posit.co/cran/2026-07-20'; \
    cran_deps <- c('bio3d','ggmuller','phytools','plyr','reticulate','seqinr','adephylo'); \
    dep_types <- c('Depends', 'Imports', 'LinkingTo'); \
    install.packages(cran_deps, repos = cran_repo, dependencies = dep_types, Ncpus = 1); \
    stopifnot(all(cran_deps %in% rownames(installed.packages()))); \
    stopifnot('alakazam' %in% rownames(installed.packages())) \
    " \
    && rm -rf /tmp/Rtmp* /root/.cache/R

# Install BrepPhylo via codeload tarball + R CMD INSTALL, NOT install_github.
# install_github goes through api.github.com which is rate-limited to 60 req/hr
# for unauthenticated users — Docker build retries silently exhausted the quota.
# codeload.github.com serves the raw tarball via CDN, no rate limit.
ARG BREPPHYLO_COMMIT=7c52fb66e28ee3839a32633bf809f320f060c876
COPY install_brepphylo.R /tmp/install_brepphylo.R
RUN curl -fsSL -o /tmp/brepphylo.tar.gz \
      "https://codeload.github.com/Fraternalilab/BrepPhylo/tar.gz/${BREPPHYLO_COMMIT}" \
    && BREPPHYLO_TARBALL=/tmp/brepphylo.tar.gz R -q -f /tmp/install_brepphylo.R \
    && rm -rf /tmp/brepphylo.tar.gz /tmp/install_brepphylo.R /tmp/Rtmp*

# paws.storage + digest installed AFTER BrepPhylo so they don't interfere with the
# upstream install chain. Required by services/brepphylo/object_storage.R to
# upload artifact files directly to MinIO.
RUN R -q -e "install.packages(c('paws.storage', 'digest'), repos = 'https://packagemanager.posit.co/cran/2026-07-20', Ncpus = 1); \
    stopifnot(all(c('paws.storage', 'digest') %in% rownames(installed.packages())))"

WORKDIR /srv
COPY validators.R /srv/validators.R
COPY plumber.R /srv/plumber.R
COPY job_manager.R /srv/job_manager.R
COPY job_runner.R /srv/job_runner.R
COPY artifact_manifest.R /srv/artifact_manifest.R
COPY object_storage.R /srv/object_storage.R

EXPOSE 8003

CMD ["R", "-q", "-e", "pr <- plumber::plumb('/srv/plumber.R'); pr$run(host='0.0.0.0', port=8003)"]
