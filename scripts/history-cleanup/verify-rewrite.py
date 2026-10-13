#!/usr/bin/env python3
"""Prove that a rewritten mirror differs from the original only as intended.

    python3 scripts/history-cleanup/verify-rewrite.py ORIGINAL.git REWRITTEN.git

ORIGINAL is an untouched mirror clone of the same repository (take a copy
before running rewrite-mirror.sh); REWRITTEN is the mirror after it.

Checked, for every branch and every tag:
  1. the same branches and tags exist;
  2. the files at each tip are identical (same paths, same modes, same content
     ids, submodule pointers included), except that the removed files are gone;
  3. no removed path is left anywhere in the rewritten history, and none of the
     removed file versions is still stored in it;
  4. no credential is recognisable anywhere in it (scripts/scan_secrets.py);
  5. every remaining commit keeps its author, committer, both dates and its
     message, and the shape of history (number of merges) is unchanged;
  6. the commits that disappeared are exactly those that changed nothing but
     removed files;
  7. annotated tags keep their tagger, date and message.

Prints a summary and exits 1 if any check fails. Reads both repositories only.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REMOVED = re.compile(r"(^|/)(\.env|\.DS_Store)$")
PUSHED = ("refs/heads/", "refs/tags/")


def git(repo: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if check and done.returncode != 0:
        raise SystemExit(f"verify-rewrite: git {' '.join(args[:2])} failed in {repo}: {done.stderr.decode(errors='replace')[:200]}")
    return done.stdout.decode("utf-8", "replace")


def refs(repo: Path) -> dict[str, str]:
    out = {}
    for line in git(repo, "for-each-ref", "--format=%(objectname) %(refname)").splitlines():
        sha, name = line.split(" ", 1)
        if name.startswith(PUSHED):
            out[name] = sha
    return out


def tree(repo: Path, ref: str) -> set[str]:
    """One line per file at ``ref``: mode, type, content id, path."""
    return {line for line in git(repo, "ls-tree", "-r", "--full-tree", f"{ref}^{{commit}}").splitlines() if line}


def commits(repo: Path) -> list[tuple[str, ...]]:
    """(id, author, author date, committer, committer date, parent count, message) of every commit on a branch or tag."""
    fmt = "%H%x1f%an <%ae>%x1f%aI%x1f%cn <%ce>%x1f%cI%x1f%P%x1f%B%x1e"
    names = list(refs(repo))
    raw = git(repo, "log", f"--format={fmt}", *names) if names else ""
    out = []
    for record in raw.split("\x1e"):
        record = record.lstrip("\n")
        if not record:
            continue
        sha, author, adate, committer, cdate, parents, message = record.split("\x1f")
        out.append((sha, author, adate, committer, cdate, str(len(parents.split())), message.strip()))
    return out


def annotated_tags(repo: Path) -> dict[str, tuple[str, ...]]:
    out = {}
    fmt = "%(refname)%1f%(objecttype)%1f%(taggername) %(taggeremail)%1f%(taggerdate:iso-strict)%1f%(contents)%1e"
    for record in git(repo, "for-each-ref", f"--format={fmt}", "refs/tags").split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        name, kind, tagger, date, message = record.split("\x1f")
        if kind == "tag":
            out[name] = (tagger, date, message.strip())
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    original, rewritten = Path(argv[0]).resolve(), Path(argv[1]).resolve()
    failures: list[str] = []

    def result(ok: bool, text: str) -> None:
        print(f"  {'OK  ' if ok else 'FAIL'}  {text}")
        if not ok:
            failures.append(text)

    print(f"original:  {original}\nrewritten: {rewritten}\n")

    # 1. branches and tags
    before, after = refs(original), refs(rewritten)
    missing, extra = sorted(set(before) - set(after)), sorted(set(after) - set(before))
    branches = sum(1 for r in before if r.startswith("refs/heads/"))
    result(not missing and not extra,
           f"same {branches} branches and {len(before) - branches} tags" if not missing and not extra
           else f"refs differ: missing {missing}, unexpected {extra}")

    # 2. files at every tip
    different, removed_at_tips = [], 0
    for name in sorted(set(before) & set(after)):
        old = tree(original, name)
        kept = {line for line in old if not REMOVED.search(line.split("\t", 1)[1])}
        removed_at_tips += len(old) - len(kept)
        if kept != tree(rewritten, name):
            different.append(name)
    result(not different, f"files at every tip are identical apart from the removed ones "
                          f"({removed_at_tips} removed file entries across all tips)" if not different
           else f"file contents differ at: {different}")

    # 3. nothing of the removed files is left
    listing = git(rewritten, "rev-list", "--all", "--objects").splitlines()
    leftover_paths = sorted({line.split(" ", 1)[1] for line in listing if " " in line and REMOVED.search(line.split(" ", 1)[1])})
    result(not leftover_paths, "no removed path anywhere in the rewritten history" if not leftover_paths
           else f"removed paths still present: {leftover_paths[:10]}")
    old_objects: dict[str, set[str]] = {}
    for line in git(original, "rev-list", "--all", "--objects").splitlines():
        sha, _, path = line.partition(" ")
        if path:
            old_objects.setdefault(sha, set()).add(path)
    removed_only = {sha for sha, paths in old_objects.items() if all(REMOVED.search(p) for p in paths)}
    still_stored = [sha for sha in removed_only
                    if subprocess.run(["git", "-C", str(rewritten), "cat-file", "-e", sha], capture_output=True).returncode == 0]
    result(not still_stored, f"none of the {len(removed_only)} removed file versions is stored in the rewritten repository"
           if not still_stored else f"{len(still_stored)} removed file version(s) are still stored (run git gc --prune=now)")

    # 4. credentials
    spec = importlib.util.spec_from_file_location("scan_secrets", Path(__file__).resolve().parents[1] / "scan_secrets.py")
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    forbidden, findings, scanned = scanner.scan_history(rewritten)
    kinds = Counter(kind for kind, *_ in findings)
    result(not forbidden and not findings, f"no credential and no forbidden file in {scanned} file versions"
           if not forbidden and not findings else f"scanner still finds: {dict(kinds)}; forbidden files: {sorted(forbidden)[:5]}")
    _, old_findings, _ = scanner.scan_history(original)
    print(f"        (the original has {len({(k, v) for k, _, _, v in old_findings})} credential value(s) "
          f"and {len(scanner.scan_history(original)[0])} forbidden path(s))")

    # 5 + 6. commits
    old_commits, new_commits = commits(original), commits(rewritten)
    identity = lambda c: c[1:5] + (c[6],)                     # noqa: E731 - author, dates, committer, message
    old_count, new_count = Counter(map(identity, old_commits)), Counter(map(identity, new_commits))
    invented = new_count - old_count
    result(not invented, f"all {len(new_commits)} remaining commits keep author, committer, dates and message"
           if not invented else f"{sum(invented.values())} commit(s) in the rewritten history match no original commit")
    commit_map = {}
    map_file = rewritten / "filter-repo" / "commit-map"
    if map_file.is_file():
        for line in map_file.read_text().splitlines()[1:]:
            old_sha, new_sha = line.split()
            commit_map[old_sha] = new_sha
    dropped = [c for c in old_commits if set(commit_map.get(c[0], "x")) == {"0"}] if commit_map else []
    expected_drop = len(old_commits) - len(new_commits)
    not_empty = []
    for commit in dropped:
        touched = [p for p in git(original, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--root", commit[0]).splitlines() if p]
        if any(not REMOVED.search(p) for p in touched):
            not_empty.append(commit[0][:10])
    result(bool(commit_map) and len(dropped) == expected_drop and not not_empty,
           f"{len(old_commits)} commits before, {len(new_commits)} after: the {expected_drop} that disappeared changed "
           f"nothing but removed files" if commit_map and len(dropped) == expected_drop and not not_empty
           else f"commit accounting does not add up: {expected_drop} fewer commits, {len(dropped)} recorded as dropped, "
                f"dropped although they changed other files: {not_empty}; commit-map present: {bool(commit_map)}")
    merges = lambda cs: sum(1 for c in cs if int(c[5]) > 1)   # noqa: E731
    dropped_merges = merges(dropped)
    result(merges(old_commits) - dropped_merges == merges(new_commits),
           f"shape of history unchanged ({merges(new_commits)} merge commits)"
           if merges(old_commits) - dropped_merges == merges(new_commits)
           else f"merge commits: {merges(old_commits)} before, {merges(new_commits)} after")

    # 7. annotated tags
    old_tags, new_tags = annotated_tags(original), annotated_tags(rewritten)
    result(old_tags == new_tags, f"{len(new_tags)} annotated tags keep tagger, date and message" if old_tags == new_tags
           else f"annotated tags differ: {sorted(set(old_tags) ^ set(new_tags)) or 'same names, different content'}")

    changed = sum(1 for name in before if after.get(name) != before[name])
    print(f"\n{changed} of {len(before)} branch and tag ids change (every clone must be replaced, see docs/HISTORY-CLEANUP.md).")
    if failures:
        print(f"\nverify-rewrite: {len(failures)} check(s) FAILED. Do not publish this mirror.")
        return 1
    print("\nverify-rewrite: all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
