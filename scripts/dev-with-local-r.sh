#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
PLUMBER_DIR="$ROOT/services/dowser"
GCTREE_DIR="$ROOT/services/gctree"
BREP_DIR="$ROOT/services/brepphylo"
CLONAL_DIR="$ROOT/services/clonaltree"

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
  else
    netstat -tuln 2>/dev/null | grep -q ":$p "
  fi
}

wait_http(){
  local port="$1" i
  for i in {1..120}; do
    if curl -fsS "http://127.0.0.1:${port}/spec" >/dev/null || \
       curl -fsS "http://localhost:${port}/spec" >/dev/null || \
       curl -fsS "http://127.0.0.1:${port}/__docs__/" >/dev/null || \
       curl -fsS "http://localhost:${port}/__docs__/" >/dev/null || \
       curl -fsS "http://127.0.0.1:${port}/docs" >/dev/null || \
       curl -fsS "http://localhost:${port}/docs" >/dev/null; then
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

resolve_contracts_abs(){
  local cfg="${CONTRACTS_DIR:-packages/contracts}"
  local abs
  if [[ "$cfg" = /* ]] || [[ "$cfg" =~ ^[A-Za-z]:[\\/].* ]]; then
    abs="$cfg"
  else
    abs="$ROOT/$cfg"
  fi
  abs="$(python3 - <<PY
import os
print(os.path.normpath(os.path.abspath("$abs")))
PY
)"
  [[ -d "$abs" ]] || die "Resolved contracts dir does not exist: $abs"
  echo "$abs"
}

resolve_storage_abs(){
  local raw="${STORAGE_LOCAL_PATH:-runtime/storage}"
  if [[ "$raw" = /* ]] || [[ "$raw" =~ ^[A-Za-z]:[\\/].* ]]; then
    echo "$raw"
  else
    realpath "$ROOT/$raw"
  fi
}

relpath_from_dir(){
  local target="$1"; local base="$2"
  python3 - <<PY
import os
print(os.path.relpath("$target", "$base"))
PY
}

method_port(){
  local method_id="$1"
  node -e 'const fs=require("fs"); const p=require("path"); const root=process.argv[1]; const id=process.argv[2]; const cfg=JSON.parse(fs.readFileSync(p.join(root,"config","method-services.json"),"utf8")); const s=(cfg.services||[]).find((x)=>String(x.id).toLowerCase()===String(id).toLowerCase()); if(!s){process.exit(2);} console.log(String(s.port));' "$ROOT" "$method_id"
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

muscle_major(){
  local raw major
  raw=$(muscle -version 2>&1 | head -n 2 || true)
  major=$(echo "$raw" | sed -n 's/.*[Vv]ersion[[:space:]]*\([0-9][0-9]*\).*/\1/p')
  if [[ -z "$major" ]]; then
    major=$(echo "$raw" | sed -n 's/.*[Vv]\([0-9][0-9]*\).*/\1/p')
  fi
  echo "${major:-}:::${raw:-}"
}

install_muscle3(){
  local url="https://drive5.com/muscle/downloads3.8.31/muscle3.8.31_i86linux64.tar.gz"
  local tmp tgz bin
  tmp="$(mktemp -d)"
  tgz="$tmp/muscle3.tgz"
  echo "${BLU}==> Installing MUSCLE v3.8.31 into .venv/bin${CLR}"
  curl -L -o "$tgz" "$url"
  tar -xzf "$tgz" -C "$tmp"
  bin="$(find "$tmp" -type f -name 'muscle3.8.31_i86linux64' | head -n 1)"
  [[ -n "$bin" ]] || die "Failed to unpack MUSCLE v3.8.31 binary"
  install -m 0755 "$bin" "$ROOT/.venv/bin/muscle"
  rm -rf "$tmp"
  echo "${GRN}MUSCLE v3.8.31 installed at $ROOT/.venv/bin/muscle${CLR}"
}

ensure_muscle_v3(){
  if command -v muscle >/dev/null 2>&1; then
    local parsed major out
    parsed="$(muscle_major)"
    major="${parsed%%:::*}"
    out="${parsed#*:::}"
    if [[ -n "$major" && "$major" -lt 5 ]]; then
      echo "${GRN}MUSCLE available:${CLR} ${out}"
      return 0
    fi
    echo "${YLW}WARN:${CLR} MUSCLE >=5 or unknown version detected (${out:-unknown}); replacing with v3.8.31"
  else
    echo "${YLW}WARN:${CLR} MUSCLE not found on PATH; installing v3.8.31"
  fi
  install_muscle3
}

ensure_gctree_sitecustomize_on_pythonpath(){
  local sc="$GCTREE_DIR/sitecustomize.py"
  if [[ ! -f "$sc" ]]; then
    echo "${YLW}WARN:${CLR} No sitecustomize.py found at $sc. ete3 render patch will not be applied."
    return 0
  fi
  export PYTHONPATH="$GCTREE_DIR${PYTHONPATH:+:$PYTHONPATH}"
}

echo "${BLU}==> Checking prerequisites${CLR}"
need_cmd Rscript; need_cmd node; need_cmd npm; need_cmd python3; need_cmd curl; need_cmd docker

cd "$ROOT"

echo "${BLU}==> Syncing method-service env from config${CLR}"
node "$ROOT/scripts/method-services.mjs" sync-env >/dev/null
load_root_env

DOWSER_PORT="$(method_port dowser)" || die "dowser service not found in config/method-services.json"
GCTREE_PORT="$(method_port gctree)" || die "gctree service not found in config/method-services.json"
BREPPHYLO_PORT="$(method_port brepphylo)" || die "brepphylo service not found in config/method-services.json"
CLONALTREE_PORT="$(method_port clonaltree)" || die "clonaltree service not found in config/method-services.json"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
PG_PORT="${POSTGRES_PORT:-5440}"

for p in "$WEB_PORT" "$API_PORT" "$PG_PORT" "$DOWSER_PORT" "$GCTREE_PORT" "$BREPPHYLO_PORT" "$CLONALTREE_PORT"; do
  if port_busy "$p"; then
    if [[ "$p" == "$PG_PORT" ]] && docker ps --format '{{.Names}}' | grep -qx "phylo-postgres"; then
      echo "${YLW}WARN:${CLR} PostgreSQL port ${PG_PORT} is already in use by phylo-postgres; reusing it."
    else
      die "Port $p is not free."
    fi
  fi
done

ABS_CONTRACTS="$(resolve_contracts_abs)"
ABS_STORAGE="$(resolve_storage_abs)"
mkdir -p "$ABS_STORAGE"

R_CONTRACTS_REL="$(relpath_from_dir "$ABS_CONTRACTS" "$PLUMBER_DIR")"
BREP_CONTRACTS_REL="$(relpath_from_dir "$ABS_CONTRACTS" "$BREP_DIR")"

cleanup(){
  echo
  echo "${YLW}Shutting down...${CLR}"
  kill ${R_PID:-} ${API_PID:-} ${GCTREE_PID:-} ${CLONAL_PID:-} ${BREP_PID:-} 2>/dev/null || true
  docker compose --profile dev stop postgres >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "${BLU}==> Starting PostgreSQL (Docker Compose, profile=dev)${CLR}"
docker compose --profile dev up -d postgres
wait_postgres || die "PostgreSQL did not become healthy"
echo "${GRN}PostgreSQL is healthy.${CLR}"

echo "${BLU}==> Checking required R packages${CLR}"
set +e
MISSING=$(Rscript --vanilla -e 'suppressPackageStartupMessages(suppressWarnings({
  pkgs <- c("plumber","dowser","alakazam","shazam","ggtree","ape","jsonlite","jsonvalidate","sodium","BrepPhylo","Biostrings","igraph")
  miss <- pkgs[!sapply(pkgs, require, character.only=TRUE, quietly=TRUE)]
  if (length(miss)>0) { cat(paste(miss, collapse=",")); quit(status=10) }
}))' 2>/dev/null)
STATUS=$?
set -e
[[ $STATUS -eq 0 ]] || die "Missing R packages: ${MISSING:-unknown}. See README for install commands."
echo "${GRN}All required R packages are present.${CLR}"

[[ -f "$ABS_CONTRACTS/methods/dowser/result.schema.json" ]] || \
  die "Expected schema not found at: $ABS_CONTRACTS/methods/dowser/result.schema.json"

# Local API talks to DB via host-mapped postgres port
export POSTGRES_HOST="127.0.0.1"
export POSTGRES_PORT="$PG_PORT"
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER:-phylo_user}:${POSTGRES_PASSWORD:-phylo_pass}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB:-phylo_db}"

