# Dependency and image security audit

Last full audit: **2026-10-09**. This file records what was scanned, what was
fixed, and every finding that remains open with the reason it is still open.
It is not a claim that the project is free of vulnerabilities: scanners only
know published advisories, and the open items below are real.

## How to re-run the audit

```bash
# npm (production + development) and the three Python lock files.
# This is the same gate CI runs on every push, pull request and weekly.
pip install pip-audit==2.10.1
bash scripts/security-audit.sh

# Container images (OS packages + bundled binaries). Build first, then:
docker save phylo-api:latest -o /tmp/phylo-api.tar
docker run --rm -v /tmp:/scan aquasec/trivy:latest image --scanners vuln --input /scan/phylo-api.tar
```

Rebuild images with `--pull` so they pick up patched base images:

```bash
docker compose --profile prod build --pull
```

## What the CI gate enforces

The `security-audit` job in `.github/workflows/tests.yml` fails when:

- a **production** npm dependency has a high or critical advisory;
- any package in `apps/api/requirements.lock`, `services/gctree/requirements.lock`
  or `services/clonaltree/requirements.lock` has a known advisory that is not
  listed, with its reason, in `.github/pip-audit-ignore.txt`.

Development-only npm advisories are printed but do not fail the job (see
"Open findings" below). Container images and R packages are not scanned in CI;
re-run those by hand with the commands above when base images change.

## Dependency pinning

| Component | Direct pins | Full pinned set |
|---|---|---|
| Web (`apps/web`) | `package.json` | `package-lock.json` (`npm ci`) |
| API (`apps/api`) | `requirements.txt` | `requirements.lock` |
| GCtree | `requirements.txt` | `requirements.lock` |
| ClonalTree | `requirements.txt` | `requirements.lock` |
| Dowser, BrepPhylo | R packages from the dated CRAN snapshot `2026-07-20`; base image `immcantation/suite:4.6.0`; BrepPhylo pinned to a commit | none |

Each Python Dockerfile installs with `-r requirements.txt -c requirements.lock`,
so an image build installs exactly the versions that were tested and audited.
After changing a `requirements.txt`, regenerate the lock:

```bash
scripts/update-python-locks.sh            # keep current pins, add what is missing
scripts/update-python-locks.sh --upgrade  # also move indirect dependencies to the newest allowed
```

`apps/api/tests/test_dependency_locks.py` fails if a pin differs between the two
files or a Dockerfile stops using its lock.

## Fixed in this audit

### npm

| Before | After |
|---|---|
| Production: 16 advisories (3 critical, 7 high) | Production: **0** |
| All: 40 advisories (7 critical, 23 high) | All: 9 (2 critical, 5 high), development tooling only |

- `next` 15.4.10 → 15.5.27 (same major); `eslint-config-next` to match.
- `axios` 1.11.0 → 1.20.0.
- `next-auth` removed: no import, configuration or environment reference
  anywhere in the repository. This also removed `@auth/core`.
- `mermaid` removed: no reference anywhere (documentation diagrams are
  pre-rendered SVG files). This also removed `dompurify` and `katex`.
- `postcss` inside Next.js: Next 15 pins `postcss` 8.4.31. A root `overrides`
  entry makes it use the patched 8.5.x line (same major). The web app builds
  and its tests pass with it.
- `vitest` / `@vitest/coverage-v8` 3.2.4 → 3.2.7; transitive fixes through
  `npm audit fix` (no `--force`).
- `d3-transition` is now a declared dependency. The tree viewer's animated zoom
  always used it, but it was only installed because `mermaid` depended on it.
- Web image base `node:20` → `node:22`. Node.js 20 reached end of life in
  April 2026 and no longer receives security fixes; CI already used Node 22.

### Python

| Image | Advisories before | After |
|---|---|---|
| API | 27 distinct, in 7 packages | **0** |
| GCtree | 25 distinct, in 6 packages | **0** |
| ClonalTree | 13 distinct, in 5 packages | 1, accepted (Biopython, below) |

- API: `python-jose` replaced by `PyJWT` 2.15.1. This removes `python-jose`
  (algorithm-confusion and JWE-bomb advisories), `ecdsa` (timing attack with no
  fix available), `rsa` and `pyasn1`. Tokens are standard HS256 JWTs, so
  sessions issued before the change stay valid.
