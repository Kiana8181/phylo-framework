FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONTRACTS_DIR=/contracts \
    STRICT_CONTRACT_ROUTES=true \
    QT_QPA_PLATFORM=offscreen \
    MPLBACKEND=agg

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      curl \
      ca-certificates && \
    curl -L -o /tmp/muscle3.tgz https://drive5.com/muscle/downloads3.8.31/muscle3.8.31_i86linux64.tar.gz && \
    tar -xzf /tmp/muscle3.tgz -C /tmp && \
    install -m 0755 /tmp/muscle3.8.31_i86linux64 /usr/local/bin/muscle && \
    rm -rf /var/lib/apt/lists/* /tmp/muscle3.tgz /tmp/muscle3.8.31_i86linux64

WORKDIR /srv/clonaltree

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY app.py /srv/clonaltree/app.py
COPY base-codes /srv/clonaltree/base-codes

EXPOSE 8004

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8004"]
