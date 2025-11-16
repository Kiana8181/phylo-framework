FROM rocker/r-ver:4.3.3

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libgit2-dev \
    libpng-dev \
    libjpeg-dev \
    libtiff5-dev \
    libfontconfig1-dev \
    libfreetype6-dev \
    phylip && \
    ln -s /usr/lib/phylip/bin/dnapars /usr/local/bin/dnapars && \
    rm -rf /var/lib/apt/lists/*

RUN R -e "install.packages(c('remotes','plumber','jsonlite','ape','igraph'), repos='https://cloud.r-project.org')" && \
    R -e "install.packages('BiocManager', repos='https://cloud.r-project.org'); BiocManager::install(c('Biostrings','msa','GenomicRanges','GenomicAlignments'), ask = FALSE)" && \
    R -e \"remotes::install_github('Fraternalilab/BrepPhylo', dependencies = TRUE)\"

ENV CONTRACTS_DIR=/contracts
ENV DNAPARS_PATH=/usr/local/bin/dnapars

WORKDIR /app
COPY plumber.R /app/plumber.R

EXPOSE 8003

CMD ["R", "-e", "pr <- plumber::plumb('plumber.R'); pr$run(host='0.0.0.0', port=8003)"]
