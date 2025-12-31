set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST_RUNTIME_DIR="$(realpath "$ROOT/runtime")"
HOST_RUNS_DIR="${HOST_RUNTIME_DIR}/runs"
CONTAINER_RUNTIME_DIR="/runtime"
CONTAINER_RUNS_DIR="${CONTAINER_RUNTIME_DIR}/runs"

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
  set -a; # export everything we source
  source "$API_ENV"
  set +a

  [[ -n "${CONTRACTS_DIR:-}" ]] || die "CONTRACTS_DIR is not set in ${API_ENV}"
  [[ -d "${CONTRACTS_DIR}" ]] || die "CONTRACTS_DIR path does not exist: ${CONTRACTS_DIR}"
  [[ -n "${METHOD_DOWSER_URL:-}" ]] || die "METHOD_DOWSER_URL is not set in ${API_ENV}"
  [[ -n "${METHOD_GCTREE_URL:-}" ]] || die "METHOD_GCTREE_URL is not set in ${API_ENV}"
  [[ -n "${METHOD_BREPPHYLO_URL:-}" ]] || die "METHOD_BREPPHYLO_URL is not set in ${API_ENV}"
  [[ -n "${METHOD_CLONALTREE_URL:-}" ]] || die "METHOD_CLONALTREE_URL is not set in ${API_ENV}"

  if ! grep -qE '^NEXT_PUBLIC_API_BASE_URL=' "$WEB_ENV"; then
    die "NEXT_PUBLIC_API_BASE_URL is missing in ${WEB_ENV}"
  fi
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
need_cmd docker; need_cmd node; need_cmd npm; need_cmd python3; need_cmd curl

for p in 3000 8000 8001 8002 8003 8004; do
  port_busy "$p" && die "Port $p is not free."
done

require_envs
mkdir -p "$HOST_RUNS_DIR"

echo "${BLU}==> Building and starting Dowser container (first time may be LONG)${CLR}"
docker rm -f phylo-dowser-dev >/dev/null 2>&1 || true
docker build -t phylo-dowser:dev "$ROOT/services/dowser"
docker run -d --name phylo-dowser-dev -p 8001:8001 \
  -e CONTRACTS_DIR=/contracts -e STRICT_CONTRACT_ROUTES=true \
  -e RUNS_DIR="$CONTAINER_RUNS_DIR" \
  -e IGPHYML_BIN=/usr/local/share/igphyml/src/igphyml \
  -e IGPHYML_MOTIFS=/usr/local/share/igphyml/src/motifs \
  -e IGPHYML_PATH=/usr/local/share/igphyml/src/motifs \
  -v "$ROOT/packages/contracts:/contracts:ro" \
  -v "$HOST_RUNTIME_DIR:$CONTAINER_RUNTIME_DIR:ro" \
  phylo-dowser:dev >/dev/null

echo "${BLU}==> Waiting for Dowser HTTP on :8001${CLR}"
wait_http 8001 || { docker logs --tail=200 phylo-dowser-dev || true; die "Dowser failed readiness check"; }
echo "${GRN}Dowser is up on http://localhost:8001${CLR}"

echo "${BLU}==> Building and starting GCtree container (first time may be LONG)${CLR}"   # [gctree]
docker rm -f phylo-gctree-dev >/dev/null 2>&1 || true                                     # [gctree]
docker build -t phylo-gctree:dev "$ROOT/services/gctree"                                  # [gctree]

HOST_CONTRACTS_DIR="$(realpath "$ROOT/packages/contracts")"

docker run -d --name phylo-gctree-dev \
  -e CONTRACTS_DIR="/contracts" \
  -e STRICT_CONTRACT_ROUTES="${STRICT_CONTRACT_ROUTES:-true}" \
  -e RUNS_DIR="$CONTAINER_RUNS_DIR" \
  -p 8002:8002 \
  -v "$HOST_CONTRACTS_DIR":/contracts:ro \
  -v "$HOST_RUNTIME_DIR:$CONTAINER_RUNTIME_DIR:ro" \
  phylo-gctree:dev                                                                      # [gctree]

# make sure METHOD_GCTREE_URL exists in API env (optional but helpful):
[[ -n "${METHOD_GCTREE_URL:-}" ]] || die "METHOD_GCTREE_URL is not set in ${API_ENV}"    # [gctree]

