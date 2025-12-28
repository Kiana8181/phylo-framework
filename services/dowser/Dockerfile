FROM immcantation/suite:4.6.0

ENV DEBIAN_FRONTEND=noninteractive
ENV CONTRACTS_DIR=/contracts
ENV IGPHYML_BIN=/usr/local/bin/igphyml
ENV IGPHYML_MOTIFS=/usr/local/share/igphyml/src/motifs
ENV IGPHYML_PATH=/usr/local/share/igphyml/src/motifs

RUN DOWNLOAD_STATIC_LIBV8=1 R -q -e "install.packages( \
    c('plumber', 'jsonlite', 'httpuv', 'swagger', 'jsonvalidate', 'httr'), \
    repos = 'https://cloud.r-project.org' \
    ); \
    stopifnot('jsonvalidate' %in% rownames(installed.packages()))"

WORKDIR /srv
COPY plumber.R /srv/plumber.R
EXPOSE 8001

CMD ["R", "-q", "-e", "pr <- plumber::plumb('/srv/plumber.R'); pr$run(host='0.0.0.0', port=8001)"]
