FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONTRACTS_DIR=/contracts \
    STRICT_CONTRACT_ROUTES=true \
    QT_QPA_PLATFORM=offscreen \
    MPLBACKEND=agg

ARG TARGETARCH

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      make \
      g++ \
      curl \
      ca-certificates && \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}" && \
    if [ "$arch" = "amd64" ]; then \
      curl -fsSL -o /tmp/muscle3.tgz https://drive5.com/muscle/downloads3.8.31/muscle3.8.31_i86linux64.tar.gz && \
      tar -xzf /tmp/muscle3.tgz -C /tmp && \
      install -m 0755 /tmp/muscle3.8.31_i86linux64 /usr/local/bin/muscle; \
    elif [ "$arch" = "arm64" ]; then \
      curl -fsSL -o /tmp/muscle3src.tgz https://drive5.com/muscle/downloads3.8.31/muscle3.8.31_src.tar.gz && \
      tar -xzf /tmp/muscle3src.tgz -C /tmp && \
      sed -i 's/-msse2 -mfpmath=sse //g' /tmp/muscle3.8.31/src/mk && \
      make -C /tmp/muscle3.8.31/src && \
      install -m 0755 /tmp/muscle3.8.31/src/muscle /usr/local/bin/muscle; \
    else \
      echo "Unsupported architecture for MUSCLE install: $arch" >&2; \
      exit 1; \
    fi && \
    rm -rf /var/lib/apt/lists/* /tmp/muscle3.tgz /tmp/muscle3src.tgz /tmp/muscle3.8.31 /tmp/muscle3.8.31_i86linux64

WORKDIR /srv/clonaltree

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY app.py /srv/clonaltree/app.py
COPY base-codes /srv/clonaltree/base-codes

EXPOSE 8004

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8004"]
