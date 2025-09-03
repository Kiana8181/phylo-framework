# apps/api/Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl tini && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# Copy requirements early for better caching
COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy repo
COPY . /srv

# Ensure package-style imports (apps.api) work
ENV PYTHONPATH=/srv

# Default runtime env (overridden in compose)
ENV CONTRACTS_DIR=packages/contracts \
    CORS_ORIGINS=http://localhost:3000

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["uvicorn","apps.api.main:app","--host","0.0.0.0","--port","8000"]
