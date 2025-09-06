set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die(){ echo "ERROR: $*" >&2; exit 1; }

if command -v node >/dev/null 2>&1 && [ -f "$ROOT/scripts/select-mode.mjs" ]; then
  exec node "$ROOT/scripts/select-mode.mjs"
fi

echo "phylo-framework runner"
echo "1) Dev - methods in Docker"
echo "2) Dev - methods in local R"
echo "3) Prod - docker compose"
read -rp "Enter 1/2/3: " choice
case "$choice" in
  1) exec "$ROOT/scripts/dev-with-docker.sh" ;;
  2) exec "$ROOT/scripts/dev-with-local-r.sh" ;;
  3) command -v docker >/dev/null 2>&1 || die "Docker not found"; exec docker compose up -d --build ;;
  *) die "Invalid choice" ;;
esac
