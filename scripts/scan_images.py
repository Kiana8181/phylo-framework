#!/usr/bin/env python3
"""Scan the runtime container images for known vulnerabilities.

How it works
    The scanner (Trivy) runs *inside* a throw-away container of each image, with
    its binary and its vulnerability database mounted read-only, and walks that
    container's own root filesystem (`trivy rootfs /`). Nothing is exported with
    `docker save`, so the 13 GB R images are scanned as reliably as the small
    ones, and peak disk use is the database (well under 1 GB) rather than a copy
    of every image. No Docker socket is handed to any container.

What it covers
    Operating-system packages and the language packages Trivy understands
    (Python, Node, Go binaries). R packages are NOT covered by Trivy: use
    scripts/audit_r_packages.py for those.

    Trivy has no vulnerability data for some distributions (Fedora, which the
    R images are built on). For those the table says "not assessed" instead of
    showing zeros, and the script asks the image's own package manager how
    many security updates are pending (`dnf updateinfo`, needs network access).

    Java archives (.jar/.war/.ear) are skipped unless --with-java is given:
    analysing them needs a second database of more than 1 GB, and the only
    ones in this project's images are two PHYLIP drawing GUIs in the R images,
    which ship without a Java runtime to run them.

Usage
    scripts/scan_images.py                      # scan the default image set
    scripts/scan_images.py phylo-api:latest     # scan specific images
    scripts/scan_images.py --out coverage/security --fail-on-fixable critical

Exit status
    0  scan completed and the gate passed
    1  the gate failed (a gated image has an un-ignored fixable finding at or
       above --fail-on-fixable)
    2  an image could not be scanned (reported, never treated as "clean")

Accepted findings live in .github/trivy-ignore.txt (one id per line, with the
reason). Requires: docker, python3.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRIVY_IMAGE = os.environ.get("TRIVY_IMAGE", "aquasec/trivy:0.75.0")
CACHE_VOLUME = os.environ.get("TRIVY_CACHE_VOLUME", "phylo-trivy-cache")
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]

# name -> (image reference, gated?). Gated images are the ones this project
# builds from bases it can rebuild; the gate applies to them. The R images sit
# on an end-of-life base and third-party images are patched upstream, so their
# findings are reported but do not fail the gate (see docs/SECURITY-AUDIT.md).
DEFAULT_IMAGES: dict[str, tuple[str, bool]] = {
    "web": ("phylo-web:latest", True),
    "api": ("phylo-api:latest", True),
    "gctree": ("phylo-gctree:latest", True),
    "clonaltree": ("phylo-clonaltree:latest", True),
    "dowser": ("phylo-dowser:latest", False),
    "brepphylo": ("phylo-brepphylo:latest", False),
}


def compose_third_party_images() -> dict[str, tuple[str, bool]]:
    """Postgres and the object store, exactly as docker-compose.yml pins them."""
    found: dict[str, tuple[str, bool]] = {}
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for service in ("postgres", "minio"):
        match = re.search(rf"^  {service}:\n(?:    .*\n|\n)*?    image: (\S+)", text, re.MULTILINE)
        if match:
            # `${VAR:-default}` -> the environment override if set, else the default.
            ref = re.sub(r"\$\{([A-Z_]+):-([^}]+)\}", lambda m: os.environ.get(m.group(1)) or m.group(2), match.group(1))
            found[service] = (ref, False)
    return found


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def image_platform(ref: str) -> str | None:
    result = run(["docker", "image", "inspect", ref, "--format", "{{.Os}}/{{.Architecture}}"])
    return result.stdout.strip() if result.returncode == 0 else None


def load_ignores() -> dict[str, str]:
    path = ROOT / ".github" / "trivy-ignore.txt"
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


class Scanner:
    def __init__(self, workdir: Path, out_dir: Path, with_java: bool = False):
        self.workdir = workdir
        self.out_dir = out_dir
        self.with_java = with_java
        self.binaries: dict[str, Path] = {}
        self.db_ready = False

    def binary_for(self, platform: str) -> Path:
        """Extract the static trivy binary matching the target image's platform."""
        if platform not in self.binaries:
            target = self.workdir / f"trivy-{platform.replace('/', '-')}"
            created = run(["docker", "create", "--platform", platform, TRIVY_IMAGE])
            if created.returncode != 0:
                raise RuntimeError(f"cannot fetch {TRIVY_IMAGE} for {platform}: {created.stderr.strip()[:300]}")
            container = created.stdout.strip()
            try:
                copied = run(["docker", "cp", f"{container}:/usr/local/bin/trivy", str(target)])
                if copied.returncode != 0:
                    raise RuntimeError(f"cannot copy the trivy binary: {copied.stderr.strip()[:300]}")
            finally:
                run(["docker", "rm", "-f", container])
            target.chmod(0o755)
            self.binaries[platform] = target
        return self.binaries[platform]

    def ensure_database(self) -> None:
        """Download the vulnerability database once, into a named volume."""
        if self.db_ready:
            return
        # Fetched here, once, so the scans themselves can run without any
        # network access. The Java index is only needed (and only downloaded)
        # with --with-java.
        wanted = [("--download-db-only", "vulnerability")]
        if self.with_java:
            wanted.append(("--download-java-db-only", "Java"))
        for flag, label in wanted:
            result = run(["docker", "run", "--rm", "-v", f"{CACHE_VOLUME}:/cache", TRIVY_IMAGE,
                          "image", flag, "--cache-dir", "/cache", "--quiet"])
            if result.returncode != 0:
                raise RuntimeError(f"cannot download the {label} database: {result.stderr.strip()[-400:]}")
        self.db_ready = True

    def scan(self, name: str, ref: str) -> dict:
        platform = image_platform(ref)
        if platform is None:
            # Third-party images (Postgres, the object store) may simply not have
            # been pulled yet on this machine; project images must be built.
            run(["docker", "pull", "--quiet", ref])
            platform = image_platform(ref)
        if platform is None:
            raise RuntimeError(f"image {ref} is not available locally and could not be pulled (build or pull it first)")
        binary = self.binary_for(platform)
        self.ensure_database()
        report = self.out_dir / f"{name}.trivy.json"
        report.unlink(missing_ok=True)
        cmd = [
            "docker", "run", "--rm", "--platform", platform,
            "--user", "0", "--network", "none", "--entrypoint", "/trivy-bin/trivy",
            "-v", f"{binary}:/trivy-bin/trivy:ro",
            "-v", f"{CACHE_VOLUME}:/trivy-cache:ro",
            "-v", f"{self.out_dir}:/trivy-out",
            "-e", "HOME=/tmp",
            ref,
            "rootfs", "--scanners", "vuln", "--quiet", "--timeout", "60m",
            "--cache-dir", "/trivy-cache", "--skip-db-update", "--skip-java-db-update", "--offline-scan",
            "--skip-dirs", "/proc", "--skip-dirs", "/sys", "--skip-dirs", "/dev",
            "--skip-dirs", "/trivy-cache", "--skip-dirs", "/trivy-out", "--skip-dirs", "/trivy-bin",
        ]
        if not self.with_java:
            # Absolute patterns: in rootfs mode paths are matched from "/".
            for pattern in ("/**/*.jar", "/**/*.war", "/**/*.ear"):
                cmd += ["--skip-files", pattern]
        cmd += ["--format", "json", "--output", f"/trivy-out/{report.name}", "/"]
        result = run(cmd)
        if result.returncode != 0 or not report.exists():
            raise RuntimeError(f"scan failed (exit {result.returncode}): {result.stderr.strip()[-500:]}")
        return json.loads(report.read_text(encoding="utf-8"))


