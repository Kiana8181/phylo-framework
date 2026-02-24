FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONTRACTS_DIR=/contracts \
    STRICT_CONTRACT_ROUTES=true \
    QT_QPA_PLATFORM=offscreen \
    MPLBACKEND=agg \
    CLONOTYPE_PINNED_TAG=1.0.0 \
    CLONOTYPE_PINNED_SHA=cf731d37ead6c15bcbad2c96ef4c76b6d4f19edf \
    CLONALTREE_IMAGE_REF=phylo-clonaltree:dev

ARG TARGETARCH
ARG MUSCLE_VERSION=5.3

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      make \
      g++ \
      curl \
      ca-certificates && \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}" && \
    if [ "$arch" = "amd64" ]; then muscle_asset="muscle-linux-x86.v${MUSCLE_VERSION}"; \
    elif [ "$arch" = "arm64" ]; then muscle_asset="muscle-aarch64.v${MUSCLE_VERSION}"; \
    else echo "Unsupported architecture for MUSCLE install: $arch" >&2; exit 1; fi && \
    curl -fsSL -o /usr/local/bin/muscle \
      "https://github.com/rcedgar/muscle/releases/download/v${MUSCLE_VERSION}/${muscle_asset}" && \
    chmod 0755 /usr/local/bin/muscle && \
    muscle -version >/tmp/muscle.version.txt 2>&1 && \
    grep -Eiq '(version[[:space:]]*5|muscle[[:space:]]+5|v5\\.)' /tmp/muscle.version.txt && \
    rm -rf /var/lib/apt/lists/* /tmp/muscle.version.txt

WORKDIR /srv/clonaltree

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY app.py /srv/clonaltree/app.py
COPY base-codes /srv/clonaltree/base-codes
RUN test -f /srv/clonaltree/base-codes/main_pipeline.py || \
    (echo "Missing clonaltree submodule content. Run: git submodule update --init --recursive" >&2 && exit 1)

EXPOSE 8004

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8004"]
