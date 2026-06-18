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
      ca-certificates \
      curl \
      git \
      build-essential \
      make \
      g++ \
      python3; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "$arch" in \
      amd64|x86_64|arm64|aarch64) \
        # Build MUSCLE from source on all Linux arches. Prebuilt v5.3 linux
        # binaries pass -version but can fail -align on some amd64 hosts (AVX
        # / CPU quirks); arm64 prebuilts are also known-broken upstream.
        git clone --branch "v${MUSCLE_VERSION}" --depth 1 \
          https://github.com/rcedgar/muscle.git /tmp/muscle-src; \
        ( \
          cd /tmp/muscle-src/src; \
          if [ "$arch" = "arm64" ] || [ "$arch" = "aarch64" ]; then \
            export CFLAGS="-D__arm64__"; \
          fi; \
          bash build_linux.bash; \
          test -x ../bin/muscle \
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
    printf '>a\nACDEF\n>b\nACDEFG\n' >/tmp/muscle-smoke.fa; \
    muscle -align /tmp/muscle-smoke.fa -output /tmp/muscle-smoke.aln -amino; \
    test -s /tmp/muscle-smoke.aln; \
    rm -rf /var/lib/apt/lists/* /tmp/muscle.version.txt /tmp/muscle-smoke.fa /tmp/muscle-smoke.aln

WORKDIR /srv/clonaltree

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY app.py /srv/clonaltree/app.py
COPY job_manager.py /srv/clonaltree/job_manager.py
COPY job_runner.py /srv/clonaltree/job_runner.py
COPY artifact_manifest.py /srv/clonaltree/artifact_manifest.py
COPY object_storage.py /srv/clonaltree/object_storage.py
COPY base-codes /srv/clonaltree/base-codes
RUN test -f /srv/clonaltree/base-codes/main_pipeline.py || \
    (echo "Missing clonaltree submodule content. Run: git submodule update --init --recursive" >&2 && exit 1)

EXPOSE 8004

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8004"]
