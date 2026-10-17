#!/usr/bin/env bash
#
# One entry point for running phylo-framework.
#
#   ./run.sh              choose a mode interactively (development or production)
#   ./run.sh prod         start or update the production stack
#   ./run.sh check        can the production stack start? (changes nothing)
#   ./run.sh status       is the running production stack complete?
#   ./run.sh ports        show and check the internal ports
#   ./run.sh ports randomize [--all]   store random internal ports in .env
#   ./run.sh down         stop the production stack (data volumes are kept)
#
# Production needs Docker with Compose 2.17+ and nothing else: no Node, no
# Python on the host. `./run.sh prod` is a convenience, not a requirement. It
# runs the pre-start check, stores the container limits for the resource
# budget in .env, and then runs exactly
#
#     docker compose --profile prod up -d --build
#
# which you may also run yourself. Arguments after `prod` are passed on to
# that command (for example `./run.sh prod --no-build`).
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die(){ echo "ERROR: $*" >&2; exit 1; }

usage(){ sed -n '3,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

need_docker(){ command -v docker >/dev/null 2>&1 || die "Docker not found"; }

prod_up(){
  need_docker
  cd "$ROOT"
  # Per-container limits for the budget in .env (see .env.example). Written
  # first, so that the check below sees the limits that will be used.
  [[ -f .env ]] || die ".env not found: cp .env.example .env, then set the secrets listed at its top"
  sh scripts/resource-plan.sh --write >/dev/null || die "Resource budget is not usable: sh scripts/resource-plan.sh"
  sh scripts/deploy-check.sh || die "Not started. Fix the problems above, then run ./run.sh prod again."
  echo
  # --no-build is this script's only own option: start what is already built.
  local build=(--build) extra=() arg
  for arg in "$@"; do
    if [[ "$arg" == "--no-build" ]]; then build=(); else extra+=("$arg"); fi
  done
  exec docker compose --profile prod up -d ${build[@]+"${build[@]}"} ${extra[@]+"${extra[@]}"}
}

case "${1:-}" in
  prod) shift; prod_up "$@" ;;
  check) need_docker; exec sh "$ROOT/scripts/deploy-check.sh" ;;
  status) need_docker; exec sh "$ROOT/scripts/deploy-check.sh" --running ;;
  ports) shift; exec sh "$ROOT/scripts/ports.sh" "$@" ;;
  down) need_docker; cd "$ROOT"; exec docker compose --profile prod down ;;
  -h|--help|help) usage; exit 0 ;;
  "") ;;
  *) usage >&2; die "Unknown command: $1" ;;
esac

# Interactive: the development modes need Node anyway, and with Node the menu
# is nicer. Without Node the same three choices are offered in plain text.
if command -v node >/dev/null 2>&1 && [[ -f "$ROOT/scripts/select-mode.mjs" && -d "$ROOT/node_modules/inquirer" ]]; then
  exec node "$ROOT/scripts/select-mode.mjs"
fi

echo "phylo-framework runner"
echo "1) Dev - methods in Docker + local API/Web"
echo "2) Dev - methods in local R/Python + local API/Web"
echo "3) Prod - docker compose"
read -rp "Enter 1/2/3: " choice
case "$choice" in
  1) exec "$ROOT/scripts/dev-with-docker.sh" ;;
  2) exec "$ROOT/scripts/dev-with-local-r.sh" ;;
  3) prod_up ;;
  *) die "Invalid choice" ;;
esac
