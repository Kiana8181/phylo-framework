# Dependency and image security audit

Last full audit: **2026-10-12**; re-scanned on **2026-10-13** during system validation (see the end of "Image scan results"). This file records what was scanned, what was
fixed, and every finding that remains open with the reason it is still open.
It is not a claim that the project is free of vulnerabilities: scanners only
know published advisories, some components are outside what any scanner here
can see, and the open items below are real.

## What is scanned, and what is not

| Layer | Tool | Where it runs | Gate |
|---|---|---|---|
| npm packages (web, contracts) | `npm audit` | CI on every push, pull request and weekly | Fails on a high or critical advisory in a production dependency |
| Python packages (API, GCtree, ClonalTree lock files) | `pip-audit` | Same job | Fails on any advisory not listed in `.github/pip-audit-ignore.txt` |
| Runtime images: OS packages, Python/Node packages, Go binaries | Trivy, run inside each image | CI job that builds the images, on every push and weekly | Fails on a fixable critical finding in an image this project builds, or when an image cannot be scanned |
| R packages in the Dowser and BrepPhylo images | OSV database (CRAN, Bioconductor) | Same job | Fails on any advisory not listed in `.github/r-audit-ignore.txt` |

Not covered by any of the above:

- **Compiled scientific tools** inside the images (IgPhyML, PHYLIP `dnapars` /
  `dnaml`, RAxML-NG, MUSCLE, and R packages' compiled code). They are not
  installed through a package manager a scanner understands, so they produce
  no findings either way. They only ever process files that already passed the
  framework's input validation, inside containers with no internet access.
- **R packages beyond OSV's coverage.** The R advisory database is young and
  small. An empty result means nothing is known, not that nothing is wrong.
- **Rust binaries** (relevant to the object-store alternatives): Trivy cannot
  read their dependencies unless they were built with audit metadata.
- **The host**, the Docker daemon and the reverse proxy: owned by the
  infrastructure team.

## How to re-run the audit

```bash
pip install pip-audit==2.10.1
bash scripts/security-audit.sh          # npm + Python lock files (no images needed)
bash scripts/security-audit.sh images   # every runtime image (build them first)
bash scripts/security-audit.sh r        # R packages inside the two R images
bash scripts/security-audit.sh full     # all of the above
```

Image and R reports are written to `coverage/security/`.

### How large images are scanned

The two R images are about 13 GB each. Exporting them with `docker save` and
scanning the archive failed (the scanner could not read the archive) and needs
a second copy of every image on disk. `scripts/scan_images.py` instead starts a
throw-away container of each image with the scanner binary and its database
mounted read-only, and scans that container's own root filesystem. It needs no
image export, gives the scanned container no network access and no Docker
socket, and uses the same amount of disk for a 13 GB image as for a small one.

If an image cannot be scanned the script exits with an error; it never reports
an unscanned image as clean.

Rebuild images with `--pull` so they pick up patched base images:

```bash
docker compose --profile prod build --pull
```

## What the CI gates enforce

`security-audit` job (fast, every push and weekly):

- a **production** npm dependency with a high or critical advisory fails it;
- any package in `apps/api/requirements.lock`, `services/gctree/requirements.lock`
  or `services/clonaltree/requirements.lock` with an advisory that is not
  listed, with its reason, in `.github/pip-audit-ignore.txt` fails it.

`scientific-browser` job (after it has built every image):

- a **fixable critical** finding in the web, API, GCtree or ClonalTree image
  that is not listed in `.github/trivy-ignore.txt` fails it;
- an R package advisory that is not listed in `.github/r-audit-ignore.txt`
  fails it;
- the Dowser, BrepPhylo, Postgres and object-store images are scanned and
  reported but do not fail the job: the first two sit on an end-of-life base
  image (finding 2) and the last two are patched by their upstreams. Their
  reports are uploaded as build artifacts on every run.

Development-only npm advisories are printed but do not fail a job (finding 5).

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

### 1. Object store: MinIO replaced by the Silo fork; mirror still to do

Upstream MinIO no longer distributes images, and the build this project pinned
(9 critical / 120 high findings) would never have been patched. The stack now
runs **Silo** (`pgsty/silo`), the maintained community fork, pinned by digest.
Evidence, alternatives and trade-offs: [OBJECT-STORAGE-OPTIONS.md](./OBJECT-STORAGE-OPTIONS.md).

- **Scan of the adopted image:** 0 critical, 5 high. Four are in the Go
  standard library and `golang.org/x/net` (denial of service; fixed by a rebuild
  with a newer Go, which needs a new Silo release). One is reported against
  MinIO's S3 Select CSV parser; the fork patched it, and this project does not
  use S3 Select.
- **Exposure:** unchanged. The object store publishes no host port and is
  reachable only from this project's API, worker and method containers.
- **Residual risk 1 — availability:** the images come from the fork's Docker
  Hub repository. Mirroring them into a registry the group controls is a
  deployment prerequisite that has not been done yet (no such registry was
  available).
- **Residual risk 2 — maintenance:** Silo is a young fork with one dominant
  maintainer. Re-check its activity every few months; SeaweedFS is the
  documented fallback.

### 2. R service base image runs an end-of-life operating system

Dowser and BrepPhylo are built on `immcantation/suite:4.6.0` (April 2025),
which is Fedora 41, and Fedora 41 is end of life.

- **What was fixed:** the distribution had published 141 security updates
  (11 rated Important, none Critical; packages such as `expat`, `sqlite`, `pam`,
  `sudo`, `qt5-qtbase`) that the base image did not contain. Both Dockerfiles
  now apply them (`dnf upgrade --security`). After the rebuild the distribution
  reports 0 pending security updates. R 4.4.3, every R package version and the
  IgPhyML / PHYLIP / RAxML-NG binaries are byte-identical before and after, and
  Dowser and BrepPhylo produced identical trees on the regression dataset.
- **What stays open:** Fedora 41 publishes no new advisories. A vulnerability
  found from now on in one of its 1,312 OS packages will neither be fixed nor
  show up in any scan of these images.
- **What cannot be scanned:** Trivy has no vulnerability data for Fedora. For
  these two images it only assesses the pip- and npm-installed parts; the scan
  report says "OS not assessed" and shows the distribution's own count of
  pending updates instead. "0 pending" therefore means "everything the
  distribution ever published is applied", not "no known vulnerabilities".
- **Exposure:** both services are internal-only (no published port), have no
  route to the internet and none to the database, run without Linux
  capabilities, hold only the write-only object-store credential, and read
  inputs that already passed the framework's validation from a read-only mount.
- **Why the base is not upgraded here:** `immcantation/suite` 4.7.0 and 4.8.0
  exist, but they change the R, Dowser and IgPhyML versions. That alters the
  scientific environment and needs a deliberate upgrade with the scientific
  regression suite, not a security patch.
- **Also in the base image:** `pyarrow` 19.0.1 (one high finding, fixed in
  23.0.1), installed with pip for the Immcantation command-line tools. The R
  services do not load it.
- **Java archives:** the images contain two PHYLIP drawing GUIs
  (`DrawGram.jar`, `DrawTree.jar`) and no Java runtime, so they cannot run.
  They are skipped by the image scan unless `--with-java` is given.

### 3. R packages

540 distinct installed R packages (both images) were checked against the OSV
database (CRAN and Bioconductor ecosystems). Three advisories matched:

| Package | Advisory | Exposure |
|---|---|---|
| `gh` 1.4.1 | RSEC-2025-0, fixed in 1.5.0 | Not loaded by the services; present only as a dependency of `usethis` |
| `plotly` 4.10.4 | RSEC-2025-1, fixed in 4.12.0 | Not loaded by the services; dependency of `Seurat`/`enchantr` |
| `png` 0.1-7 | RSEC-2026-1, fixed in 0.1-9 | Applies to source installs on Windows with R < 4.2; the images are Linux with R 4.4.3 |

They ship inside the base image. Accepted, with these reasons, in
`.github/r-audit-ignore.txt`; any new advisory fails the CI audit. They go away
with an `immcantation/suite` upgrade.

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
| Python 3.12 | API, ClonalTree | Security fixes until October 2028 |
| Python 3.11 | GCtree | Security fixes until October 2027 |
| `ete3` 3.1.x | GCtree, ClonalTree | Imports the `cgi` module, removed in Python 3.13. It is what keeps both services at Python 3.12 or older |
| `passlib` 1.7.4 | API password hashing | Unmaintained; imports a module removed in Python 3.13. Works on the API's Python 3.12 |
| Fedora 41 | Dowser, BrepPhylo base image | End of life (finding 2) |
| PostgreSQL 15 | Database | Supported until November 2027 |

ClonalTree moved from Python 3.10 (end of life in October 2026) to 3.12. Python
3.11, 3.12 and 3.13 were all tried with the unchanged dependency lock: 3.11 and
3.12 install and run it; 3.13 fails on `import ete3`. 3.12 was chosen because it
is the newest release the pinned scientific stack supports. Every scientific pin
is unchanged (the lock file lost only `exceptiongroup`, a Python 3.10
backport). The old and new images produced identical output for three parameter
sets on the regression dataset: the same Newick tree, nodes, edges, clone
table, artifacts and step log, including the same behaviour on the two
parameter sets that do not yield a tree. MUSCLE produces an identical alignment
from both images.

## Image scan results

Trivy 0.75.0 run inside each image (`scripts/scan_images.py`), all severities,
2026-10-12. All eight images were scanned in under three minutes on a laptop,
including the two 13 GB R images.

| Image | Critical | High | Medium | Low | Fixable critical/high | Where the fixable ones are |
|---|---|---|---|---|---|---|
| `phylo-web` (Node 22, Debian 12) | 1 | 50 | 96 | 77 | 0 | — |
| `phylo-api` (Python 3.12, Debian 13) | 0 | 58 | 95 | 105 | 4 high | Copies bundled inside `pip` (finding 6) |
| `phylo-gctree` (Python 3.11, Debian 12) | 4 | 110 | 271 | 218 | 4 high | Copies bundled inside `pip` (finding 6) |
| `phylo-clonaltree` (Python 3.12, Debian 12) | 2 | 59 | 119 | 101 | 4 high | Copies bundled inside `pip` (finding 6) |
| `phylo-dowser` (Fedora 41) | OS not assessed | | | | 1 high | `pyarrow` from the base image (finding 2). Distribution reports 0 pending security updates |
| `phylo-brepphylo` (Fedora 41) | OS not assessed | | | | 1 high | Same as Dowser |
| `postgres:15-alpine` | 1 | 24 | 28 | 3 | 1 critical, 24 high | `gosu` helper binary (finding 8) |
| `pgsty/silo` (pinned digest, object store) | 0 | 5 | 7 | 1 | 4 high | Go standard library and `x/net` inside the `silo` binary (finding 1). The MinIO image it replaced had 9 critical / 120 high |

Changes from the earlier scan (2026-10-09):

- **ClonalTree:** 3 critical / 274 high / 2212 medium → 2 / 59 / 119. The
  compiler toolchain, git and kernel headers now stay in a build stage; the
  runtime image holds only the MUSCLE binary and the pinned Python packages
  (1.24 GB instead of 1.66 GB).
- **Web:** 3 critical and 14 high fixable findings → 0. The runtime stage
  applies Debian updates and removes `npm`, `corepack` and `yarn`, which the
  standalone server never runs.
- **Dowser, BrepPhylo:** not scannable before (the scanner could not read a
  13 GB image archive); now scanned from the inside, with the limits described
  in finding 2.

Everything in the "Critical/High" columns that is not "fixable" has no patched
package in the distribution yet. Counts move from day to day as the scanner's
database is updated.

**Re-scan of 2026-10-13 (system validation).** Run on images built from base
images that had been cached locally for some days, the scan failed its gate:
6 fixable critical findings in the API image and 7 in the GCtree image, all in
operating-system packages (OpenSSL, GnuTLS, `perl-base`) for which Debian had
published updates in the meantime. Neither Dockerfile applied pending updates,
so an image was only as current as the last pull of its base image. Both now
run `apt-get upgrade` in the build, as the web and ClonalTree images already
did. After a rebuild with `--pull` the two images are back at the figures in
the table (0 fixable critical, 4 fixable high inside `pip`). The R package
audit found the same three accepted advisories and nothing new; `npm audit`
(production) and `pip-audit` found nothing; the nine development-only npm
advisories of finding 5 are unchanged.

What this means for a deployment: security updates of the operating-system
packages reach the images only when they are rebuilt. Rebuild with fresh base
images regularly, and whenever the weekly CI scan reports a fixable critical
finding:

```bash
docker compose --profile prod build --pull
docker compose --profile prod up -d
```
