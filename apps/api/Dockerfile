# apps/api/Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl tini && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# Copy requirements early for better caching.
# requirements.lock pins the complete dependency set (direct + indirect), so
# every build installs exactly the versions that were tested and audited.
# Regenerate it with scripts/update-python-locks.sh.
COPY apps/api/requirements.txt apps/api/requirements.lock ./
RUN pip install --no-cache-dir --upgrade pip==26.2.1 \
    && pip install --no-cache-dir -r requirements.txt -c requirements.lock

# Copy repo
COPY . /srv

# Ensure package-style imports (apps.api) work
ENV PYTHONPATH=/srv

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["uvicorn","apps.api.main:app","--host","0.0.0.0","--port","8000"]
