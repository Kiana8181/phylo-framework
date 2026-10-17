#!/usr/bin/env python3
"""Check the R packages installed in the R service images against OSV.

Container scanners do not understand R libraries, so the Dowser and BrepPhylo
images need their own check. This script asks each image for its installed R
packages (name + version), then queries the OSV database (https://osv.dev,
ecosystems "CRAN" and "Bioconductor") for advisories.

Only package names and versions are sent to OSV; no project data leaves the
machine.

Usage
    scripts/audit_r_packages.py                       # both R images
    scripts/audit_r_packages.py phylo-dowser:latest   # specific images
    scripts/audit_r_packages.py --out coverage/security

Exit status
    0  no advisory outside .github/r-audit-ignore.txt
    1  at least one un-ignored advisory
    2  an image could not be inspected or OSV could not be reached (never
       treated as "clean")

Limits: OSV's R coverage is young (the R Consortium advisory database), so few
advisories exist. An empty result means "nothing known", not "nothing wrong".
Requires: docker, python3 (standard library only).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGES = ["phylo-dowser:latest", "phylo-brepphylo:latest"]
OSV_BATCH = "https://api.osv.dev/v1/querybatch"
OSV_VULN = "https://api.osv.dev/v1/vulns/"
ECOSYSTEMS = ("CRAN", "Bioconductor")
R_SNIPPET = (
    'ip <- installed.packages()[, c("Package", "Version"), drop = FALSE];'
    'write.table(ip, sep = "\\t", quote = FALSE, row.names = FALSE, col.names = FALSE);'
    'cat("R\\t", as.character(getRversion()), "\\n", sep = "")'
)


def load_ignores() -> dict[str, str]:
    path = ROOT / ".github" / "r-audit-ignore.txt"
    ignores: dict[str, str] = {}
    if path.exists():
        reason = ""
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("#"):
                reason = (reason + " " + line.lstrip("# ")).strip()
            elif line:
                ignores[line.split()[0]] = reason
                reason = ""
            else:
                reason = ""
    return ignores


def installed_packages(image: str) -> dict[str, str]:
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--entrypoint", "Rscript", image, "-e", R_SNIPPET],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cannot list R packages in {image}: {result.stderr.strip()[-300:]}")
    packages: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0] and parts[1]:
            packages[parts[0]] = parts[1]
    if len(packages) < 10:
        raise RuntimeError(f"{image} reported only {len(packages)} R packages; refusing to treat that as a result")
    return packages


def post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def query_osv(pairs: list[tuple[str, str]]) -> dict[tuple[str, str], set[str]]:
    found: dict[tuple[str, str], set[str]] = {}
    for ecosystem in ECOSYSTEMS:
        for start in range(0, len(pairs), 500):
            chunk = pairs[start:start + 500]
            body = {"queries": [{"package": {"name": n, "ecosystem": ecosystem}, "version": v} for n, v in chunk]}
            results = post_json(OSV_BATCH, body).get("results", [])
            if len(results) != len(chunk):
                raise RuntimeError("OSV returned an incomplete answer")
            for pair, result in zip(chunk, results):
                for vuln in result.get("vulns") or []:
                    found.setdefault(pair, set()).add(vuln["id"])
    return found


def describe(vuln_id: str) -> tuple[str, str]:
    try:
        data = get_json(OSV_VULN + vuln_id)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return "", ""
    fixed = sorted({event["fixed"] for affected in data.get("affected", []) for rng in affected.get("ranges", [])
                    for event in rng.get("events", []) if event.get("fixed")})
    summary = " ".join((data.get("summary") or data.get("details") or "").split())[:110]
    return ", ".join(fixed), summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit installed R packages against OSV.")
    parser.add_argument("images", nargs="*", default=DEFAULT_IMAGES)
    parser.add_argument("--out", default=str(ROOT / "coverage" / "security"))
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ignores = load_ignores()

    per_image: dict[str, dict[str, str]] = {}
    try:
        for image in args.images:
            print(f"==> listing R packages in {image}", flush=True)
            per_image[image] = installed_packages(image)
        pairs = sorted({(name, version) for packages in per_image.values() for name, version in packages.items() if name != "R"})
        print(f"==> querying OSV for {len(pairs)} distinct package versions ({', '.join(ECOSYSTEMS)})", flush=True)
        found = query_osv(pairs)
    except (RuntimeError, urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"ERROR: R audit could not complete: {exc}", file=sys.stderr)
        return 2

    rows = []
    for (name, version), ids in sorted(found.items()):
        users = sorted(image for image, packages in per_image.items() if packages.get(name) == version)
        for vuln_id in sorted(ids):
            fixed, summary = describe(vuln_id)
            rows.append({"package": name, "version": version, "id": vuln_id, "fixed": fixed, "summary": summary,
                         "images": users, "ignored": vuln_id in ignores, "reason": ignores.get(vuln_id, "")})

    print()
    for image, packages in per_image.items():
        print(f"{image}: R {packages.get('R', '?')}, {len(packages) - ('R' in packages)} packages")
    if rows:
        print(f"\n{'package':18} {'version':10} {'advisory':14} {'fixed in':10} status    summary")
        for row in rows:
            status = "accepted" if row["ignored"] else "OPEN"
            print(f"{row['package']:18} {row['version']:10} {row['id']:14} {row['fixed'] or '-':10} {status:9} {row['summary']}")
    else:
        print("\nNo advisory found for any installed R package.")
    print("\nOSV's R coverage is limited: an empty or short list means nothing KNOWN, not nothing wrong.")

    (out_dir / "r-audit.json").write_text(json.dumps(
        {"images": {image: {"r_version": packages.get("R"), "packages": len(packages) - ("R" in packages)}
                    for image, packages in per_image.items()},
         "distinct_package_versions": len(pairs), "advisories": rows}, indent=2), encoding="utf-8")
    print(f"Report: {out_dir / 'r-audit.json'}")

    open_rows = [row for row in rows if not row["ignored"]]
    if open_rows:
        print(f"\nR AUDIT FAILED: {len(open_rows)} advisory(ies) not listed in .github/r-audit-ignore.txt", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