- API and GCtree: `fastapi` → 0.139.2 and `starlette` → 1.3.1 (the versions
  ClonalTree already ran), fixing eight Starlette advisories including
  request-URL/Host confusion and unbounded form parsing.
- API: `python-dotenv` 1.1.1 → 1.2.2.
- GCtree: `python-multipart` 0.0.9 → 0.0.32.
- All three: `urllib3` 2.7.0 → 2.8.0 through the lock files.
- API: `rq`, `redis`, `psycopg2-binary` and `python-multipart` removed. None is
  imported; the queue is the Postgres-backed worker, migrations use `asyncpg`,
  and the API parses no form bodies.
- All three images: `pip` → 26.2.1; GCtree and ClonalTree: `setuptools` →
  84.0.0 and `wheel` → 0.48.0.

Scientific pins (`gctree`, `ete3`, `numpy`, `scipy`, `biopython`, `pandas`,
`scikit-learn`, …) were **not** changed. The lock files freeze the indirect
scientific dependencies at the versions that were installed in the previously
tested images.

## Open findings

### 1. MinIO images are no longer distributed (action needed)

`minio/minio` and `minio/mc` cannot be pulled any more: Docker Hub returns
"repository does not exist" for both, and the `quay.io` mirror has no manifest.
`docker-compose.yml` pins both by digest and `docker-compose.test.yml` uses a
`RELEASE.2025-04-22` tag.

- **Impact on deployment:** a host that already has the images cached keeps
  working. A fresh host, or CI on a clean runner, cannot pull them and the
  stack will not start.
- **Impact on security:** the pinned server image is a September 2025 build
  that will never be patched. Trivy reports 7 critical and 102 high fixable
  findings in it, almost all in Go libraries compiled into the `minio` binary.
- **Exposure:** MinIO publishes no host port and is reachable only from this
  project's containers, so these are not reachable from the internet. An
  attacker would first need code execution inside one of the project's
  containers.
- **Why it is open:** replacing the object store, or building MinIO from
  source, is a deployment decision with data-migration consequences. It was
  not made in this audit.
- **Options:** (a) keep the cached image and export it with `docker save` so
  the server can be rebuilt (after `docker load` the compose file may need a
  local tag in place of the digest reference); (b) build MinIO from its source
  repository into a project-owned image; (c) move to another S3-compatible
  server. The API, worker and method services already speak plain S3
  (`STORAGE_BACKEND=s3`), so (c) needs no application code change, but the
  `minio-init` service (bucket creation and the write-only methods user) is
  MinIO-specific and would have to be replaced, and existing objects copied.

### 2. R service base image runs an end-of-life operating system

Dowser and BrepPhylo are built on `immcantation/suite:4.6.0` (April 2025),
which is Fedora 41. Fedora 41 no longer receives security updates, so OS-level
findings in these two images cannot be fixed by rebuilding.

- **Exposure:** both services are internal-only (no published port), read
  inputs from a read-only mount, and are reached only by the worker.
- **Why it is open:** `immcantation/suite` 4.7.0 and 4.8.0 exist, but they
  change the R, Dowser and IgPhyML versions. That alters the scientific
  environment and needs a deliberate upgrade with the scientific regression
  suite, not a security patch.
- **Mitigation planned:** Phase 3 places the method services on a Docker
  network with no outbound internet access.

### 3. R packages

540 distinct installed R packages (both images) were checked against the OSV
database (CRAN and Bioconductor ecosystems). Three advisories matched:

| Package | Advisory | Exposure |
|---|---|---|
| `gh` 1.4.1 | RSEC-2025-0, fixed in 1.5.0 | Not loaded by the services; present only as a dependency of `usethis` |
| `plotly` 4.10.4 | RSEC-2025-1, fixed in 4.12.0 | Not loaded by the services; dependency of `Seurat`/`enchantr` |
| `png` 0.1-7 | RSEC-2026-1, fixed in 0.1-9 | Applies to source installs on Windows with R < 4.2; the images are Linux with R 4.4.3 |

They ship inside the base image. Left as is; they go away with an
`immcantation/suite` upgrade.

### 4. Biopython `Bio.Entrez` XXE (CVE-2025-68463) in ClonalTree

`biopython` 1.85 is pinned for ClonalTree; the fix is in 1.87. The flaw is in
`Bio.Entrez`, the NCBI web client, which ClonalTree never imports. Biopython is
a scientific dependency, so it is only changed together with a scientific
regression run. Ignored in CI through `.github/pip-audit-ignore.txt`.