def pending_distribution_updates(ref: str, platform: str) -> dict | None:
    """Security updates the image's own package manager knows about but the
    image does not have. Used when Trivy cannot assess the distribution."""
    result = run(["docker", "run", "--rm", "--platform", platform, "--user", "0", "--entrypoint", "sh", ref, "-c",
                  "command -v dnf >/dev/null 2>&1 || exit 97; timeout 900 dnf -q updateinfo list --security --available 2>/dev/null"])
    if result.returncode != 0:
        return None
    severities: collections.Counter = collections.Counter()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == "security":
            severities[parts[2]] += 1
    return {"total": sum(severities.values()), "by_severity": dict(severities)}


def summarize(data: dict, ignores: dict[str, str]) -> dict:
    total: collections.Counter = collections.Counter()
    fixable: collections.Counter = collections.Counter()
    ignored = 0
    actionable: list[tuple[str, str, str, str, str]] = []
    for result in data.get("Results") or []:
        for vuln in result.get("Vulnerabilities") or []:
            severity = vuln.get("Severity", "UNKNOWN")
            total[severity] += 1
            if not vuln.get("FixedVersion"):
                continue
            if vuln["VulnerabilityID"] in ignores:
                ignored += 1
                continue
            fixable[severity] += 1
            actionable.append((severity, vuln["PkgName"], vuln.get("InstalledVersion", ""),
                               vuln["FixedVersion"].split(",")[0].strip(), vuln["VulnerabilityID"]))
    os_info = (data.get("Metadata") or {}).get("OS") or {}
    # Trivy only emits an "os-pkgs" result for distributions it has data for.
    os_assessed = any(result.get("Class") == "os-pkgs" for result in data.get("Results") or [])
    return {
        "os": f"{os_info.get('Family', '?')} {os_info.get('Name', '')}".strip(),
        "os_assessed": os_assessed or not os_info,
        "eosl": bool(os_info.get("EOSL")),
        "total": dict(total), "fixable": dict(fixable), "ignored": ignored,
        "actionable": sorted(set(actionable), key=lambda row: (SEVERITIES.index(row[0]), row[1])),
        "targets": len(data.get("Results") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan runtime images with Trivy (rootfs mode).")
    parser.add_argument("images", nargs="*", help="image references (default: the project's image set)")
    parser.add_argument("--out", default=str(ROOT / "coverage" / "security"), help="directory for JSON reports")
    parser.add_argument("--fail-on-fixable", choices=["critical", "high", "none"], default="critical",
                        help="gate: fail when a gated image has an un-ignored fixable finding at this severity or above")
    parser.add_argument("--skip-third-party", action="store_true", help="do not scan Postgres and the object store")
    parser.add_argument("--with-java", action="store_true",
                        help="also analyse Java archives (downloads an extra database of more than 1 GB)")
    args = parser.parse_args()

    if args.images:
        images = {re.sub(r"[^A-Za-z0-9_.-]+", "_", ref): (ref, True) for ref in args.images}
    else:
        images = dict(DEFAULT_IMAGES)
        if not args.skip_third_party:
            images.update(compose_third_party_images())

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ignores = load_ignores()
    gate_levels = {"critical": ["CRITICAL"], "high": ["CRITICAL", "HIGH"], "none": []}[args.fail_on_fixable]

    summaries: dict[str, dict] = {}
    errors: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="phylo-trivy-") as tmp:
        scanner = Scanner(Path(tmp), out_dir, with_java=args.with_java)
        for name, (ref, _gated) in images.items():
            print(f"==> scanning {name} ({ref})", flush=True)
            try:
                summaries[name] = summarize(scanner.scan(name, ref), ignores)
                if not summaries[name]["os_assessed"]:
                    print(f"    Trivy has no data for '{summaries[name]['os']}'; asking the image's package manager instead",
                          flush=True)
                    summaries[name]["distribution_updates"] = pending_distribution_updates(ref, image_platform(ref) or "")
            except RuntimeError as exc:
                errors[name] = str(exc)
                print(f"    NOT SCANNED: {exc}", flush=True)

    print()
    width = max(12, *(len(n) for n in images))
    print(f"{'image':{width}} {'os':30} {'crit':>5} {'high':>5} {'med':>5} {'low':>5} | {'fixable crit/high':>18} | gate")
    gate_failed = []
    for name, (ref, gated) in images.items():
        if name in errors:
            print(f"{name:{width}} NOT SCANNED - see message above")
            continue
        s = summaries[name]
        blocking = sum(s["fixable"].get(level, 0) for level in gate_levels)
        if gated and blocking:
            gate_failed.append(name)
        verdict = ("FAIL" if blocking else "pass") if gated else "report only"
        os_label = s["os"] + (" (EOL)" if s["eosl"] else "")
        if not s["os_assessed"]:
            os_label += " [OS not assessed]"
            if gated:  # a gate that cannot see the OS packages proves nothing
                errors[name] = f"Trivy cannot assess OS packages of '{s['os']}'"
                verdict = "cannot gate"
        print(f"{name:{width}} {os_label[:30]:30} {s['total'].get('CRITICAL', 0):>5} {s['total'].get('HIGH', 0):>5} "
              f"{s['total'].get('MEDIUM', 0):>5} {s['total'].get('LOW', 0):>5} | "
              f"{s['fixable'].get('CRITICAL', 0):>8} /{s['fixable'].get('HIGH', 0):>8} | {verdict}")
    for name in images:
        s = summaries.get(name) or {}
        if s and not s["os_assessed"]:
            updates = s.get("distribution_updates")
            print(f"\n{name}: OS packages of '{s['os']}' are NOT covered by the numbers above (no Trivy data).")
            if updates is None:
                print("  The image's package manager could not be queried either: treat the OS layer as unassessed.")
            else:
                detail = ", ".join(f"{k}: {v}" for k, v in sorted(updates["by_severity"].items())) or "none"
                print(f"  Pending security updates according to the distribution itself: {updates['total']} ({detail}).")
                print("  This only counts advisories the distribution published; an end-of-life release publishes no new ones.")
    for name in images:
        rows = [r for r in summaries.get(name, {}).get("actionable", []) if r[0] in ("CRITICAL", "HIGH")]
        if rows:
            print(f"\n{name}: fixable critical/high findings")
            for severity, pkg, installed, fixed, vuln_id in rows[:25]:
                print(f"  {severity:8} {pkg} {installed} -> {fixed}  ({vuln_id})")
            if len(rows) > 25:
                print(f"  ... and {len(rows) - 25} more (see {out_dir / (name + '.trivy.json')})")

    (out_dir / "image-scan-summary.json").write_text(json.dumps(
        {"scanner": TRIVY_IMAGE, "images": {n: {"ref": images[n][0], "gated": images[n][1], **s} for n, s in summaries.items()},
         "not_scanned": errors, "ignored_ids": sorted(ignores)}, indent=2), encoding="utf-8")
    print(f"\nReports: {out_dir}")
    print("A clean result means no KNOWN vulnerability in what the scanner can see; it is not proof of absence.")
    if not args.with_java:
        print("Java archives (.jar/.war/.ear) were not analysed; add --with-java to include them.")

    if errors:
        print(f"\nERROR: {len(errors)} image(s) could not be fully scanned:", file=sys.stderr)
        for name, reason in errors.items():
            print(f"  {name}: {reason[:200]}", file=sys.stderr)
        return 2
    if gate_failed:
        print(f"\nGATE FAILED: fixable {'/'.join(gate_levels).lower()} findings in: {', '.join(gate_failed)}", file=sys.stderr)
        print("Rebuild with --pull, upgrade the package, or record an accepted risk in .github/trivy-ignore.txt.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
