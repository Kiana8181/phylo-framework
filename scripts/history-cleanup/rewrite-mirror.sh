#!/bin/sh
#
# Remove committed configuration and junk files from the WHOLE history of a
# mirror clone. Read docs/HISTORY-CLEANUP.md first.
#
#   scripts/history-cleanup/rewrite-mirror.sh /path/to/phylo-framework-mirror.git
#
# What is removed, from every commit of every branch and tag:
#   - every file named `.env`, in any directory (`.env.example` is kept)
#   - every `.DS_Store`
# Nothing else changes: other files, messages, authors and dates stay as they
# are. Commit ids change from the first affected commit onwards, and commits
# that touched nothing but removed files disappear.
#
# Safety:
#   - works only on a bare mirror clone, never on a working checkout;
#   - never pushes, and leaves the mirror WITHOUT a remote (git-filter-repo
#     removes `origin`), so nothing can be pushed from it by accident;
#   - keeps `filter-repo/commit-map` (old id -> new id) inside the mirror.
#
# Publishing the result is a separate, deliberate step described in the
# document above. It overwrites the remote's history and needs the repository
# owner's explicit decision.
#
# Needs git and git-filter-repo (https://github.com/newren/git-filter-repo;
# `pip install git-filter-repo` or `brew install git-filter-repo`).

set -eu

die() { echo "rewrite-mirror: $*" >&2; exit 1; }

[ $# -eq 1 ] || die "usage: $0 /path/to/mirror.git"
MIRROR="$1"
[ -d "$MIRROR" ] || die "$MIRROR is not a directory"
MIRROR="$(cd "$MIRROR" && pwd)"

command -v git >/dev/null 2>&1 || die "git not found"
git filter-repo --version >/dev/null 2>&1 || die "git-filter-repo not found (pip install git-filter-repo)"

[ "$(git -C "$MIRROR" rev-parse --is-bare-repository 2>/dev/null)" = "true" ] || \
  die "$MIRROR is not a bare repository. Make a mirror clone first: git clone --mirror <url> phylo-framework-mirror.git"
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
case "$MIRROR" in
  "$HERE"|"$HERE"/.git|"$HERE"/.git/*) die "refusing to rewrite the repository this script lives in; use a separate mirror clone" ;;
esac
[ ! -e "$MIRROR/filter-repo/commit-map" ] || die "$MIRROR was already rewritten (filter-repo/commit-map exists); start from a fresh mirror clone"

# What the mirror looked like before, for scripts/history-cleanup/verify-rewrite.py.
git -C "$MIRROR" for-each-ref --format='%(objectname) %(refname)' > "$MIRROR/refs-before-rewrite.txt"
before="$(git -C "$MIRROR" rev-list --all --count)"

# --invert-paths: keep everything EXCEPT the paths named. The two patterns are
# anchored on a path component, so `.env.example`, `env.py` and similar stay.
git -C "$MIRROR" filter-repo --force --invert-paths \
  --path-regex '(^|/)\.env$' \
  --path-regex '(^|/)\.DS_Store$'

after="$(git -C "$MIRROR" rev-list --all --count)"
echo
echo "rewrite-mirror: done. Commits reachable from any ref: $before before, $after after."
echo "rewrite-mirror: old-to-new commit ids are in $MIRROR/filter-repo/commit-map"
if git -C "$MIRROR" remote | grep -q .; then
  echo "rewrite-mirror: WARNING: the mirror still has a remote: $(git -C "$MIRROR" remote | tr '\n' ' ')" >&2
else
  echo "rewrite-mirror: the mirror has no remote; nothing was pushed and nothing can be pushed from it as it is."
fi
echo "rewrite-mirror: next: verify it (scripts/history-cleanup/verify-rewrite.py), then follow docs/HISTORY-CLEANUP.md."
