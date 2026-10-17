#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
# docker-compose.yml publishes no host ports; the dev override adds the Postgres
# and MinIO ports that the host-run API, worker and method containers need.
COMPOSE_DEV=(docker compose -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.dev.yml" --profile dev)

RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; BLU=$'\033[34m'; CLR=$'\033[0m'
die(){ echo "${RED}ERROR:${CLR} $*" >&2; exit 1; }
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Missing '$1'. Please install it."; }

npm_major(){ local v; v=$(npm -v 2>/dev/null || echo "0"); echo "${v%%.*}"; }

port_busy(){
  local p="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -Pi :"$p" -sTCP:LISTEN -t >/dev/null
  elif command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$p" | tail -n +2 | grep -q .
  elif command -v netstat >/dev/null 2>&1; then
    if [[ "$(uname -s)" == "Darwin" ]]; then
      netstat -anv -p tcp 2>/dev/null | grep -Eq "[\\.:]$p[[:space:]].*LISTEN"
    else
      netstat -tuln 2>/dev/null | grep -q ":$p "
    fi
  else
    return 1
  fi
}

wait_http(){
  local port="$1" i
  for i in {1..120}; do
    if curl -fsS "http://127.0.0.1:${port}/docs" >/dev/null || \
       curl -fsS "http://localhost:${port}/docs" >/dev/null || \
       curl -fsS "http://127.0.0.1:${port}/spec" >/dev/null || \
       curl -fsS "http://localhost:${port}/spec" >/dev/null || \
       curl -fsS "http://127.0.0.1:${port}/__docs__/" >/dev/null || \
       curl -fsS "http://localhost:${port}/__docs__/" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_postgres(){
  local i
  for i in {1..90}; do
    if [[ "$(docker inspect -f '{{.State.Health.Status}}' phylo-postgres 2>/dev/null || true)" == "healthy" ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

ensure_node_deps_and_build_contracts(){
  local NPM_MAJ; NPM_MAJ=$(npm_major)
  echo "${BLU}==> npm version: $(npm -v 2>/dev/null || echo unknown)${CLR}"
  if [[ "$NPM_MAJ" -lt 7 ]]; then
    if grep -q '"@phylo/contracts"[[:space:]]*:[[:space:]]*"workspace:\*"' "$ROOT/apps/web/package.json" 2>/dev/null; then
      die "Your npm ($NPM_MAJ.x) does not support \"workspace:*\".
Either upgrade npm (npm i -g npm@latest) or set:
  apps/web/package.json -> \"@phylo/contracts\": \"file:../../packages/contracts\""
    fi
    echo "${YLW}npm < 7 detected. Using plain 'npm i'.${CLR}"
    (cd "$ROOT" && npm i)
    echo "${BLU}==> Building @phylo/contracts (non-workspace path)${CLR}"
    (cd "$ROOT/packages/contracts" && npm run build) || echo "${YLW}(contracts build skipped or failed)${CLR}"
  else
    echo "${BLU}==> Installing deps with workspaces${CLR}"
    (cd "$ROOT" && npm i --workspaces)
    echo "${BLU}==> Building @phylo/contracts (workspace)${CLR}"
    (cd "$ROOT" && npm -w @phylo/contracts run build) || echo "${YLW}(contracts build skipped or failed)${CLR}"
  fi
}

method_host_ports(){
  node -e 'const fs=require("fs"); const p=require("path"); const cfg=JSON.parse(fs.readFileSync(p.join(process.argv[1],"config","method-services.json"),"utf8")); for (const s of cfg.services||[]) console.log(String(s.port));' "$ROOT"
}

load_root_env(){
  [[ -f "$ENV_FILE" ]] || die "Root .env not found at $ENV_FILE. Run: node scripts/method-services.mjs sync-env"
  while IFS= read -r -d '' kv; do
    export "$kv"
  done < <(python3 - "$ENV_FILE" <<'PY'
import re
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    for raw in f:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        val = val.strip()
        if len(val) >= 2 and ((val[0] == val[-1] == '"') or (val[0] == val[-1] == "'")):
            val = val[1:-1]
        print(f"{key}={val}", end="\0")
PY
)
}

resolve_storage_abs(){
  local raw="${STORAGE_LOCAL_PATH:-runtime/storage}"
  if [[ "$raw" = /* ]] || [[ "$raw" =~ ^[A-Za-z]:[\\/].* ]]; then
    echo "$raw"
  else
    python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$ROOT/$raw"
  fi
}

echo "${BLU}==> Checking prerequisites${CLR}"
need_cmd docker; need_cmd node; need_cmd npm; need_cmd python3; need_cmd curl

cd "$ROOT"

echo "${BLU}==> Syncing method-service env from config${CLR}"
node "$ROOT/scripts/method-services.mjs" sync-env >/dev/null
load_root_env

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
PG_PORT="${POSTGRES_PORT:-5440}"

# Clear previously managed method containers before checking ports.
node "$ROOT/scripts/method-services.mjs" stop >/dev/null 2>&1 || true

for p in "$WEB_PORT" "$API_PORT" "$PG_PORT"; do
  if port_busy "$p"; then
    if [[ "$p" == "$PG_PORT" ]] && docker ps --format '{{.Names}}' | grep -qx "phylo-postgres"; then
      echo "${YLW}WARN:${CLR} PostgreSQL port ${PG_PORT} is already in use by phylo-postgres; reusing it."
    else
      die "Port $p is not free."
    fi
  fi
done
while IFS= read -r p; do
  [[ -n "$p" ]] || continue
  port_busy "$p" && die "Port $p is not free."
done < <(method_host_ports)

HOST_STORAGE_DIR="$(resolve_storage_abs)"
mkdir -p "$HOST_STORAGE_DIR"

cleanup(){
  echo
  echo "${YLW}Shutting down...${CLR}"
  if [[ -n "${WORKER_PID:-}" ]]; then kill "$WORKER_PID" 2>/dev/null || true; fi
  if [[ -n "${API_PID:-}" ]]; then kill "$API_PID" 2>/dev/null || true; fi
  node "$ROOT/scripts/method-services.mjs" stop >/dev/null 2>&1 || true
  "${COMPOSE_DEV[@]}" stop postgres minio minio-init >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "${BLU}==> Starting PostgreSQL (Docker Compose, profile=dev)${CLR}"
"${COMPOSE_DEV[@]}" up -d postgres
wait_postgres || die "PostgreSQL did not become healthy"
echo "${GRN}PostgreSQL is healthy.${CLR}"

echo "${BLU}==> Starting MinIO object storage + creating buckets${CLR}"
"${COMPOSE_DEV[@]}" up -d minio minio-init
docker wait phylo-minio-init >/dev/null 2>&1 || true
echo "${GRN}MinIO is up; dataset/artifact buckets ready.${CLR}"

echo "${BLU}==> Starting method services from config via Docker${CLR}"
node "$ROOT/scripts/method-services.mjs" start

# Local API talks to DB via host-mapped postgres port
export POSTGRES_HOST="127.0.0.1"
export POSTGRES_PORT="$PG_PORT"
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER:-phylo_user}:${POSTGRES_PASSWORD:-phylo_pass}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB:-phylo_db}"

# API writes to host storage; method containers read same files at this in-container prefix
export METHOD_SERVICE_FILE_PREFIX="${METHOD_SERVICE_FILE_PREFIX:-/runtime/storage}"
export HOST_RUNTIME_SHARED_ROOT="$HOST_STORAGE_DIR"

# Ensure web dev server always gets API base URL from the single root env
export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://localhost:${API_PORT}}"

echo "${BLU}==> Setting up Python venv for API${CLR}"
[[ -d "$ROOT/.venv" ]] || python3 -m venv "$ROOT/.venv" || die "Failed to create venv"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install -U pip >/dev/null
python -m pip install -r "$ROOT/apps/api/requirements.txt"

echo "${BLU}==> Running database migrations${CLR}"
(cd "$ROOT" && alembic upgrade head)

echo "${BLU}==> Ensuring Node deps and building @phylo/contracts${CLR}"
ensure_node_deps_and_build_contracts

echo "${BLU}==> Starting API on :${API_PORT}${CLR}"
uvicorn apps.api.main:app --host 0.0.0.0 --port "$API_PORT" >/tmp/api.log 2>&1 &
API_PID=$!
wait_http "$API_PORT" || { tail -n 200 /tmp/api.log 2>/dev/null || true; die "API failed readiness check"; }

echo "${BLU}==> Starting run worker (processes QUEUED runs)${CLR}"
python -m apps.api.workers.run_worker >/tmp/run-worker.log 2>&1 &
WORKER_PID=$!
sleep 1
if ! kill -0 "$WORKER_PID" 2>/dev/null; then
  echo "${YLW}Last 50 run-worker logs:${CLR}"
  tail -n 50 /tmp/run-worker.log 2>/dev/null || true
  die "Run worker failed to start"
fi
echo "${GRN}Run worker started (pid ${WORKER_PID}).${CLR}"

echo "${BLU}==> Starting Next.js dev on :${WEB_PORT}${CLR}"
(cd "$ROOT/apps/web" && npm run dev -- -p "$WEB_PORT")
