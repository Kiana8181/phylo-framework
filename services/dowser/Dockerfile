# services/dowser/Dockerfile
FROM rocker/r-ver:4.3.3

# system deps needed by ggtree/graphics/etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcurl4-openssl-dev libssl-dev libxml2-dev libgit2-dev \
    libfontconfig1-dev libfreetype6-dev libharfbuzz-dev libfribidi-dev \
    libpng-dev libtiff5-dev libjpeg-dev libcairo2-dev libxt-dev \
    make g++ && rm -rf /var/lib/apt/lists/*

# R packages: plumber + dowser and its deps (Bioconductor for ggtree/Biostrings)
RUN R -q -e "install.packages(c('plumber','remotes','BiocManager','ape','phangorn','airr','alakazam','shazam'), repos='https://cloud.r-project.org')"
RUN R -q -e "BiocManager::install(c('Biostrings','ggtree'), ask=FALSE, update=FALSE)"
RUN R -q -e "install.packages('dowser', repos='https://cloud.r-project.org')"

# app
WORKDIR /srv
COPY plumber.R /srv/plumber.R

EXPOSE 8001
CMD ["R", "-q", "-e", "pr <- plumber::plumb('/srv/plumber.R'); pr$run(host='0.0.0.0', port=8001)"]
