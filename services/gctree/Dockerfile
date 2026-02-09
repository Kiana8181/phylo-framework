# services/gctree/Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    QT_QPA_PLATFORM=offscreen \
    MPLBACKEND=agg \
    XDG_RUNTIME_DIR=/tmp/runtime-gctree \
    CONTRACTS_DIR=/contracts

# System deps: PHYLIP provides dnapars; plus fonts for matplotlib SVG. :contentReference[oaicite:14]{index=14}
RUN apt-get update && apt-get install -y --no-install-recommends \
    phylip ca-certificates curl tini fonts-dejavu-core \
    python3-pyqt5 libgl1 libxcb-xinerama0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY sitecustomize.py /usr/local/lib/python3.12/site-packages/sitecustomize.py
COPY app.py /srv/app.py

EXPOSE 8002
ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8002"]
