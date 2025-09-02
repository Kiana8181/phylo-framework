# services/dowser/Dockerfile
FROM rocker/r-ver:4.3.3
ENV DEBIAN_FRONTEND=noninteractive

# System deps (added libv8-dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcurl4-openssl-dev libssl-dev libxml2-dev libgit2-dev \
    libfontconfig1-dev libfreetype6-dev libharfbuzz-dev libfribidi-dev \
    libpng-dev libtiff5-dev libjpeg-dev libcairo2-dev libxt-dev \
    zlib1g-dev libbz2-dev liblzma-dev libsodium-dev pkg-config libicu-dev \
    libv8-dev make g++ && rm -rf /var/lib/apt/lists/*

# Pin CRAN globally
RUN echo "options(repos='https://cloud.r-project.org')" >> /usr/local/lib/R/etc/Rprofile.site

# Base CRAN packages
RUN install2.r --error --skipinstalled --ncpus 4 \
    remotes BiocManager ape phangorn airr \
    ggplot2 dplyr tidyr tibble stringr jsonlite httpuv swagger \
    V8 jsonvalidate

# Bioconductor stack needed by alakazam/shazam/ggtree
RUN R -q -e "BiocManager::install(c( \
    'S4Vectors','IRanges','XVector','Biostrings','GenomeInfoDb', \
    'GenomicRanges','Rhtslib','Rsamtools','GenomicAlignments', \
    'treeio','ggtree' \
    ), ask=FALSE, update=FALSE)"

# CRAN packages that depend on the Bioc stack
RUN install2.r --error --skipinstalled --ncpus 4 \
    sodium plumber alakazam shazam dowser

# Quick verification at build time (fix: use library(jsonvalidate))
RUN R -q -e "library(plumber); library(dowser); library(alakazam); library(ggtree); library(jsonvalidate); cat('OK\\n')"

# App
WORKDIR /srv
COPY plumber.R /srv/plumber.R

# Optionally copy contracts in if your build context is repo root:
# COPY packages/contracts /srv/contracts
# ENV CONTRACTS_DIR=/srv/contracts

EXPOSE 8001
CMD ["R", "-q", "-e", "pr <- plumber::plumb('/srv/plumber.R'); pr$run(host='0.0.0.0', port=8001)"]
