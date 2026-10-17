#!/bin/sh
#
# Can this deployment start, and once started, is it complete?
#
#   scripts/deploy-check.sh             before starting: everything `docker
#                                       compose --profile prod up` depends on
#   scripts/deploy-check.sh --running   after starting: containers, database
#                                       migrations, buckets, method services,
#                                       version information, email
#
# Read-only: it creates, changes and deletes nothing, and prints no secret.
# Exit code 1 when something must be fixed; warnings do not fail it.
#
# The compose project is the one `docker compose` would use from the repository
# root (COMPOSE_FILE / COMPOSE_PROJECT_NAME are honoured). PHYLO_ENV_FILE names
# the env file when it is not ./.env.
#
# POSIX sh + awk + docker only (no Node/Python on the host).

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${PHYLO_ENV_FILE:-$ROOT/.env}"
MODE="preflight"
MIN_COMPOSE_MAJOR=2
MIN_COMPOSE_MINOR=17
EXTERNAL_NETWORK="proxy_net"
VOLUMES="phylo_postgres_data phylo_minio_data"

case "${1:-}" in
  "") ;;
  --running) MODE="running" ;;
  -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "deploy-check: unknown argument: $1 (see --help)" >&2; exit 2 ;;
esac

failures=0
warnings=0
ok()   { printf '  OK    %s\n' "$*"; }
warn() { printf '  WARN  %s\n' "$*"; warnings=$((warnings + 1)); }
fail() { printf '  FAIL  %s\n' "$*"; failures=$((failures + 1)); }
hint() { printf '        %s\n' "$*"; }

# The env file is named explicitly so that the values checked here are the ones
# Compose substitutes.
compose() {
  if [ -f "$ENV_FILE" ]; then
    (cd "$ROOT" && docker compose --env-file "$ENV_FILE" --profile prod "$@")
  else
    (cd "$ROOT" && docker compose --profile prod "$@")
  fi
}

# Value of KEY: shell environment first (as Compose does), then the env file.
value_of() {
  eval "shell_value=\${$1:-}"
  if [ -n "$shell_value" ]; then echo "$shell_value"; return; fi
  [ -f "$ENV_FILE" ] || return 0
  awk -v key="$1" '
    /^[[:space:]]*#/ { next }
    {
      line = $0
      sub(/^[[:space:]]*(export[[:space:]]+)?/, "", line)
      eq = index(line, "=")
      if (eq == 0) next
      k = substr(line, 1, eq - 1); gsub(/[[:space:]]/, "", k)
      if (k != key) next
      v = substr(line, eq + 1)
      sub(/[[:space:]]+#.*$/, "", v); gsub(/^[[:space:]"'\'']+|[[:space:]"'\'']+$/, "", v)
      val = v
    }
    END { if (val != "") print val }' "$ENV_FILE"
}

# ----------------------------------------------------------------------------
check_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    fail "Docker is not installed (the docker command was not found)"
    return 1
  fi
  if ! docker info >/dev/null 2>&1; then
    fail "the Docker daemon does not answer (is it running, and may this user use it?)"
    return 1
  fi
  version="$(docker compose version --short 2>/dev/null | sed 's/^v//')"
  if [ -z "$version" ]; then
    fail "Docker Compose v2 is not installed ('docker compose version' failed)"
    return 1
  fi
  major="${version%%.*}"; rest="${version#*.}"; minor="${rest%%.*}"
  case "$major$minor" in *[!0-9]*|'') fail "unexpected Docker Compose version: $version"; return 1 ;; esac
  if [ "$major" -lt "$MIN_COMPOSE_MAJOR" ] || { [ "$major" -eq "$MIN_COMPOSE_MAJOR" ] && [ "$minor" -lt "$MIN_COMPOSE_MINOR" ]; }; then
    fail "Docker Compose $version is too old: $MIN_COMPOSE_MAJOR.$MIN_COMPOSE_MINOR or newer is needed (named build contexts)"
    return 1
  fi
  ok "Docker and Docker Compose $version"
}

check_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    fail "$ENV_FILE does not exist"
    hint "cp .env.example .env, then set the secrets listed at its top"
    return 1
  fi
  ok "configuration file $ENV_FILE"
}

check_compose_config() {
  # Compose names the first missing required variable and nothing else.
  if out="$(compose config --quiet 2>&1)"; then
    ok "docker-compose.yml is valid and every required variable is set"
  else
    fail "docker-compose.yml cannot be used with this configuration:"
    echo "$out" | sed -n '1,5p' | while IFS= read -r line; do hint "$line"; done
    return 1
  fi
}

check_ports() {
  if out="$(sh "$ROOT/scripts/ports.sh" check --env-file "$ENV_FILE" 2>&1)"; then
    ok "internal ports are consistent"
  else
    fail "internal ports:"
    echo "$out" | while IFS= read -r line; do hint "$line"; done
  fi
}

check_resource_plan() {
  plan="$ROOT/scripts/resource-plan.sh"
  if sh "$plan" --check --env-file "$ENV_FILE" >/dev/null 2>&1; then
    ok "container limits in the env file match the resource budget"
    return 0
  fi
  if ! wanted="$(sh "$plan" --env --env-file "$ENV_FILE" 2>&1)"; then
    fail "the resource budget cannot be used:"
    echo "$wanted" | sed -n '1,4p' | while IFS= read -r line; do hint "$line"; done
    return 0
  fi
  # No stored plan: docker-compose.yml then uses its built-in limits, which are
  # the plan for the default budget.
  builtin="$(env -u PHYLO_CPU_BUDGET -u PHYLO_MEMORY_BUDGET_MB -u PHYLO_PIDS_BUDGET -u PHYLO_RESOURCE_MODE \
             sh "$plan" --env --env-file /dev/null 2>/dev/null)"
  if grep -q "resource plan (generated by" "$ENV_FILE" 2>/dev/null; then
    fail "the container limits stored in the env file belong to a different resource budget"
    hint "run: sh scripts/resource-plan.sh --write   (./run.sh prod does this)"
  elif [ "$wanted" = "$builtin" ]; then
    ok "default resource budget: docker-compose.yml's built-in container limits apply"
  else
    fail "a resource budget is set, but its container limits are not stored in the env file"
    hint "plain 'docker compose up' would use the built-in limits instead of your budget"
    hint "run: sh scripts/resource-plan.sh --write   (./run.sh prod does this)"
  fi
}

