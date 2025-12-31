#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUMBER_DIR="$ROOT/services/dowser"
GCTREE_DIR="$ROOT/services/gctree"
BREP_DIR="$ROOT/services/brepphylo"
CLONAL_DIR="$ROOT/services/clonaltree"

RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; BLU=$'\033[34m'; CLR=$'\033[0m'
die(){ echo "${RED}ERROR:${CLR} $*" >&2; exit 1; }
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Missing '$1'. Please install it."; }
warn_missing(){ command -v "$1" >/dev/null 2>&1 || echo "${YLW}WARN:${CLR} '$1' not found on PATH."; }
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

  [[ -n "${METHOD_DOWSER_URL:-}" ]]     || die "METHOD_DOWSER_URL is not set in ${API_ENV}"
  [[ -n "${METHOD_GCTREE_URL:-}" ]]     || die "METHOD_GCTREE_URL is not set in ${API_ENV} (e.g., http://localhost:8002)"
  [[ -n "${METHOD_BREPPHYLO_URL:-}" ]]  || die "METHOD_BREPPHYLO_URL is not set in ${API_ENV} (e.g., http://localhost:8003)"
  [[ -n "${METHOD_CLONALTREE_URL:-}" ]] || die "METHOD_CLONALTREE_URL is not set in ${API_ENV} (e.g., http://localhost:8004)"

  if ! grep -qE '^NEXT_PUBLIC_API_BASE_URL=' "$WEB_ENV"; then
    die "NEXT_PUBLIC_API_BASE_URL is missing in ${WEB_ENV}"
  fi
}

