# Python 3.12: the newest release the pinned scientific stack supports
# (ete3 3.1.3 imports the `cgi` module, which Python 3.13 removed). It receives
# security fixes until October 2028; Python 3.10 reached end of life in 2026.
ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# --- Build stage -------------------------------------------------------------
# Compiles MUSCLE. The compiler toolchain, git and the kernel headers they pull
# in stay in this stage; only the finished binary is copied to the runtime
# image.
FROM ${PYTHON_IMAGE} AS muscle-build

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
        ;; \
      *) echo "Unsupported architecture for MUSCLE install: $arch" >&2; exit 1 ;; \
    esac

# --- Runtime stage -----------------------------------------------------------
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONTRACTS_DIR=/contracts \
    STRICT_CONTRACT_ROUTES=true \
    QT_QPA_PLATFORM=offscreen \
    MPLBACKEND=agg \
    CLONALTREE_IMAGE_REF=phylo-clonaltree:dev

# Pending Debian security updates; no build tools are installed here.
RUN set -eux; \
    apt-get update; \
    apt-get -y upgrade; \
    rm -rf /var/lib/apt/lists/*

# MUSCLE is linked statically, so the binary runs without the toolchain. The
# checks run in THIS stage: they prove the copied binary works in the image
# that ships, not just in the one that built it.
COPY --from=muscle-build /usr/local/bin/muscle /usr/local/bin/muscle
RUN set -eux; \
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
    rm -f /tmp/muscle.version.txt /tmp/muscle-smoke.fa /tmp/muscle-smoke.aln

WORKDIR /srv/clonaltree

# requirements.lock pins the complete dependency set (direct + indirect), so
# every build installs exactly the versions that were tested and audited.
# Regenerate it with scripts/update-python-locks.sh.
COPY requirements.txt requirements.lock /tmp/
RUN pip install --no-cache-dir --upgrade pip==26.2.1 setuptools==84.0.0 wheel==0.48.0 \
    && pip install --no-cache-dir -r /tmp/requirements.txt -c /tmp/requirements.lock

COPY app.py /srv/clonaltree/app.py
COPY validators.py /srv/clonaltree/validators.py
COPY resource_limits.py /srv/clonaltree/resource_limits.py
COPY sitecustomize.py /srv/clonaltree/sitecustomize.py
COPY job_manager.py /srv/clonaltree/job_manager.py
COPY job_runner.py /srv/clonaltree/job_runner.py
COPY artifact_manifest.py /srv/clonaltree/artifact_manifest.py
COPY object_storage.py /srv/clonaltree/object_storage.py
COPY base-codes /srv/clonaltree/base-codes

EXPOSE 8004

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8004"]
