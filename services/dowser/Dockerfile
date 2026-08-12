FROM immcantation/suite:4.6.0

ENV DEBIAN_FRONTEND=noninteractive \
    CONTRACTS_DIR=/contracts \
    DNAPARS_PATH=/usr/local/bin/dnapars \
    DNAML_PATH=/usr/local/bin/dnaml \
    RAXML_BIN=/usr/local/bin/raxml-ng \
    IGPHYML_BIN=/usr/local/share/igphyml/src/igphyml \
    IGPHYML_MOTIFS=/usr/local/share/igphyml/src/motifs \
    IGPHYML_PATH=/usr/local/share/igphyml/src/motifs \
    STRICT_CONTRACT_ROUTES=true \
    MAKEFLAGS=-j1 \
    DOWNLOAD_STATIC_LIBV8=1

RUN set -eux; \
    dnf -y \
      --disablerepo='*openh264*' \
      --setopt=install_weak_deps=False \
      install \
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
      harfbuzz-devel \
      v8-devel \
      nodejs-devel \
      wget \
      tar \
      gzip \
      unzip; \
    for tool in dnapars dnaml; do \
      bin_path="$$(command -v "$$tool" || true)"; \
      if [ -n "$$bin_path" ] && [ "$$bin_path" != "/usr/local/bin/$$tool" ]; then \
        ln -sf "$$bin_path" "/usr/local/bin/$$tool"; \
      fi; \
    done; \
    if ! command -v raxml-ng >/dev/null 2>&1; then \
      mkdir -p /tmp/raxml-ng; \
      cd /tmp/raxml-ng; \
      wget -q https://github.com/amkozlov/raxml-ng/releases/download/1.2.2/raxml-ng_v1.2.2_linux_x86_64.zip; \
      unzip -q raxml-ng_*.zip; \
      install -m 0755 raxml-ng /usr/local/bin/raxml-ng; \
      cd /; \
      rm -rf /tmp/raxml-ng; \
    fi; \
    dnf clean all; \
    rm -rf /var/cache/dnf

RUN R -q -e "\
    cran_repo <- 'https://packagemanager.posit.co/cran/2026-07-20'; \
    install.packages( \
      c('V8', 'promises', 'later', 'webutils', 'sodium', \
        'plumber', 'jsonlite', 'httpuv', 'swagger', \
        'jsonvalidate', 'httr', 'ape', 'phangorn', 'remotes'), \
      repos=cran_repo, \
      Ncpus=1 \
    ); \
    install.packages('BiocManager', repos=cran_repo, Ncpus=1); \
    BiocManager::install( \
      c('Biostrings', 'ggtree', 'pwalign'), \
      ask=FALSE, \
      update=FALSE, \
      Ncpus=1 \
    ); \
    install.packages( \
      c('paws.storage', 'digest'), \
      repos=cran_repo, \
      Ncpus=1 \
    ); \
    install.packages( \
      c('alakazam', 'dowser'), \
      repos=cran_repo, \
      Ncpus=1, \
      dependencies=TRUE \
    ); \
    stopifnot( \
      as.character(packageVersion('dowser')) == '2.4.1', \
      as.character(packageVersion('alakazam')) == '1.4.3', \
      as.character(packageVersion('ape')) == '5.8.1', \
      as.character(packageVersion('phangorn')) == '2.12.1', \
      requireNamespace('pwalign') \
    ) \
    " \
    && rm -rf /tmp/Rtmp* /root/.cache/R

WORKDIR /srv

COPY validators.R \
     data_io.R \
     format_clones.R \
     tree_build.R \
     dta.R \
     time_evolution.R \
     internal_seqs.R \
     exports.R \
     handlers.R \
     plumber.R \
     job_manager.R \
     job_runner.R \
     artifact_manifest.R \
     object_storage.R \
     /srv/

EXPOSE 8001

CMD ["R", "-q", "-e", "pr <- plumber::plumb('/srv/plumber.R'); pr$run(host='0.0.0.0', port=8001)"]