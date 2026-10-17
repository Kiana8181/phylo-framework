#!/usr/bin/env python3
"""Look for committed credentials. Never prints one.

    python3 scripts/scan_secrets.py              files tracked by git (what CI runs)
    python3 scripts/scan_secrets.py --history    every revision reachable from any
                                                 ref, the reflog and the stash

Two things are reported:

  * files that must not be in a repository at all: env files other than
    ``.env.example``, private-key files, ``.DS_Store``;
  * credentials recognisable by their format (provider API keys and client
    secrets, access tokens, private-key blocks, passwords inside URLs).

A finding is shown as its kind, where it is, and a fingerprint: the first eight
hex characters of the SHA-256 of the value, and its length. That is enough to
tell two findings apart, or to check a value you hold against the report
(``printf %s "$VALUE" | shasum -a 256``), and useless for recovering it.

Exit code 1 when anything was found. A line that must contain something
credential-shaped on purpose (a test fixture, documentation of a format) can
carry the marker ``scan-secrets: fake`` on the same line.

Standard library only; needs the ``git`` command.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional

MARKER = b"scan-secrets: fake"
MAX_BYTES = 3_000_000

# Paths that have no place in a repository, whatever they contain.
FORBIDDEN_PATH = re.compile(
    r"(^|/)(\.env(\.(?!example$)[^/]*)?|\.DS_Store|id_rsa[^/]*|id_ed25519[^/]*|[^/]+\.(pem|key|p12|pfx|keystore))$"
)

# Formats that identify a credential on sight. Each pattern's own source text
# does not match it, so this file never reports itself.
CREDENTIALS: dict[str, re.Pattern[bytes]] = {
    "Resend API key": re.compile(rb"\bre_[A-Za-z0-9]{6,}_[A-Za-z0-9]{16,}\b"),
    "Google OAuth client secret": re.compile(rb"\bGOCSPX-[A-Za-z0-9_-]{20,}"),
    "AWS access key id": re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "Slack token": re.compile(rb"\bxox[abprs]-[A-Za-z0-9-]{20,}\b"),
    "Stripe key": re.compile(rb"\b[sr]k_live_[A-Za-z0-9]{20,}\b"),
    "SendGrid key": re.compile(rb"\bSG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b"),
    "Private key block": re.compile(rb"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    "Password inside a URL": re.compile(rb"\b[a-z][a-z0-9+.-]*://[^\s:/@'\"`]+:([^\s@/'\"`${}<>*]{8,})@[A-Za-z0-9.-]+"),
}
# Passwords that are placeholders by their look: they say what they are.
# Anything in .env.example is added to these at run time: an example value is
# public by definition. Only the URL detector uses this; a provider key is
# reported whatever it looks like.
PLACEHOLDER = re.compile(
    rb"(?i)^(.*(secret|password|passwd|example|placeholder|change[-_ ]?me|dummy|redacted).*|your[-_a-z]*|x{3,}|<.*>|"
    rb"\[.*\]|pass\d*|user:?pass.*|phylo_[a-z_]*|minioadmin|postgres|test[-_a-z0-9]*|.*[-_]test[-_a-z0-9]*|\.{3,}|%s|\{.*)$"
)


def git(repo: Path, *args: str, stdin: Optional[bytes] = None) -> bytes:
    done = subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True)
    if done.returncode != 0:
        raise SystemExit(f"scan-secrets: git {args[0]} failed: {done.stderr.decode(errors='replace').strip()[:200]}")
    return done.stdout


def fingerprint(value: bytes) -> str:
    return f"{hashlib.sha256(value).hexdigest()[:8]}/{len(value)}"


def example_values(blobs: Iterable[bytes]) -> set[bytes]:
    values: set[bytes] = set()
    for data in blobs:
        for match in re.finditer(rb"^[ \t]*#?[ \t]*[A-Z][A-Z0-9_]*[ \t]*=[ \t]*['\"]?([^\s'\"#]+)", data, re.M):
            values.add(match.group(1))
            # ...and a password that is part of an example URL.
            inner = re.match(rb"[a-z][a-z0-9+.-]*://[^:@/]+:([^@/]+)@", match.group(1))
            if inner:
                values.add(inner.group(1))
    return values


def scan_content(data: bytes, known_examples: set[bytes]) -> list[tuple[str, int, bytes]]:
    """(kind, line number, value) for every credential in ``data``."""
    if b"\0" in data[:8000] or len(data) > MAX_BYTES:
        return []
    found = []
    for kind, pattern in CREDENTIALS.items():
        for match in pattern.finditer(data):
            value = match.group(1) if match.groups() else match.group(0)
            line_start = data.rfind(b"\n", 0, match.start()) + 1
            line_end = data.find(b"\n", match.end())
            if MARKER in data[line_start: line_end if line_end != -1 else len(data)]:
                continue
            if kind == "Password inside a URL" and (value in known_examples or PLACEHOLDER.match(value)):
                continue
            found.append((kind, data.count(b"\n", 0, match.start()) + 1, value))
    return found


# --------------------------------------------------------------------------- #
def scan_tracked(repo: Path) -> tuple[list[str], list[tuple[str, str, int, bytes]]]:
    paths = [p for p in git(repo, "ls-files", "-z").decode("utf-8", "replace").split("\0") if p]
    forbidden = sorted(p for p in paths if FORBIDDEN_PATH.search(p))
    readable = [(p, repo / p) for p in paths if (repo / p).is_file()]
    known = example_values(f.read_bytes() for p, f in readable if p.endswith(".env.example"))
    findings = []
    for path, file in readable:
        try:
            data = file.read_bytes()
        except OSError:
            continue
        findings += [(kind, path, line, value) for kind, line, value in scan_content(data, known)]
    return forbidden, findings


def scan_history(repo: Path) -> tuple[dict[str, int], list[tuple[str, str, int, bytes]], int]:
    """Every blob reachable from any ref, the reflog and the stash."""
    listing = git(repo, "rev-list", "--all", "--reflog", "--objects").decode("utf-8", "replace").splitlines()
    paths: dict[str, set[str]] = defaultdict(set)
    for line in listing:
        sha, _, path = line.partition(" ")
        if path:
            paths[sha].add(path)
    kinds = git(repo, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                stdin="\n".join(paths).encode()).decode().splitlines()
    blobs = [parts[0] for parts in (line.split() for line in kinds) if parts[1] == "blob" and int(parts[2]) <= MAX_BYTES]

    forbidden: dict[str, int] = defaultdict(int)
    for sha in blobs:
        for path in paths[sha]:
            if FORBIDDEN_PATH.search(path):
                forbidden[path] += 1                                 # number of distinct versions of the file
    known = example_values(git(repo, "cat-file", "blob", sha) for sha in blobs
                           if any(p.endswith(".env.example") for p in paths[sha]))
    findings = []
    for sha in blobs:
        data = git(repo, "cat-file", "blob", sha)
        for kind, line, value in scan_content(data, known):
            for path in sorted(paths[sha]):
                findings.append((kind, path, line, value))
    return dict(forbidden), findings, len(blobs)


def report(forbidden, findings, *, history: bool, scanned: Optional[int] = None) -> int:
    where = "history" if history else "tracked files"
    if forbidden:
        print(f"Files that must not be in a repository ({where}):")
        for path in sorted(forbidden):
            extra = f"  ({forbidden[path]} version(s))" if history else ""
            print(f"  {path}{extra}")
    by_kind: dict[str, dict[bytes, set[str]]] = defaultdict(lambda: defaultdict(set))
    for kind, path, line, value in findings:
        by_kind[kind][value].add(path if history else f"{path}:{line}")
    if by_kind:
        print(f"Credentials recognised by their format ({where}):")
        for kind in sorted(by_kind):
            print(f"  {kind}: {len(by_kind[kind])} distinct value(s)")
            for value, places in sorted(by_kind[kind].items(), key=lambda item: fingerprint(item[0])):
                listed = sorted(places)
                more = f" (+{len(listed) - 6} more)" if len(listed) > 6 else ""
                print(f"    {fingerprint(value)}  in {', '.join(listed[:6])}{more}")
    total = len(forbidden) + sum(len(values) for values in by_kind.values())
    scope = f"{scanned} file versions in every ref, the reflog and the stash" if history else "the files tracked by git"
    if total:
        print(f"\nscan-secrets: {len(forbidden)} forbidden file(s) and "
              f"{sum(len(v) for v in by_kind.values())} credential value(s) found in {scope}.")
        print("scan-secrets: see docs/HISTORY-CLEANUP.md. A credential that was ever committed must be replaced "
              "at its provider; removing it from the repository does not make it secret again.")
        return 1
    print(f"scan-secrets: nothing found in {scope}.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Look for committed credentials. Never prints one.")
    parser.add_argument("--history", action="store_true", help="scan every revision, not only the tracked files")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent,
                        help="repository to scan (default: this one); a bare repository needs --history")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    if args.history:
        forbidden, findings, scanned = scan_history(repo)
        return report(forbidden, findings, history=True, scanned=scanned)
    forbidden, findings = scan_tracked(repo)
    return report({p: 1 for p in forbidden}, findings, history=False)


if __name__ == "__main__":
    sys.exit(main())
