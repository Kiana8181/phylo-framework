FROM immcantation/suite:4.6.0

ENV DEBIAN_FRONTEND=noninteractive \
    CONTRACTS_DIR=/contracts \
    DNAPARS_PATH=/usr/local/bin/dnapars \
    DNAML_PATH=/usr/local/bin/dnaml \
    RAXML_BIN=/usr/local/bin/raxml-ng \
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
      wget \
      tar \
      gzip \
      texlive-scheme-basic \
      texlive-collection-latex \
      texlive-collection-latexrecommended \
      texlive-collection-latexextra \
      texlive-collection-fontsrecommended \
      texlive-latexmk || true; \
    for tool in dnapars dnaml; do \
      bin_path="$(command -v $tool || true)"; \
      if [ -n "$bin_path" ] && [ "$bin_path" != "/usr/local/bin/$tool" ]; then \
        ln -sf "$bin_path" "/usr/local/bin/$tool"; \
      fi; \
    done; \
    if ! command -v raxml-ng >/dev/null 2>&1; then \
      mkdir -p /tmp/raxml-ng && cd /tmp/raxml-ng; \
      wget -q https://github.com/amkozlov/raxml-ng/releases/download/1.2.2/raxml-ng_v1.2.2_linux_x86_64.zip || \
        wget -q https://github.com/amkozlov/raxml-ng/releases/download/1.1.0/raxml-ng_v1.1.0_linux_x86_64.zip; \
      unzip -q raxml-ng_*.zip || true; \
      if [ -f raxml-ng ]; then install -m 0755 raxml-ng /usr/local/bin/raxml-ng; fi; \
      cd / && rm -rf /tmp/raxml-ng; \
    fi; \
    if ! command -v pdflatex >/dev/null 2>&1; then \
      R -q -e "install.packages('tinytex', repos='https://cloud.r-project.org'); tinytex::install_tinytex()" || true; \
    fi; \
    dnf clean all; \
    rm -rf /var/cache/dnf

RUN DOWNLOAD_STATIC_LIBV8=1 R -q -e "install.packages( \
    c('plumber', 'jsonlite', 'httpuv', 'swagger', 'jsonvalidate', 'httr', 'ape', 'phangorn', 'remotes'), \
    repos = 'https://cloud.r-project.org' \
    ); \
    install.packages('BiocManager', repos = 'https://cloud.r-project.org'); \
    BiocManager::install(c('Biostrings', 'ggtree'), ask = FALSE); \
    stopifnot('jsonvalidate' %in% rownames(installed.packages()))"

RUN R -q -e "install.packages(c('paws.storage', 'digest'), repos = 'https://cloud.r-project.org'); \
    stopifnot(all(c('paws.storage', 'digest') %in% rownames(installed.packages())))"

WORKDIR /srv
COPY validators.R data_io.R format_clones.R tree_build.R dta.R time_evolution.R internal_seqs.R exports.R handlers.R plumber.R job_manager.R job_runner.R artifact_manifest.R object_storage.R /srv/

EXPOSE 8001

CMD ["R", "-q", "-e", "pr <- plumber::plumb('/srv/plumber.R'); pr$run(host='0.0.0.0', port=8001)"]
