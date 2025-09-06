set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUMBER_DIR="$ROOT/services/dowser"

RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; BLU=$'\033[34m'; CLR=$'\033[0m'
die(){ echo "${RED}ERROR:${CLR} $*" >&2; exit 1; }
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Missing '$1'. Please install it."; }
npm_major(){ local v; v=$(npm -v 2>/dev/null || echo "0"); echo "${v%%.*}"; }

port_busy(){
  local p="$1"
  if command -v lsof >/dev/null 2>&1; then lsof -Pi :"$p" -sTCP:LISTEN -t >/dev/null
  elif command -v ss >/dev/null 2>&1; then ss -ltn "sport = :$p" | tail -n +2 | grep -q .
  else netstat -tuln 2>/dev/null | grep -q ":$p "
  fi
}

wait_http(){
  local port="$1" i
  for i in {1..120}; do
    if curl -fsS "http://127.0.0.1:${port}/spec" >/dev/null || \
       curl -fsS "http://localhost:${port}/spec" >/dev/null || \
       curl -fsS "http://127.0.0.1:${port}/__docs__/" >/dev/null || \
       curl -fsS "http://localhost:${port}/__docs__/" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

find_env_file(){
  local dir="$1"
  for fname in ".env.local" ".env.development.local" ".env.development" ".env"; do
    [[ -f "$dir/$fname" ]] && { echo "$dir/$fname"; return 0; }
  done
  return 1
}

require_envs(){
  API_ENV="$(find_env_file "$ROOT/apps/api")" || die "API env not found. Create apps/api/.env (or .env.local)."
  WEB_ENV="$(find_env_file "$ROOT/apps/web")" || die "Web env not found. Create apps/web/.env (or .env.local)."
  echo "${BLU}==> Loading API env: ${API_ENV}${CLR}"
  set -a; source "$API_ENV"; set +a

  local cfg="${CONTRACTS_DIR:-packages/contracts}"
  [[ -d "$ROOT/$cfg" || -d "$cfg" ]] || die "CONTRACTS_DIR not found (got '$cfg'). Put a valid path in ${API_ENV}."

  [[ -n "${METHOD_DOWSER_URL:-}" ]] || die "METHOD_DOWSER_URL is not set in ${API_ENV}"

  if ! grep -qE '^NEXT_PUBLIC_API_BASE_URL=' "$WEB_ENV"; then
    die "NEXT_PUBLIC_API_BASE_URL is missing in ${WEB_ENV}"
  fi
}

resolve_contracts_rel_to_plumber(){
  local cfg="${CONTRACTS_DIR:-packages/contracts}"
  local abs
  if [[ "$cfg" = /* ]] || [[ "$cfg" =~ ^[A-Za-z]:[\\/].* ]]; then
    abs="$cfg"
  else
    abs="$ROOT/$cfg"
  fi
  abs="$(python3 - <<PY 2>/dev/null || true
import os,sys
p=os.path.normpath(os.path.abspath("$abs"))
print(p)
PY
)"
  [[ -d "$abs" ]] || die "Resolved contracts dir does not exist: $abs"

  local rel
  if command -v realpath >/dev/null 2>&1; then
    rel="$(realpath --relative-to="$PLUMBER_DIR" "$abs" 2>/dev/null || true)"
  fi
  if [[ -z "$rel" ]]; then
    rel="$(python3 - <<PY
import os
print(os.path.relpath("$abs", "$PLUMBER_DIR"))
PY
)"
  fi
  echo "$rel"
}

ensure_node_deps_and_build_contracts(){
  local NPM_MAJ; NPM_MAJ=$(npm_major)
  echo "${BLU}==> npm version: $(npm -v 2>/dev/null || echo unknown)${CLR}"
  if [[ "$NPM_MAJ" -lt 7 ]]; then
    if grep -q '"@phylo/contracts"[[:space:]]*:[[:space:]]*"workspace:\*"' "$ROOT/apps/web/package.json" 2>/dev/null; then
      die "Your npm ($NPM_MAJ.x) does not support \"workspace:*\".
Either upgrade npm (npm i -g npm@latest) or set:
  apps/web/package.json → \"@phylo/contracts\": \"file:../../packages/contracts\""
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

echo "${BLU}==> Checking prerequisites${CLR}"
need_cmd Rscript; need_cmd node; need_cmd npm; need_cmd python3; need_cmd curl

for p in 3000 8000 8001; do
  port_busy "$p" && die "Port $p is not free."
done

require_envs

echo "${BLU}==> Checking required R packages${CLR}"
set +e
MISSING=$(Rscript --vanilla -e 'suppressPackageStartupMessages(suppressWarnings({
  pkgs <- c("plumber","dowser","alakazam","shazam","ggtree","ape","jsonlite","jsonvalidate","sodium")
  miss <- pkgs[!sapply(pkgs, require, character.only=TRUE, quietly=TRUE)]
  if (length(miss)>0) { cat(paste(miss, collapse=",")); quit(status=10) }
}))' 2>/dev/null)
STATUS=$?
set -e
[[ $STATUS -eq 0 ]] || die "Missing R packages: ${MISSING:-unknown}. See README for install commands."
echo "${GRN}All required R packages are present.${CLR}"

R_CONTRACTS_REL="$(resolve_contracts_rel_to_plumber)"

ABS_CONTRACTS="$(cd "$PLUMBER_DIR" && python3 - <<PY
import os
print(os.path.normpath(os.path.abspath(os.path.join("$PLUMBER_DIR","$R_CONTRACTS_REL"))))
PY
)"
[[ -f "$ABS_CONTRACTS/methods/dowser/result.schema.json" ]] || \
  die "Expected schema not found at: $ABS_CONTRACTS/methods/dowser/result.schema.json"

echo "${BLU}==> Starting Dowser (R/plumber) on :8001${CLR}"
Rscript --vanilla -e "setwd('$PLUMBER_DIR'); Sys.setenv(CONTRACTS_DIR='${R_CONTRACTS_REL}', STRICT_CONTRACT_ROUTES='true'); pr <- plumber::plumb('plumber.R'); pr\$run(host='0.0.0.0', port=8001)" \
  >/tmp/dowser.log 2>&1 &
R_PID=$!

trap 'echo; echo "${YLW}Shutting down...${CLR}"; kill $R_PID $API_PID 2>/dev/null || true' EXIT

wait_http 8001 || { echo "${YLW}Last 200 R logs:${CLR}"; tail -n 200 /tmp/dowser.log || true; die "Dowser failed readiness check"; }
echo "${GRN}Dowser is up on http://localhost:8001${CLR}"

echo "${BLU}==> Setting up Python venv for API${CLR}"
[[ -d "$ROOT/.venv" ]] || python3 -m venv "$ROOT/.venv" || die "Failed to create venv"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install -U pip >/dev/null
python -m pip install -r "$ROOT/apps/api/requirements.txt"

echo "${BLU}==> Ensuring Node deps and building @phylo/contracts${CLR}"
ensure_node_deps_and_build_contracts

echo "${BLU}==> Starting API on :8000${CLR}"
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# brief API readiness check
for i in {1..60}; do
  curl -fsS "http://127.0.0.1:8000/docs" >/dev/null && break || true
  curl -fsS "http://localhost:8000/docs" >/dev/null && break || true
  sleep 1
done

echo "${BLU}==> Starting Next.js dev on :3000${CLR}"
(cd "$ROOT/apps/web" && npm run dev)
