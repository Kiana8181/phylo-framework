#!/usr/bin/env bash
#
# Dependency vulnerability gate, used by CI and runnable locally.
#
#   scripts/security-audit.sh            # npm + Python
#   scripts/security-audit.sh npm        # JavaScript only
#   scripts/security-audit.sh python     # Python only
#
# Fails when:
#   - a production npm dependency has a high or critical advisory, or
#   - any package in a requirements.lock has a known advisory that is not
#     listed in .github/pip-audit-ignore.txt.
# Development-only npm advisories are printed but do not fail the gate; the
# accepted ones are listed in docs/SECURITY-AUDIT.md.
#
# Python: needs pip-audit on PATH (pip install pip-audit==2.10.1).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
what="${1:-all}"
status=0

if [[ "$what" == "all" || "$what" == "npm" ]]; then
  echo "==> npm audit (production dependencies, fail on high/critical)"
  npm audit --omit=dev --audit-level=high || status=1
  echo
  echo "==> npm audit (all dependencies, informational)"
  npm audit --audit-level=critical || echo "(development-only advisories above do not fail this gate)"
  echo
fi

if [[ "$what" == "all" || "$what" == "python" ]]; then
  ignore_args=()
  while IFS= read -r line; do
    line="${line%%#*}"; line="$(echo "$line" | tr -d '[:space:]')"
    [[ -n "$line" ]] && ignore_args+=(--ignore-vuln "$line")
  done < "$ROOT/.github/pip-audit-ignore.txt"

  for lock in apps/api/requirements.lock services/gctree/requirements.lock services/clonaltree/requirements.lock; do
    echo "==> pip-audit $lock"
    # --no-deps/--disable-pip: the lock already lists every package at an exact
    # version, so nothing is resolved or installed.
    pip-audit -r "$lock" --no-deps --disable-pip --progress-spinner off ${ignore_args[@]+"${ignore_args[@]}"} || status=1
    echo
  done
fi

if [[ $status -ne 0 ]]; then
  echo "Security audit FAILED. See docs/SECURITY-AUDIT.md for how to triage." >&2
fi
exit $status
