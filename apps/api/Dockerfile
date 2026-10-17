# apps/api/Dockerfile
#
# Build context: the repository root. Optional named context `gitmeta`: the
# repository's .git directory (docker-compose.yml passes it), from which the
# image records which commit it was built from. `.git` is not part of the
# build context (.dockerignore), hence the separate context.

# Without a `gitmeta` context this empty stage stands in for it: the build
# still works and the image records that it was not built from a git checkout.
FROM scratch AS gitmeta

# Deployment identity (commit, image names, pinned tool versions), written once
# per build. Only the three small things git needs to name HEAD are copied;
# the bracket patterns make each of them optional.
FROM python:3.12-slim AS version-info
COPY --from=gitmeta HEA[D] packed-ref[s] /gitmeta/
COPY --from=gitmeta ref[s] /gitmeta/refs/
ARG PHYLO_METHOD_IMAGE_TAG=latest
RUN --mount=type=bind,target=/src,readonly \
    python /src/scripts/generate_version_info.py --root /src --git-dir /gitmeta \
        --no-commands --image-tag "${PHYLO_METHOD_IMAGE_TAG}" --out /out/version-info.json

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# `apt-get upgrade` applies the security updates the distribution has published
# since the base image was built: the base image is only as fresh as its last
# pull, and a scan of this image fails on fixable critical findings.
RUN apt-get update && apt-get -y upgrade && apt-get install -y --no-install-recommends \
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

# Last, so a new commit only replaces this one small layer.
COPY --from=version-info /out/version-info.json /version-info.json
ENV PHYLO_VERSION_INFO_PATH=/version-info.json

# The port is configurable (PHYLO_PORT_API in docker-compose.yml); 8000 is the
# default when the image is run on its own.
ENV PORT=8000
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["sh","-c","exec uvicorn apps.api.main:app --host 0.0.0.0 --port \"${PORT}\""]
