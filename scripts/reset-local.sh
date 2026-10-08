#!/usr/bin/env bash
#
# Clean-slate reset for LOCAL development.
#
# Project-scoped and safe: it only removes THIS docker-compose project's
# containers + named volumes (phylo_postgres_data, phylo_minio_data) and the project-local
# ./runtime staging folders. It never runs `docker volume prune` and never
# touches unrelated files or volumes.
#
# Usage:  bash ./scripts/reset-local.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
# Base file + dev override (host ports for Postgres/MinIO); see docker-compose.dev.yml.
COMPOSE_DEV=(docker compose -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.dev.yml" --profile dev)

echo "This will DESTROY local development state for the project at:"
echo "  $ROOT"
echo
echo "It will:"
echo "  1. stop this project's containers (docker compose down)"
echo "  2. remove this project's named volumes: phylo_postgres_data, phylo_minio_data"
echo "  3. delete project runtime folders: ./runtime/storage ./runtime/method-jobs"
echo "  4. rebuild + start the clean dev stack (MinIO buckets auto-created)"
echo "  5. run the storage connectivity check"
echo
read -r -p "Type 'reset' to continue: " CONFIRM
if [ "$CONFIRM" != "reset" ]; then
  echo "Aborted."
  exit 1
fi

echo "==> Stopping containers and removing project-scoped named volumes..."
# `down -v` removes ONLY the volumes declared in this compose project.
"${COMPOSE_DEV[@]}" down -v --remove-orphans

echo "==> Removing project runtime/staging folders (gitignored, project-local)..."
rm -rf "$ROOT/runtime/storage" "$ROOT/runtime/method-jobs"

echo "==> Building and starting the clean dev stack..."
"${COMPOSE_DEV[@]}" up -d --build

echo "==> Waiting for the API to apply migrations and become healthy..."
# The dev `api` service runs `alembic upgrade head` on start; give it a moment.
sleep 8

echo "==> Verifying object storage connectivity + buckets..."
node ./scripts/storage-check.mjs --docker || {
  echo "Storage check failed. Inspect: docker compose logs minio minio-init api"
  exit 1
}

echo
echo "Reset complete. Stack is up with a fresh database and empty MinIO buckets."