# Local method services read host files directly.
export METHOD_SERVICE_FILE_PREFIX="$ABS_STORAGE"
export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://localhost:${API_PORT}}"

echo "${BLU}==> Starting Dowser (R/plumber) on :${DOWSER_PORT}${CLR}"
Rscript --vanilla -e "setwd('$PLUMBER_DIR'); Sys.setenv(CONTRACTS_DIR='${R_CONTRACTS_REL}', STRICT_CONTRACT_ROUTES='${STRICT_CONTRACT_ROUTES:-true}'); pr <- plumber::plumb('plumber.R'); pr\$run(host='0.0.0.0', port=${DOWSER_PORT})" \
  >/tmp/dowser.log 2>&1 &
R_PID=$!
wait_http "$DOWSER_PORT" || { echo "${YLW}Last 200 Dowser logs:${CLR}"; tail -n 200 /tmp/dowser.log || true; die "Dowser failed readiness check"; }

echo "${BLU}==> Setting up Python venv for API + local Python methods${CLR}"
[[ -d "$ROOT/.venv" ]] || python3 -m venv "$ROOT/.venv" || die "Failed to create venv"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install -U pip >/dev/null
python -m pip install -r "$ROOT/apps/api/requirements.txt"
python -m pip install -r "$GCTREE_DIR/requirements.txt"
python -m pip install -r "$CLONAL_DIR/requirements.txt"

