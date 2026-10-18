FROM immcantation/suite:4.6.0

ENV DEBIAN_FRONTEND=noninteractive \
    CONTRACTS_DIR=/contracts \
    DNAPARS_PATH=/usr/local/bin/dnapars \
    IGPHYML_BIN=/usr/local/share/igphyml/src/igphyml \
    IGPHYML_MOTIFS=/usr/local/share/igphyml/src/motifs \
    IGPHYML_PATH=/usr/local/share/igphyml/src/motifs \
    STRICT_CONTRACT_ROUTES=true

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
    repos = 'https://packagemanager.posit.co/cran/2026-07-20' \
    )" \
    && R -q -e "install.packages('BiocManager', repos = 'https://packagemanager.posit.co/cran/2026-07-20'); \
    bioc_deps <- c('Biostrings','msa','GenomicRanges','GenomicAlignments'); \
    BiocManager::install(bioc_deps, ask = FALSE, update = FALSE); \
    stopifnot(all(bioc_deps %in% rownames(installed.packages())))"

# Install BrepPhylo via codeload tarball + install_local, NOT install_github.
# install_github goes through api.github.com which is rate-limited to 60 req/hr
# for unauthenticated users — Docker build retries silently exhausted the quota.
# codeload.github.com serves the raw tarball via CDN, no rate limit. stopifnot
# at the end fails the build loudly if BrepPhylo somehow didn't install.
ARG BREPPHYLO_COMMIT=7c52fb66e28ee3839a32633bf809f320f060c876
RUN curl -fsSL -o /tmp/brepphylo.tar.gz \
      "https://codeload.github.com/Fraternalilab/BrepPhylo/tar.gz/${BREPPHYLO_COMMIT}" \
    && R -q -e "stopifnot('msa' %in% rownames(installed.packages())); \
                remotes::install_local('/tmp/brepphylo.tar.gz', dependencies = TRUE, upgrade = 'never'); \
                stopifnot('BrepPhylo' %in% rownames(installed.packages()))" \
    && rm -f /tmp/brepphylo.tar.gz

# paws.storage + digest installed AFTER BrepPhylo so they don't interfere with the
# upstream install chain. Required by services/brepphylo/object_storage.R to
# upload artifact files directly to MinIO.
RUN R -q -e "install.packages(c('paws.storage', 'digest'), repos = 'https://packagemanager.posit.co/cran/2026-07-20'); \
    stopifnot(all(c('paws.storage', 'digest') %in% rownames(installed.packages())))"

# Security updates published for the base image's distribution since the base
# image was built. `--security` limits this to packages with a security
# advisory, so R and the scientific tools keep the versions the base image
# ships. Kept as the last system layer so the expensive layers above stay
# cached.
RUN dnf -y upgrade --security --setopt=install_weak_deps=False \
    && dnf clean all \
    && rm -rf /var/cache/dnf

# The base image's Python ships pyarrow 19.0.1 (CVE-2026-25087). Nothing here
# depends on it; raise it to the first fixed release, touching nothing else.
RUN python3 -m pip install --no-cache-dir --no-deps pyarrow==23.0.1

WORKDIR /srv
COPY validators.R /srv/validators.R
COPY plumber.R /srv/plumber.R
COPY resource_limits.R /srv/resource_limits.R
COPY job_manager.R /srv/job_manager.R
COPY job_runner.R /srv/job_runner.R
COPY artifact_manifest.R /srv/artifact_manifest.R
COPY object_storage.R /srv/object_storage.R

EXPOSE 8003

CMD ["R", "-q", "-e", "pr <- plumber::plumb('/srv/plumber.R'); pr$run(host='0.0.0.0', port=8003)"]