check_network() {
  if docker network inspect "$EXTERNAL_NETWORK" >/dev/null 2>&1; then
    ok "reverse-proxy network '$EXTERNAL_NETWORK' exists"
  else
    fail "the reverse-proxy network '$EXTERNAL_NETWORK' does not exist"
    hint "it belongs to the server's reverse proxy; ask the infrastructure team, or, on a"
    hint "machine without one: docker network create $EXTERNAL_NETWORK"
  fi
}

check_git_dir() {
  dir="$(value_of PHYLO_GIT_DIR)"
  dir="${dir:-./.git}"
  case "$dir" in /*) path="$dir" ;; *) path="$ROOT/${dir#./}" ;; esac
  if [ ! -d "$path" ]; then
    if [ -f "$path" ]; then
      fail "$dir is a file, not a directory (a git worktree or submodule checkout): the image build cannot read it"
    else
      fail "$dir does not exist: the image build needs it to record the deployed commit"
    fi
    hint "set PHYLO_GIT_DIR=config/no-git in the env file to build without git information"
    return 0
  fi
  if [ -f "$path/HEAD" ]; then
    ok "git information for the image build: $dir"
  else
    warn "$dir holds no git data: results will not record which commit produced them"
  fi
}

check_volumes() {
  for volume in $VOLUMES; do
    if docker volume inspect "$volume" >/dev/null 2>&1; then
      ok "volume $volume exists: its data will be used as it is"
    else
      ok "volume $volume does not exist yet: it will be created empty (fresh installation)"
    fi
  done
}

# ----------------------------------------------------------------------------
check_containers() {
  services="$(compose config --services 2>/dev/null | sort)"
  if [ -z "$services" ]; then
    fail "the list of services could not be read from docker-compose.yml"
    return 1
  fi
  for service in $services; do
    id="$(compose ps -a -q "$service" 2>/dev/null | head -n 1)"
    if [ -z "$id" ]; then
      fail "$service: no container (start the stack with ./run.sh prod)"
      continue
    fi
    state="$(docker inspect -f '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.RestartCount}}' "$id" 2>/dev/null)"
    status="${state%%|*}"; rest="${state#*|}"; health="${rest%%|*}"; rest="${rest#*|}"; code="${rest%%|*}"; restarts="${rest#*|}"
    if [ "$service" = "minio-init" ]; then
      # A one-off job: it creates the buckets and the methods' storage user.
      if [ "$status" = "exited" ] && [ "$code" = "0" ]; then ok "$service: finished successfully (buckets and storage user created)"
      elif [ "$status" = "running" ]; then warn "$service: still running"
      else fail "$service: ended with exit code $code (docker compose logs minio-init)"; fi
      continue
    fi
    if [ "$status" != "running" ]; then
      fail "$service: $status (docker compose logs $service)"
    elif [ "$health" = "unhealthy" ]; then
      fail "$service: running but unhealthy (docker compose logs $service)"
    elif [ "$health" = "starting" ]; then
      warn "$service: still starting"
    elif [ "${restarts:-0}" -gt 0 ] 2>/dev/null; then
      warn "$service: running, restarted $restarts time(s) since it was created"
    else
      [ "$health" = "healthy" ] && ok "$service: running, healthy" || ok "$service: running"
    fi
  done
}

check_inside() {
  # Database, migrations, buckets, method services, version information and
  # email, asked from inside the API container (the only place that can).
  out="$(compose exec -T api-prod python -m apps.api.scripts.deploy_check 2>&1)"
  code=$?
  lines="$(echo "$out" | grep -E '^  (OK  |WARN|FAIL)  ')"
  if [ -z "$lines" ]; then
    fail "the check inside the API container did not run:"
    echo "$out" | sed -n '1,5p' | while IFS= read -r line; do hint "$line"; done
    return 0
  fi
  echo "$lines" | sed -e 's/^  OK    /  OK    /' -e 's/^  WARN  /  WARN  /' -e 's/^  FAIL  /  FAIL  /'
  failures=$((failures + $(echo "$lines" | grep -c '^  FAIL')))
  warnings=$((warnings + $(echo "$lines" | grep -c '^  WARN')))
  [ "$code" -eq 0 ] || [ "$(echo "$lines" | grep -c '^  FAIL')" -gt 0 ] || fail "the check inside the API container ended with exit code $code"
}

# ----------------------------------------------------------------------------
if [ "$MODE" = "preflight" ]; then
  echo "Before starting:"
  if check_docker && check_env_file; then
    check_compose_config
    check_ports
    check_resource_plan
    check_network
    check_git_dir
    check_volumes
  fi
else
  echo "Running deployment:"
  if check_docker; then
    check_containers
    check_inside
  fi
fi

echo
if [ "$failures" -gt 0 ]; then
  echo "$failures problem(s) to fix, $warnings warning(s)."
  exit 1
fi
if [ "$MODE" = "preflight" ]; then
  echo "Ready to start ($warnings warning(s)):  docker compose --profile prod up -d --build"
else
  echo "The deployment is complete ($warnings warning(s))."
fi
