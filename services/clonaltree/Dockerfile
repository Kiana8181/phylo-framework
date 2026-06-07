FROM python:3.10-slim-bookworm

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

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      curl \
      ca-certificates; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "$arch" in \
      amd64|x86_64) \
        muscle_asset="muscle-linux-x86.v${MUSCLE_VERSION}"; \
        curl -fsSL -o /usr/local/bin/muscle \
          "https://github.com/rcedgar/muscle/releases/download/v${MUSCLE_VERSION}/${muscle_asset}"; \
        chmod 0755 /usr/local/bin/muscle; \
        ;; \
      arm64|aarch64) \
        # Upstream Linux arm64 binaries are broken in v5.2/v5.3.
        # Build from source and force arm64 macro because upstream checks
        # __arm64__ (not __aarch64__) when setting BITS.
        apt-get install -y --no-install-recommends \
          git \
          build-essential \
          make \
          g++ \
          python3; \
        git clone --branch "v${MUSCLE_VERSION}" --depth 1 \
          https://github.com/rcedgar/muscle.git /tmp/muscle-src; \
        ( \
          cd /tmp/muscle-src/src; \
          export CFLAGS="-D__arm64__"; \
          bash build_linux.bash \
        ); \
        install -m 0755 /tmp/muscle-src/bin/muscle /usr/local/bin/muscle; \
        rm -rf /tmp/muscle-src; \
        ;; \
      *) echo "Unsupported architecture for MUSCLE install: $arch" >&2; exit 1 ;; \
    esac; \
    if ! muscle -version >/tmp/muscle.version.txt 2>&1; then \
      cat /tmp/muscle.version.txt >&2; \
      exit 1; \
    fi; \
    grep -Eiq '(version[[:space:]]*5|muscle[[:space:]]+v?5|v5\.)' /tmp/muscle.version.txt || { \
      cat /tmp/muscle.version.txt >&2; \
      exit 1; \
    }; \
    rm -rf /var/lib/apt/lists/* /tmp/muscle.version.txt

WORKDIR /srv/clonaltree

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY app.py /srv/clonaltree/app.py
COPY job_manager.py /srv/clonaltree/job_manager.py
COPY job_runner.py /srv/clonaltree/job_runner.py
COPY base-codes /srv/clonaltree/base-codes
RUN test -f /srv/clonaltree/base-codes/main_pipeline.py || \
    (echo "Missing clonaltree submodule content. Run: git submodule update --init --recursive" >&2 && exit 1)

EXPOSE 8004

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8004"]