resolve_contracts_abs(){
  local cfg="${CONTRACTS_DIR:-packages/contracts}"
  local abs
  if [[ "$cfg" = /* ]] || [[ "$cfg" =~ ^[A-Za-z]:[\\/].* ]]; then
    abs="$cfg"
  else
    abs="$ROOT/$cfg"
  fi
  abs="$(python3 - <<PY 2>/dev/null || true
import os
print(os.path.normpath(os.path.abspath("$abs")))
PY
)"
  [[ -d "$abs" ]] || die "Resolved contracts dir does not exist: $abs"
  echo "$abs"
}

relpath_from_dir(){
  local target="$1"; local base="$2"
  python3 - <<PY
import os
print(os.path.relpath("$target", "$base"))
PY
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

muscle_major(){
  local raw major
  raw=$(muscle -version 2>&1 | head -n 2 || true)
  major=$(echo "$raw" | sed -n 's/.*[Vv]ersion[[:space:]]*\\([0-9][0-9]*\\).*/\\1/p')
  if [[ -z "$major" ]]; then
    major=$(echo "$raw" | sed -n 's/.*[Vv]\\([0-9][0-9]*\\).*/\\1/p')
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

# ---- NEW: ensure sitecustomize patch is loaded via PYTHONPATH (no copying) ----
ensure_gctree_sitecustomize_on_pythonpath(){
  local sc="$GCTREE_DIR/sitecustomize.py"
  if [[ ! -f "$sc" ]]; then
    echo "${YLW}WARN:${CLR} No sitecustomize.py found at $sc. ete3 render patch will not be applied."
    return 0
  fi

  # Prepend services/gctree so Python auto-imports sitecustomize.py from there.
  # This affects: uvicorn, gctree CLI, and any python spawned from this shell.
  export PYTHONPATH="$GCTREE_DIR${PYTHONPATH:+:$PYTHONPATH}"

  # Optional: prove it is active (non-fatal; helpful for debugging)
  python - <<'PY' || true
import sys
print("PYTHONPATH[0] =", sys.path[0])
try:
    import sitecustomize  # noqa: F401
    print("OK: sitecustomize imported from:", getattr(sitecustomize, "__file__", "<unknown>"))
except Exception as e:
    print("WARN: sitecustomize import failed:", e)
PY
}

echo "${BLU}==> Checking prerequisites${CLR}"
need_cmd Rscript; need_cmd node; need_cmd npm; need_cmd python3; need_cmd curl

for p in 3000 8000 8001 8002 8003 8004; do
  port_busy "$p" && die "Port $p is not free."
done

require_envs

BREP_ENV="$(find_env_file "$BREP_DIR")" || die "BrepPhylo env not found. Create services/brepphylo/.env (or .env.local)."
echo "${BLU}==> Loading BrepPhylo env: ${BREP_ENV}${CLR}"
set -a; source "$BREP_ENV"; set +a
if [[ -z "${IGPHYML_BIN:-}" ]]; then
  echo "${YLW}WARN:${CLR} IGPHYML_BIN not set in ${BREP_ENV}; defaulting to /usr/local/bin/igphyml"
  export IGPHYML_BIN="/usr/local/bin/igphyml"
fi
if [[ -z "${IGPHYML_MOTIFS:-}" ]]; then
  echo "${YLW}WARN:${CLR} IGPHYML_MOTIFS not set in ${BREP_ENV}; defaulting to /usr/local/share/igphyml/src/motifs"
  export IGPHYML_MOTIFS="/usr/local/share/igphyml/src/motifs"
  export IGPHYML_PATH="$IGPHYML_MOTIFS"
fi

ABS_CONTRACTS="$(resolve_contracts_abs)"
R_CONTRACTS_REL="$(relpath_from_dir "$ABS_CONTRACTS" "$PLUMBER_DIR")"
BREP_CONTRACTS_REL="$(relpath_from_dir "$ABS_CONTRACTS" "$BREP_DIR")"

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
[[ -f "$ABS_CONTRACTS/methods/gctree/param.schema.json" ]] || \
  echo "${YLW}WARN:${CLR} gctree schemas not found under contracts; continuing."

echo "${BLU}==> Starting Dowser (R/plumber) on :8001${CLR}"
Rscript --vanilla -e "setwd('$PLUMBER_DIR'); Sys.setenv(CONTRACTS_DIR='${R_CONTRACTS_REL}', STRICT_CONTRACT_ROUTES='true'); pr <- plumber::plumb('plumber.R'); pr\$run(host='0.0.0.0', port=8001)" \
  >/tmp/dowser.log 2>&1 &
R_PID=$!

trap 'echo; echo "${YLW}Shutting down...${CLR}"; kill $R_PID $API_PID ${GCTREE_PID:-} ${CLONAL_PID:-} ${BREP_PID:-} 2>/dev/null || true' EXIT

wait_http 8001 || { echo "${YLW}Last 200 R logs:${CLR}"; tail -n 200 /tmp/dowser.log || true; die "Dowser failed readiness check"; }
echo "${GRN}Dowser is up on http://localhost:8001${CLR}"

echo "${BLU}==> Setting up Python venv for API & GCtree${CLR}"
[[ -d "$ROOT/.venv" ]] || python3 -m venv "$ROOT/.venv" || die "Failed to create venv"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install -U pip >/dev/null
python -m pip install -r "$ROOT/apps/api/requirements.txt"

# --- GCtree micro (no Docker) ---
echo "${BLU}==> Installing GCtree service requirements${CLR}"
[[ -f "$GCTREE_DIR/requirements.txt" ]] || die "Missing $GCTREE_DIR/requirements.txt"
python -m pip install -r "$GCTREE_DIR/requirements.txt"

echo "${BLU}==> Installing ClonalTree service requirements${CLR}"
[[ -f "$CLONAL_DIR/requirements.txt" ]] || die "Missing $CLONAL_DIR/requirements.txt"
python -m pip install -r "$CLONAL_DIR/requirements.txt"

echo "${BLU}==> Ensuring MUSCLE v3.x is available for ClonalTree${CLR}"
ensure_muscle_v3

# NEW: no copying into site-packages. Ensure patch is loaded via PYTHONPATH.
echo "${BLU}==> Enabling ete3 render patch via PYTHONPATH (sitecustomize)${CLR}"
ensure_gctree_sitecustomize_on_pythonpath

echo "${BLU}==> Checking GCtree CLIs on PATH (from the venv)${CLR}"
need_cmd gctree
need_cmd deduplicate
need_cmd mkconfig

# DNAPARS is system-provided; warn if absent. GCtree can still run parts without it.
if ! command -v dnapars >/dev/null 2>&1 && ! command -v phylip >/dev/null 2>&1; then
  echo "${YLW}WARN:${CLR} Neither 'dnapars' nor 'phylip' wrapper found on PATH."
  echo "      Install via one of:"
  echo "        • Ubuntu/Debian: sudo apt-get install phylip"
  echo "        • Conda (recommended): conda install -c bioconda phylip"
fi

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

# --- Start GCtree FastAPI service on :8002 (no Docker) ---
echo "${BLU}==> Starting GCtree (FastAPI) on :8002${CLR}"
(
  cd "$GCTREE_DIR"
  # CONTRACTS_DIR must be absolute for the Python micro
  export CONTRACTS_DIR="$ABS_CONTRACTS"
  export STRICT_CONTRACT_ROUTES="true"
  # headless hints (also set inside the service, but harmless here)
  export QT_QPA_PLATFORM="offscreen"
  export MPLBACKEND="agg"
  uvicorn app:app --host 0.0.0.0 --port 8002
) >/tmp/gctree.log 2>&1 &
GCTREE_PID=$!

wait_http 8002 || { echo "${YLW}Last 200 GCtree logs:${CLR}"; tail -n 200 /tmp/gctree.log || true; die "GCtree failed readiness check"; }
echo "${GRN}GCtree is up on http://localhost:8002${CLR}"

# --- ClonalTree micro (FastAPI) ---
echo "${BLU}==> Starting ClonalTree (FastAPI) on :8004${CLR}"
(
  cd "$CLONAL_DIR"
  export CONTRACTS_DIR="$ABS_CONTRACTS"
  export STRICT_CONTRACT_ROUTES="true"
  export QT_QPA_PLATFORM="offscreen"
  export MPLBACKEND="agg"
  uvicorn app:app --host 0.0.0.0 --port 8004
) >/tmp/clonaltree.log 2>&1 &
CLONAL_PID=$!

wait_http 8004 || { echo "${YLW}Last 200 ClonalTree logs:${CLR}"; tail -n 200 /tmp/clonaltree.log || true; die "ClonalTree failed readiness check"; }
echo "${GRN}ClonalTree is up on http://localhost:8004${CLR}"

# --- BrepPhylo micro (R/plumber) ---
echo "${BLU}==> Starting BrepPhylo (R/plumber) on :8003${CLR}"
Rscript --vanilla -e "setwd('$BREP_DIR'); Sys.setenv(CONTRACTS_DIR='${BREP_CONTRACTS_REL}', STRICT_CONTRACT_ROUTES='true'); pr <- plumber::plumb('plumber.R'); pr\$run(host='0.0.0.0', port=8003)" \
  >/tmp/brepphylo.log 2>&1 &
BREP_PID=$!

wait_http 8003 || { echo "${YLW}Last 200 BrepPhylo logs:${CLR}"; tail -n 200 /tmp/brepphylo.log || true; die "BrepPhylo failed readiness check"; }
echo "${GRN}BrepPhylo is up on http://localhost:8003${CLR}"

echo "${BLU}==> Starting Next.js dev on :3000${CLR}"
(cd "$ROOT/apps/web" && npm run dev)
