#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die(){ echo "ERROR: $*" >&2; exit 1; }

if command -v node >/dev/null 2>&1 && [[ -f "$ROOT/scripts/select-mode.mjs" ]]; then
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
  3)
    command -v docker >/dev/null 2>&1 || die "Docker not found"
    if command -v node >/dev/null 2>&1; then
      node "$ROOT/scripts/method-services.mjs" sync-env >/dev/null
    fi
    # Per-container limits for the budget in .env (see .env.example).
    sh "$ROOT/scripts/resource-plan.sh" --write || die "Resource budget is not usable (see above)"
    exec docker compose --profile prod up -d --build
    ;;
  *) die "Invalid choice" ;;
esac
