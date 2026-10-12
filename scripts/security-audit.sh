#!/usr/bin/env bash
#
# Vulnerability gates, used by CI and runnable locally.
#
#   scripts/security-audit.sh            # npm + Python (fast, no images needed)
#   scripts/security-audit.sh npm        # JavaScript only
#   scripts/security-audit.sh python     # Python only
#   scripts/security-audit.sh images     # built runtime images (Trivy)
#   scripts/security-audit.sh r          # R packages inside the R images (OSV)
#   scripts/security-audit.sh full       # everything above
#
# Fails when:
#   - a production npm dependency has a high or critical advisory;
#   - any package in a requirements.lock has a known advisory that is not
#     listed in .github/pip-audit-ignore.txt;
#   - (images) an image this project builds has a fixable critical finding that
#     is not listed in .github/trivy-ignore.txt, or an image cannot be scanned;
#   - (r) an installed R package has an advisory that is not listed in
#     .github/r-audit-ignore.txt.
# Development-only npm advisories are printed but do not fail the gate; the
# accepted ones are listed in docs/SECURITY-AUDIT.md.
#
# Python: needs pip-audit on PATH (pip install pip-audit==2.10.1).
# images / r: need Docker and the images built locally; reports are written to
# coverage/security/.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
what="${1:-all}"
status=0

case "$what" in
  all|npm|python|images|r|full) ;;
  *) echo "Unknown audit: $what (use npm, python, images, r, full)" >&2; exit 2 ;;
esac
want(){ [[ "$what" == "$1" || "$what" == "full" || ( "$what" == "all" && ( "$1" == "npm" || "$1" == "python" ) ) ]]; }

if want npm; then
  echo "==> npm audit (production dependencies, fail on high/critical)"
  npm audit --omit=dev --audit-level=high || status=1
  echo
  echo "==> npm audit (all dependencies, informational)"
  npm audit --audit-level=critical || echo "(development-only advisories above do not fail this gate)"
  echo
fi

if want python; then
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

if want images; then
  echo "==> image scan (Trivy, inside each image; fails on fixable critical findings)"
  python3 "$ROOT/scripts/scan_images.py" --fail-on-fixable critical || status=1
  echo
fi

if want r; then
  echo "==> R package audit (OSV)"
  python3 "$ROOT/scripts/audit_r_packages.py" || status=1
  echo
fi

if [[ $status -ne 0 ]]; then
  echo "Security audit FAILED. See docs/SECURITY-AUDIT.md for how to triage." >&2
fi
exit $status