echo "${BLU}==> Building and starting ClonalTree container${CLR}"
docker rm -f phylo-clonaltree-dev >/dev/null 2>&1 || true
docker build -t phylo-clonaltree:dev "$ROOT/services/clonaltree"
docker run -d --name phylo-clonaltree-dev -p 8004:8004 \
  -e CONTRACTS_DIR=/contracts -e STRICT_CONTRACT_ROUTES=true \
  -e RUNS_DIR="$CONTAINER_RUNS_DIR" \
  -v "$ROOT/packages/contracts:/contracts:ro" \
  -v "$HOST_RUNTIME_DIR:$CONTAINER_RUNTIME_DIR:ro" \
  phylo-clonaltree:dev >/dev/null

echo "${BLU}==> Waiting for ClonalTree HTTP on :8004${CLR}"
wait_http 8004 || { docker logs --tail=200 phylo-clonaltree-dev || true; die "ClonalTree failed readiness check"; }
echo "${GRN}ClonalTree is up on http://localhost:8004${CLR}"

echo "${BLU}==> Building and starting BrepPhylo container${CLR}"
docker rm -f phylo-brepphylo-dev >/dev/null 2>&1 || true
docker build -t phylo-brepphylo:dev "$ROOT/services/brepphylo"
docker run -d --name phylo-brepphylo-dev -p 8003:8003 \
  -e CONTRACTS_DIR=/contracts -e STRICT_CONTRACT_ROUTES=true \
  -e RUNS_DIR="$CONTAINER_RUNS_DIR" \
  -e DNAPARS_PATH=/usr/local/bin/dnapars \
  -e IGPHYML_BIN=/usr/local/share/igphyml/src/igphyml \
  -e IGPHYML_MOTIFS=/usr/local/share/igphyml/src/motifs \
  -e IGPHYML_PATH=/usr/local/share/igphyml/src/motifs \
  -v "$ROOT/packages/contracts:/contracts:ro" \
  -v "$HOST_RUNTIME_DIR:$CONTAINER_RUNTIME_DIR:ro" \
  phylo-brepphylo:dev >/dev/null

echo "${BLU}==> Waiting for BrepPhylo HTTP on :8003${CLR}"
wait_http 8003 || { docker logs --tail=200 phylo-brepphylo-dev || true; die "BrepPhylo failed readiness check"; }
echo "${GRN}BrepPhylo is up on http://localhost:8003${CLR}"

# in the trap line, add the container:
trap 'echo; echo "${YLW}Shutting down...${CLR}"; \
      if [[ -n "${API_PID:-}" ]]; then kill "$API_PID" 2>/dev/null || true; fi; \
      docker rm -f phylo-dowser-dev >/dev/null 2>&1 || true; \
      docker rm -f phylo-gctree-dev >/dev/null 2>&1 || true; \
      docker rm -f phylo-clonaltree-dev >/dev/null 2>&1 || true; \
      docker rm -f phylo-brepphylo-dev >/dev/null 2>&1 || true' EXIT

echo "${BLU}==> Setting up Python venv for API${CLR}"
[[ -d "$ROOT/.venv" ]] || python3 -m venv "$ROOT/.venv" || die "Failed to create venv"
source "$ROOT/.venv/bin/activate"
python -m pip install -U pip >/dev/null
python -m pip install -r "$ROOT/apps/api/requirements.txt"

# ensure API writes to host path but sends container-visible paths to method services
export RUNS_DIR="$HOST_RUNS_DIR"
export RUNS_DIR_SERVICE="$CONTAINER_RUNS_DIR"

echo "${BLU}==> Ensuring Node deps and building @phylo/contracts${CLR}"
ensure_node_deps_and_build_contracts

echo "${BLU}==> Starting API on :8000${CLR}"
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

for i in {1..60}; do
  curl -fsS "http://127.0.0.1:8000/docs" >/dev/null && break || true
  curl -fsS "http://localhost:8000/docs" >/dev/null && break || true
  sleep 1
done

echo "${BLU}==> Starting Next.js dev on :3000${CLR}"
(cd "$ROOT/apps/web" && npm run dev)