echo "${BLU}==> Ensuring MUSCLE v3.x is available for ClonalTree${CLR}"
ensure_muscle_v3

echo "${BLU}==> Enabling GCtree sitecustomize patch via PYTHONPATH${CLR}"
ensure_gctree_sitecustomize_on_pythonpath

echo "${BLU}==> Checking GCtree CLIs on PATH${CLR}"
need_cmd gctree
need_cmd deduplicate
need_cmd mkconfig
if ! command -v dnapars >/dev/null 2>&1 && ! command -v phylip >/dev/null 2>&1; then
  echo "${YLW}WARN:${CLR} Neither 'dnapars' nor 'phylip' wrapper found on PATH."
fi

echo "${BLU}==> Running database migrations${CLR}"
(cd "$ROOT" && alembic upgrade head)

echo "${BLU}==> Ensuring Node deps and building @phylo/contracts${CLR}"
ensure_node_deps_and_build_contracts

echo "${BLU}==> Starting API on :${API_PORT}${CLR}"
uvicorn apps.api.main:app --host 0.0.0.0 --port "$API_PORT" >/tmp/api.log 2>&1 &
API_PID=$!
wait_http "$API_PORT" || { echo "${YLW}Last 200 API logs:${CLR}"; tail -n 200 /tmp/api.log || true; die "API failed readiness check"; }

echo "${BLU}==> Starting GCtree (FastAPI) on :${GCTREE_PORT}${CLR}"
(
  cd "$GCTREE_DIR"
  export CONTRACTS_DIR="$ABS_CONTRACTS"
  export STRICT_CONTRACT_ROUTES="${STRICT_CONTRACT_ROUTES:-true}"
  export QT_QPA_PLATFORM="offscreen"
  export MPLBACKEND="agg"
  uvicorn app:app --host 0.0.0.0 --port "$GCTREE_PORT"
) >/tmp/gctree.log 2>&1 &
GCTREE_PID=$!
wait_http "$GCTREE_PORT" || { echo "${YLW}Last 200 GCtree logs:${CLR}"; tail -n 200 /tmp/gctree.log || true; die "GCtree failed readiness check"; }

echo "${BLU}==> Starting ClonalTree (FastAPI) on :${CLONALTREE_PORT}${CLR}"
(
  cd "$CLONAL_DIR"
  export CONTRACTS_DIR="$ABS_CONTRACTS"
  export STRICT_CONTRACT_ROUTES="${STRICT_CONTRACT_ROUTES:-true}"
  export QT_QPA_PLATFORM="offscreen"
  export MPLBACKEND="agg"
  uvicorn app:app --host 0.0.0.0 --port "$CLONALTREE_PORT"
) >/tmp/clonaltree.log 2>&1 &
CLONAL_PID=$!
wait_http "$CLONALTREE_PORT" || { echo "${YLW}Last 200 ClonalTree logs:${CLR}"; tail -n 200 /tmp/clonaltree.log || true; die "ClonalTree failed readiness check"; }

echo "${BLU}==> Starting BrepPhylo (R/plumber) on :${BREPPHYLO_PORT}${CLR}"
Rscript --vanilla -e "setwd('$BREP_DIR'); Sys.setenv(CONTRACTS_DIR='${BREP_CONTRACTS_REL}', STRICT_CONTRACT_ROUTES='${STRICT_CONTRACT_ROUTES:-true}', IGPHYML_BIN='${IGPHYML_BIN:-/usr/local/share/igphyml/src/igphyml}', IGPHYML_MOTIFS='${IGPHYML_MOTIFS:-/usr/local/share/igphyml/src/motifs}', IGPHYML_PATH='${IGPHYML_PATH:-/usr/local/share/igphyml/src/motifs}'); pr <- plumber::plumb('plumber.R'); pr\$run(host='0.0.0.0', port=${BREPPHYLO_PORT})" \
  >/tmp/brepphylo.log 2>&1 &
BREP_PID=$!
wait_http "$BREPPHYLO_PORT" || { echo "${YLW}Last 200 BrepPhylo logs:${CLR}"; tail -n 200 /tmp/brepphylo.log || true; die "BrepPhylo failed readiness check"; }

echo "${BLU}==> Starting Next.js dev on :${WEB_PORT}${CLR}"
(cd "$ROOT/apps/web" && npm run dev -- -p "$WEB_PORT")
