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
      muscle \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /srv/clonaltree

COPY services/clonaltree/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY services/clonaltree/app.py /srv/clonaltree/app.py
COPY services/clonaltree/base-codes /srv/clonaltree/base-codes

EXPOSE 8004

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8004"]
