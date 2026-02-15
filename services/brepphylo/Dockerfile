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
      freetype-devel; \
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
    repos = 'https://cloud.r-project.org' \
    )" \
    && R -q -e "install.packages('BiocManager', repos = 'https://cloud.r-project.org'); \
    BiocManager::install(c('Biostrings','msa','GenomicRanges','GenomicAlignments'), ask = FALSE)" \
    && R -q -e "remotes::install_github('Fraternalilab/BrepPhylo', dependencies = TRUE)"

WORKDIR /srv
COPY plumber.R /srv/plumber.R

EXPOSE 8003

CMD ["R", "-q", "-e", "pr <- plumber::plumb('/srv/plumber.R'); pr$run(host='0.0.0.0', port=8003)"]