### 5. Development-only npm advisories (9)

| Chain | Advisories | Why it is open | Exposure |
|---|---|---|---|
| `vitest`, `@vitest/mocker`, `@vitest/coverage-v8`, `tinypool` | 2 critical, 2 moderate | The fix is Vitest 5, two major versions ahead; installing it fails peer-dependency resolution and would need `--force` | Test runner only. The file-read advisories need the Vitest UI/API server to be listening; the project only uses `vitest run`. Not in any production image |
| `eslint-config-next` → `fast-glob` → `micromatch` → `braces` | 5 high | No fixed release of `braces`/`micromatch` exists for this line; npm's only suggestion is a downgrade to `eslint-config-next` 14 | Linter only, run on the project's own files. Not in any production image |

### 6. `pip` bundles vulnerable copies of three libraries

Trivy flags `msgpack` 1.1.2, `setuptools` 70.3.0 and `urllib3` 2.7.0 in the
Python images. They are private copies inside `pip` 26.2.1 (`pip/_vendor`),
which is the newest `pip` release. `pip` is not run by any service at run time.
Resolved when a newer `pip` is released and the pin in the Dockerfiles is
raised.

### 7. Operating-system packages without a fix

Trivy reports OS findings with no fixed package available in the distribution
(Debian status `affected`, `fix_deferred` or `will_not_fix`). Rebuilding with
`--pull` is the only action available; they are listed per image below.

### 8. Postgres image

`postgres:15-alpine` has no findings in PostgreSQL or Alpine packages. The 22
fixable findings are all in the Go standard library compiled into `gosu`, the
helper the image uses once at start-up to drop privileges. It processes no
network input. Resolved when the upstream image is rebuilt.

### 9. Runtime end-of-life dates to plan for

| Runtime | Used by | Status |
|---|---|---|
| Python 3.10 | ClonalTree | End of life in October 2026. Moving to 3.11/3.12 needs a scientific regression run |
| `passlib` 1.7.4 | API password hashing | Unmaintained; imports a module removed in Python 3.13. Works on the API's Python 3.12 |
| PostgreSQL 15 | Database | Supported until November 2027 |

## Image scan results

Trivy 0.75.0, all severities, scanned from the locally built images.

| Image | Critical | High | Medium | Low | Fixable critical/high | Where the fixable ones are |
|---|---|---|---|---|---|---|
| `phylo-web` (Node 22, Debian 12) | 1 | 48 | 95 | 77 | 0 | — |
| `phylo-api` (Python 3.12, Debian 13) | 0 | 56 | 86 | 105 | 4 high | Copies bundled inside `pip` (finding 6) |
| `phylo-gctree` (Python 3.11, Debian 12) | 4 | 108 | 260 | 215 | 4 high | Copies bundled inside `pip` (finding 6) |
| `phylo-clonaltree` (Python 3.10, Debian 12) | 3 | 274 | 2212 | 1024 | 4 high | Copies bundled inside `pip` (finding 6) |
| `postgres:15-alpine` | 1 | 21 | 23 | 2 | 1 critical, 21 high | `gosu` helper binary (finding 8) |
| `minio/minio` (pinned digest) | 9 | 112 | 137 | 24 | 7 critical, 102 high | `minio` binary (finding 1) |
| `minio/mc` (pinned digest) | 2 | 51 | 97 | 20 | 2 critical, 45 high | `mc` binary (finding 1) |
| `phylo-dowser`, `phylo-brepphylo` | not scanned | | | | | Trivy failed to read the 13 GB image archive. Their OS is end-of-life Fedora 41 (finding 2); R packages were checked separately (finding 3) |

Before this audit the web image had 3 critical and 14 high **fixable** findings
(an outdated `perl-base` and the `npm` bundled in the base image). The runtime
stage now applies Debian updates and removes `npm`, `corepack` and `yarn`,
which the standalone server never runs.

Everything in the "Critical/High" columns that is not "fixable" has no patched
package in the distribution yet. In the ClonalTree image, 190 of the 277
critical/high entries are `linux-libc-dev` (kernel header files installed with
the compiler toolchain that builds MUSCLE); they are headers, not running code.
Moving the MUSCLE build to a separate build stage would remove the toolchain
from the final image. That restructuring is planned with the container
hardening in Phase 3.
