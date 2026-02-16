#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$ROOT/.venv/bin/python"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

if [[ ! -x "$PYTHON_BIN" ]]; then
  die "Missing $PYTHON_BIN. Create/install the API venv first (see README)."
fi

raw_storage="${STORAGE_LOCAL_PATH:-runtime/storage}"
if [[ "$raw_storage" = /* ]] || [[ "$raw_storage" =~ ^[A-Za-z]:[\\/].* ]]; then
  host_storage="$raw_storage"
else
  host_storage="$ROOT/$raw_storage"
fi

# If not set, or accidentally set to the container mount path, point host
# runtime root at the host storage directory.
if [[ -z "${HOST_RUNTIME_SHARED_ROOT:-}" ]] || [[ "${HOST_RUNTIME_SHARED_ROOT}" == "/runtime/storage"* ]]; then
  export HOST_RUNTIME_SHARED_ROOT="$host_storage"
fi

mkdir -p "$host_storage"

exec "$PYTHON_BIN" -m uvicorn apps.api.main:app --reload --host 0.0.0.0 --port "${API_PORT:-8000}"
