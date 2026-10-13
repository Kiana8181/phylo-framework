# phylo-framework

A one-page UI to run phylogeny/lineage tree methods behind a simple orchestrator API.

- **Web**: Next.js (apps/web)
- **API**: FastAPI (apps/api)
- **Methods**: pluggable microservices (Dowser, GCtree, BrepPhylo, ClonalTree included)
- **Contracts**: JSON schemas (packages/contracts) used by both UI & API to drive parameters, validation, and results
- **Object storage**: self-hosted **MinIO** (S3-compatible) holds uploaded datasets and generated artifacts; PostgreSQL holds ownership metadata and scientific result/tree JSON, but no base64 binaries

> **Heads-up**: Running with Docker for the first time is **time-consuming** because large R images and packages need to be downloaded and built.

> **File management (important):** Uploaded datasets and generated run artifacts
> (images, PDFs, Newick, TSV/CSV, logs, ZIP bundles) live in **MinIO**, never in the
> repository and never as base64 in the database. Downloads/previews are streamed
> through the API. See [File Management & Object Storage](#file-management--object-storage)
> and [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md). The `.env` file is **gitignored** —
> copy `.env.example` to `.env` before running.

---

## Table of Contents

- [Quick Start](#quick-start)
- [What You Get](#what-you-get)
- [Architecture](#architecture)
- [File Management & Object Storage](#file-management--object-storage)
- [Ports](#ports)
- [Prerequisites](#prerequisites)
  - [macOS](#macos) · [Linux](#linux) · [Windows](#windows)
- [Run It](#run-it)
  - [Dev — Full Docker Compose (simplest)](#dev--full-docker-compose-simplest)
  - [Dev (Docker methods)](#dev-docker-methods)
  - [Dev (Local R methods)](#dev-local-r-methods)
  - [Prod (Docker Compose)](#prod-docker-compose)
- [Manual Run (Developers)](#manual-run-developers)
- [Clean Reset (wipe local DB + storage)](#clean-reset-wipe-local-db--storage)
- [Environment Variables](#environment-variables)
- [Testing and Coverage](#testing-and-coverage)
- [Troubleshooting](#troubleshooting)
- [Extend: Add a New Method](#extend-add-a-new-method)
- [Repository Layout](#repository-layout)
- [License](#license)

---

## Quick Start

The recommended first run requires Docker Desktop (or Docker Engine with the
Compose plugin) and Git. Node, Python, R and LaTeX are needed only for the
optional host-development paths below.

1. **Clone with submodules** (required for ClonalTree base code):

```bash
git clone --recurse-submodules https://github.com/Kiana8181/phylo-framework.git
cd phylo-framework
```

Anonymous HTTPS access to the ClonalTree submodule was not available during the
latest local verification. Until the owner makes both repositories public, a
GitHub account authorized for `smhamidi/clonotype` is required. The submodule's
identity and pinned commit have deliberately not been changed.

If you already cloned without submodules:

```bash
git submodule update --init --recursive
```

2. **Create your `.env`** (it is gitignored — never committed):

```bash
cp .env.example .env
# replace the JWT and MinIO secrets
# OAuth and email settings may stay empty for local use
```

3. **Build and start the full container stack**:

```bash
docker compose --profile prod up -d --build
docker compose --profile prod exec -T api-prod python -m apps.api.scripts.storage_check
```

Migrations run when the API starts, MinIO initialization creates both buckets,
and the worker starts with the production profile. Open `http://localhost:3000`
after the services become healthy.

---

## What You Get

- **UI**: dynamic schema-driven form; upload data (CSV/TSV/RDS/RDA/FASTA for Dowser); display trees/results; lazy artifact downloads + image previews (no base64 in the browser).
- **Sequence Trace**: identifier search and root-to-match context in lineage-tree views; retain mapping artifacts when an adapter changes identifiers.
- **API** (FastAPI):
  - `GET /methods` — list methods
  - `GET /methods/{id}/spec` — method spec + UI hints
  - `POST /uploads/init` + `PUT /uploads/{id}/content` — upload a dataset to object storage
  - `POST /runs?method={id}` — create a run referencing an uploaded `file_id`
  - `GET /runs/{id}/result` — **lightweight** scientific summary only (no base64, no embedded binaries) + `dataset` descriptor + `artifact_count`
  - `GET /runs/{id}/artifacts` — list downloadable artifact descriptors
  - `GET /artifacts/{id}/download` · `GET /artifacts/{id}/preview` — stream a file / inline preview
  - `GET /datasets/{id}/download` — download the original uploaded dataset
  - `DELETE /datasets/{id}` — hard-delete the stored object, soft-delete the metadata row (idempotent; preserves run history)
- **Method services**: R/plumber (Dowser, BrepPhylo) and FastAPI (GCtree, ClonalTree) exposing `/spec` plus the asynchronous `/jobs` lifecycle. They upload output files to MinIO and return a manifest; the worker validates it and records authorized artifact references. No base64 crosses the service→API boundary.

---

## Architecture

![Architecture](./architecture.png)

- **Contracts** (packages/contracts/methods/<id>/…)
  - `spec.json`: name, version, accepted MIME types
  - `param.schema.json`: JSON-Schema parameters (drives UI)
  - `result.schema.json`: JSON-Schema results (validated by API)
  - `ui.json`: UI hints (required files, control order, etc.)
  - `service.routes.json`: maps `/spec` and asynchronous `/jobs` lifecycle endpoints

---

## File Management & Object Storage

The system of record for files is **MinIO** (self-hosted, S3-compatible, free). No
AWS or paid cloud storage is required. The abstraction stays S3-compatible, so a
real S3 endpoint can be used later by changing env vars only.

| What | Where | Notes |
| --- | --- | --- |
| Uploaded datasets | MinIO bucket `S3_BUCKET_DATASETS` | key `datasets/{user}/{upload}.{ext}` |
| Generated artifacts | MinIO bucket `S3_BUCKET_ARTIFACTS` | key `artifacts/{run}/{job}/{file}` |
| Run/file/artifact records | PostgreSQL | metadata plus scientific result/tree JSON; **no base64 binaries** |
| Staging scratch (`/runtime/storage`) | host bind / volume | where a dataset is staged for a method to read |
| Method job outputs (`/runtime/method-jobs`) | host dir / volume | method writes files; the **worker** uploads them to MinIO |

Flow: upload → object in `phylo-datasets`; the worker stages it for the method
service, the method uploads output files to `phylo-artifacts` and returns a
manifest, and the worker records `run_artifacts` rows. The browser fetches
images/downloads by streaming through the API (`/artifacts/{id}/preview|download`) —
MinIO is never exposed to the browser.

- Verify storage connectivity + buckets at any time: `npm run storage:check` (host)
  or `npm run storage:check:docker` (inside the API container).
- Full clean reset (wipe DB + MinIO + staging): `bash ./scripts/reset-local.sh`.
- Production/server guidance (volumes, backup/restore, hardening): [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md).
- Dependency and image security audit (what was scanned, what is still open, how to re-run it): [docs/SECURITY-AUDIT.md](./docs/SECURITY-AUDIT.md).
- Resource budget, container limits, network layout and secret isolation on a shared server: [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md#resource-budget-and-container-limits).
- How many jobs run at once, how threads are limited inside each method, and why a run may show "waiting for capacity": [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md#job-execution-inside-the-budget).
- How many runs a user may start per hour, what counts, and what the wizard shows when the limit is reached: [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md#limits-on-creating-runs).
- Sign-in protection: the self-hosted CAPTCHA, rate limits, the reverse-proxy setting they depend on, and email verification: [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md#sign-in-protection).
- Email: SMTP settings, which runs send a notification, retries and what a mail outage does (nothing to runs): [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md#email-and-run-notifications).
- How long results are kept (60 days by default), what expires and what does not, the upload size limit and clean-up: [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md#storage-lifecycle-and-retention).
- Starting, checking and updating a deployment, internal ports, and how results record the deployed version: [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md#starting-and-checking-a-deployment).
- Credentials that were committed in the past, what to rotate, and how the history is cleaned: [docs/HISTORY-CLEANUP.md](./docs/HISTORY-CLEANUP.md). Run `python3 scripts/scan_secrets.py` to check that no credential or env file is tracked.
- How the whole system is validated, including the tests that put the real stack under pressure (`npm run test:system`), and what the last validation found: [docs/VALIDATION.md](./docs/VALIDATION.md).
- Run time limits, what happens to a run when a method container restarts, the object store is down or a job runs out of memory, and what each error code means: [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md#when-a-run-cannot-finish).
- Replacing the unmaintained MinIO image (investigation and recommendation, not yet applied): [docs/OBJECT-STORAGE-OPTIONS.md](./docs/OBJECT-STORAGE-OPTIONS.md).

---

## Ports

|    Service | URL                   | Port |
| ---------: | --------------------- | ---: |
|        Web | http://localhost:3000 | 3000 |
|        API | http://localhost:8000 | 8000 |
|     Dowser | http://localhost:8001 | 8001 |
|     GCtree | http://localhost:8002 | 8002 |
|  BrepPhylo | http://localhost:8003 | 8003 |
| ClonalTree | http://localhost:8004 | 8004 |
|  MinIO API | http://localhost:9000 | 9000 |
| MinIO Console | http://localhost:9001 | 9001 |

> Ensure these ports are **free** before running. The helper scripts will check and exit with a clear error if not. MinIO ports are configurable via `MINIO_API_PORT` / `MINIO_CONSOLE_PORT`.

---

## Prerequisites

You do **not** need everything for every mode; the helper will tell you what’s missing.

### macOS host-development extras

- **Node.js 22** (matches CI; the earlier local report used Node 24)
- **Python 3.10+** (3.12 OK)
- **Docker Desktop** (for Docker modes)
- **R 4.3+** (only for Local-R dev)
  - Helpful libs: `brew install pkg-config cairo pango harfbuzz fribidi libgit2 v8`

### Linux host-development extras

- **Node.js 22**, **Python 3.10+**
- **Docker Engine + compose plugin** (for Docker modes)
- **R 4.3+** (only for Local-R dev) + system libs:
  ```bash
  sudo apt-get update && sudo apt-get install -y     libcurl4-openssl-dev libssl-dev libxml2-dev libgit2-dev     libfontconfig1-dev libfreetype6-dev libharfbuzz-dev libfribidi-dev     libpng-dev libtiff5-dev libjpeg-dev libcairo2-dev libxt-dev     zlib1g-dev libbz2-dev liblzma-dev libsodium-dev pkg-config libicu-dev     libv8-dev make g++
  ```

### Windows

- **Docker path**: use Docker Desktop from PowerShell or a WSL2 shell; the Compose commands above work in either environment.
- **Shell helper/development scripts**: use WSL2. They are Bash scripts, not PowerShell scripts.
- **Dev (Local R)**: Recommended to use **WSL2 (Ubuntu)** and follow Linux steps. Native Windows R is possible but requires proper Rtools/toolchain setup.

---

## Run It

> Every mode below starts MinIO and auto-creates the `phylo-datasets` and
> `phylo-artifacts` buckets. After startup you can sanity-check storage with
> `npm run storage:check` (host) / `npm run storage:check:docker` (containers).

### Dev — Full Docker Compose (simplest)

Everything runs in containers, including the run worker. Method services upload
generated artifacts directly to MinIO and the worker records their manifest.
This is the closest local path to the production profile.

```bash
cp .env.example .env          # first time only
docker compose --profile dev up -d --build
# - postgres migrations run automatically (api runs `alembic upgrade head` on start)
# - minio-init creates both buckets
docker compose --profile dev exec -T api python -m apps.api.scripts.storage_check
```

- Web → http://localhost:3000 · API → http://localhost:8000 · MinIO console → http://localhost:9001

Tail logs / stop:

```bash
docker compose --profile dev logs -f api api-worker
docker compose --profile dev down        # add -v to also wipe volumes (DB + MinIO)
```

> Use this when you don't need hot-reload of the API/worker. For fast Python
> iteration on the API/worker, use the `./run.sh` hybrid modes below (host
> API/worker + Docker or local methods).

---

### Dev (Docker methods)

Host **API + worker** with hot-reload; method services run in **Docker**.
MinIO + Postgres start via Compose automatically; method containers and the host
worker share `runtime/method-jobs` so artifacts can be ingested.

```bash
./run.sh
# choose: Dev → Docker
```

> First time can be **slow** due to large R images and compiled dependencies.

Open http://localhost:3000

---

### Dev (Local R methods)

Requires **R 4.3+** with packages:

- CRAN: `plumber`, `dowser`, `alakazam`, `shazam`, `ggtree`, `ape`, `jsonlite`, `jsonvalidate`, `sodium`
- Bioc: `S4Vectors`, `IRanges`, `XVector`, `Biostrings`, `GenomeInfoDb`, `GenomicRanges`, `Rhtslib`, `Rsamtools`, `GenomicAlignments`, `treeio`, `ggtree`

Run:

```bash
./run.sh
# choose: Dev → Local R
```

The script starts **plumber** on **:8001**, **API** on **:8000**, and **Web** on **:3000**.

---

### Prod (Docker Compose)

Everything in containers with internal networking (includes Postgres, MinIO,
API, worker, web, and all method services).

```bash
./run.sh prod      # pre-start check, then the command below
# or directly:
docker compose --profile prod up -d --build
./run.sh status    # containers, migrations, buckets, method services
```

Production needs Docker with Compose 2.17+ on the host and nothing else (no
Node, no Python). `./run.sh` without arguments still offers the interactive
menu.

- Web → http://localhost:3000
- API → http://localhost:8000

> First run can take a **long time** for images to download/build. For server
> deployment (persistent volumes, **not** exposing MinIO publicly, backup/restore,
> credential hardening, post-deploy checks) follow **[docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md)**.

---

## Central control for method services

Ports and service endpoints come from one config file and sync into one root env file.

- **Config source:** `config/method-services.json`
- **Runtime env source:** `.env` (repo root)

| Command                                   | Description                                                                       |
| ----------------------------------------- | --------------------------------------------------------------------------------- |
| `npm run services:sync-env`               | Generate/update `METHOD_*` vars in root `.env` from `config/method-services.json` |
| `npm run services:list`                   | List service IDs, host/container ports, and local/docker URLs                     |
| `npm run services:start`                  | Build + start all method services in Docker                                       |
| `npm run services:start -- gctree dowser` | Build + start only selected method services                                       |
| `npm run services:stop`                   | Stop all managed method containers                                                |
| `npm run services:stop -- gctree`         | Stop one managed method container                                                 |

Generated keys include both local and compose-network URLs:

- `METHOD_<ID>_URL` (example: `http://localhost:8002`)
- `METHOD_<ID>_URL_DOCKER` (example: `http://gctree:8002`)
- `METHOD_<ID>_HOST_PORT`
- `METHOD_<ID>_CONTAINER_PORT`

---

## Manual Run (Developers)

If you want to run without `./run.sh`, use this flow.

### 1) Create + sync the single env file

From repo root:

```bash
cp .env.example .env          # .env is gitignored; never commit it
npm run services:sync-env     # generates METHOD_* vars into .env
```

Then edit only root `.env` for project configuration (API, web, DB, **object
storage / MinIO**, method URLs, auth/email keys, etc.). The storage defaults
(`STORAGE_BACKEND=minio`, `S3_*`, `MINIO_ROOT_*`, bucket names) already work for
local development — change the credentials/buckets for anything shared.

### 2) Install dependencies

```bash
# Node deps (monorepo/workspaces)
npm ci

# Python venv for API + migrations
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r apps/api/requirements.txt

# Optional contracts build
npm -w @phylo/contracts run build
```

### 3) Start PostgreSQL + MinIO, run migrations, verify storage

```bash
set -a; source .env; set +a
source .venv/bin/activate

# Database + object storage (minio-init creates both buckets, then exits)
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev up -d postgres minio minio-init
docker wait phylo-minio-init 2>/dev/null || true   # block until buckets are ready (no-op if already done)

npm run db:migrate             # applies migrations incl. 008 (run_artifacts, dataset soft-delete)
npm run storage:check          # round-trips both buckets via the host (localhost:9000) — the real readiness gate
```

> If `set -a; source .env` errors on values containing `<` or spaces (e.g.
> `SMTP_FROM`), run the storage check via the Node wrapper instead, which parses
> `.env` safely: `node --env-file=.env ./scripts/storage-check.mjs`.

> **Method services upload artifacts directly to MinIO** using a scoped
> PutObject-only user (`MINIO_METHODS_USER`/`MINIO_METHODS_PASSWORD`, created
> by the `minio-init` container with a policy restricted to
> `s3:PutObject` on the artifact bucket). The worker never reads files from
> disk and there is no shared volume between methods and the worker —
> `METHOD_JOBS_DIR` is purely internal to each method container (for
> `status.json` / `request.json` / `job.log`). `job.log` is auto-uploaded to
> MinIO at the end of every job alongside the scientific artifacts.

### 4) Start method services (pick one approach)

Before starting services, ensure submodules are initialized:

```bash
git submodule update --init --recursive
```

#### A) Docker methods (uses `method-services.mjs` + config)

```bash
npm run services:start
```

#### B) Local methods

Use ports from root `.env` (`METHOD_*_HOST_PORT`).
In each terminal where you run a local method, run this bootstrap first:

```bash
# from repo root
set -a; source .env; set +a
export CONTRACTS_DIR="$(python3 -c 'import os; p=os.environ.get("CONTRACTS_DIR","packages/contracts"); print(p if os.path.isabs(p) else os.path.realpath(p))')"
export STORAGE_ABS="$(python3 -c 'import os; p=os.environ.get("STORAGE_LOCAL_PATH","runtime/storage"); print(p if os.path.isabs(p) else os.path.realpath(p))')"
mkdir -p "$STORAGE_ABS"
export STRICT_CONTRACT_ROUTES="${STRICT_CONTRACT_ROUTES:-true}"
export METHOD_SERVICE_FILE_PREFIX="$STORAGE_ABS"
export HOST_RUNTIME_SHARED_ROOT="$STORAGE_ABS"
# Method services upload artifact files directly to MinIO using a scoped user
# created by minio-init. No shared METHOD_JOBS_DIR with the worker is needed —
# methods only use it for internal state (status.json/request.json/job.log).
export METHOD_JOBS_DIR="$PWD/runtime/method-jobs"
mkdir -p "$METHOD_JOBS_DIR"
export IGPHYML_BIN="${IGPHYML_BIN:-/usr/local/share/igphyml/src/igphyml}"
export IGPHYML_MOTIFS="${IGPHYML_MOTIFS:-/usr/local/share/igphyml/src/motifs}"
export IGPHYML_PATH="${IGPHYML_PATH:-$IGPHYML_MOTIFS}"
```

Run each local service in its own terminal (you can run only one if you want):

**Dowser (local R)**

```bash
set -a; source .env; set +a
export CONTRACTS_DIR="$(python3 -c 'import os; p=os.environ.get("CONTRACTS_DIR","packages/contracts"); print(p if os.path.isabs(p) else os.path.realpath(p))')"
export STRICT_CONTRACT_ROUTES="${STRICT_CONTRACT_ROUTES:-true}"
export DNAPARS_PATH="${DNAPARS_PATH:-$(command -v dnapars || echo /usr/local/bin/dnapars)}"
export DNAML_PATH="${DNAML_PATH:-$(command -v dnaml || echo /usr/local/bin/dnaml)}"
export RAXML_BIN="${RAXML_BIN:-$(command -v raxml-ng || echo /usr/local/bin/raxml-ng)}"
export IGPHYML_BIN="${IGPHYML_BIN:-/usr/local/share/igphyml/src/igphyml}"
export IGPHYML_MOTIFS="${IGPHYML_MOTIFS:-/usr/local/share/igphyml/src/motifs}"
export IGPHYML_PATH="${IGPHYML_PATH:-$IGPHYML_MOTIFS}"
Rscript --vanilla -e "setwd('services/dowser'); Sys.setenv(CONTRACTS_DIR='${CONTRACTS_DIR}', STRICT_CONTRACT_ROUTES='${STRICT_CONTRACT_ROUTES}', DNAPARS_PATH='${DNAPARS_PATH}', DNAML_PATH='${DNAML_PATH}', RAXML_BIN='${RAXML_BIN}', IGPHYML_BIN='${IGPHYML_BIN}', IGPHYML_MOTIFS='${IGPHYML_MOTIFS}', IGPHYML_PATH='${IGPHYML_PATH}'); pr <- plumber::plumb('plumber.R'); pr\$run(host='0.0.0.0', port=${METHOD_DOWSER_HOST_PORT})"
```

Dowser requires aligned AIRR/Change-O input (not raw FASTA). Supported build methods: `pratchet`, `pml`, `dnapars`, `dnaml`, `igphyml`, `raxml`. For `dnapars`/`dnaml` install PHYLIP; for `raxml` install [RAxML-NG](https://github.com/amkozlov/raxml-ng); for `igphyml` set `IGPHYML_BIN` and motif paths. Run validator tests: `Rscript services/dowser/tests/run_validators.R`.

**GCtree (local Python)**

CSV/TSV is a framework adapter, not a native GCtree input. The adapter writes
the selected `sequence_id` and `sequence_alignment` fields, requires unique IDs
and equal aligned lengths, and emits exactly one FASTA record per valid row.
`duplicate_count` and other table metadata are not sent as record weights. If
three records are intended, supply three identical aligned sequences with
distinct IDs such as `cellA_copy1` through `cellA_copy3` and retain the mapping.
The designated reference row is not itself counted as an observation; other
records matching its sequence can contribute to the collapsed root genotype.

```bash
set -a; source .env; set +a
export CONTRACTS_DIR="$(python3 -c 'import os; p=os.environ.get("CONTRACTS_DIR","packages/contracts"); print(p if os.path.isabs(p) else os.path.realpath(p))')"
export STRICT_CONTRACT_ROUTES="${STRICT_CONTRACT_ROUTES:-true}"
source .venv/bin/activate
pip install -r services/gctree/requirements.txt
(
  cd services/gctree
  export QT_QPA_PLATFORM="offscreen"
  export MPLBACKEND="agg"
  export PYTHONPATH="$(pwd)${PYTHONPATH:+:$PYTHONPATH}"
  uvicorn app:app --host 0.0.0.0 --port "${METHOD_GCTREE_HOST_PORT}"
)
```

Notice: `gctree`, `deduplicate`, and `mkconfig` CLIs must be on `PATH` (installed by `pip install -r services/gctree/requirements.txt`).

**BrepPhylo (local R)**

```bash
set -a; source .env; set +a
export CONTRACTS_DIR="$(python3 -c 'import os; p=os.environ.get("CONTRACTS_DIR","packages/contracts"); print(p if os.path.isabs(p) else os.path.realpath(p))')"
export STRICT_CONTRACT_ROUTES="${STRICT_CONTRACT_ROUTES:-true}"
export IGPHYML_BIN="${IGPHYML_BIN:-/usr/local/share/igphyml/src/igphyml}"
export IGPHYML_MOTIFS="${IGPHYML_MOTIFS:-/usr/local/share/igphyml/src/motifs}"
export IGPHYML_PATH="${IGPHYML_PATH:-$IGPHYML_MOTIFS}"
Rscript --vanilla -e "setwd('services/brepphylo'); Sys.setenv(CONTRACTS_DIR='${CONTRACTS_DIR}', STRICT_CONTRACT_ROUTES='${STRICT_CONTRACT_ROUTES}', IGPHYML_BIN='${IGPHYML_BIN}', IGPHYML_MOTIFS='${IGPHYML_MOTIFS}', IGPHYML_PATH='${IGPHYML_PATH}'); pr <- plumber::plumb('plumber.R'); pr\$run(host='0.0.0.0', port=${METHOD_BREPPHYLO_HOST_PORT})"
```

Notice: default `tree_type=dnapars` expects `dnapars` on `PATH` (or `DNAPARS_PATH`). If using `tree_type=igphyml`, set `IGPHYML_BIN` and motifs (`IGPHYML_MOTIFS` or `IGPHYML_PATH`).

**BrepPhylo parameters (contract/UI)**

- `tree_type` is labeled **Tree inference method** (`simple`, `dnapars`, `igphyml`).
- `input_sequence_mode`: `raw_sequence` (MSA via `algorithm`) or `aligned_imgt_gapped` (sequences must contain IMGT gap `.` characters; no alignment algorithm).
- `species` enum includes built-in references plus `custom` (paste IMGT germline V-gene FASTA into `germline_set_text`).
- `enable_csr_analysis` + `isotype_column` gate CSR / arborescence post-processing.
- Removed from UI/backend: `class_column`, color controls, `use_temp_dir`, sequence preprocessing (`apply_filters`, `uppercase`, `gap_policy`, `noniupac_policy`), resume, and server-side `germline_set` paths.

**Alignment PDF / LaTeX (`make_alignment_pdf=true`)**

- The supported path is the `brepphylo` Docker image, which contains the needed
  TeX packages. The full-Docker setup requires no LaTeX installation on the host.
- If LaTeX is missing, tree inference still runs; the service reports `diagnostics.latex_available=false` and a warning (alignment PDF may fail without blocking trees).

**BrepPhylo validator tests (local)**

```bash
Rscript services/brepphylo/tests/run_validators.R
npm run test:all  # includes real BrepPhylo scientific execution
```


```bash
set -a; source .env; set +a
export CONTRACTS_DIR="$(python3 -c 'import os; p=os.environ.get("CONTRACTS_DIR","packages/contracts"); print(p if os.path.isabs(p) else os.path.realpath(p))')"
export STRICT_CONTRACT_ROUTES="${STRICT_CONTRACT_ROUTES:-true}"
source .venv/bin/activate
pip install -r services/clonaltree/requirements.txt
(
  cd services/clonaltree
  export QT_QPA_PLATFORM="offscreen"
  export MPLBACKEND="agg"
  uvicorn app:app --host 0.0.0.0 --port "${METHOD_CLONALTREE_HOST_PORT}"
)
```

Notice: ClonalTree requires **MUSCLE v5.x**.  
If you start via `./run.sh` -> `Dev -> Local R` (or `scripts/dev-with-local-r.sh`), MUSCLE v5 is auto-installed/checked.  
If you start ClonalTree manually, ensure `muscle -version` reports major version `>= 5`; otherwise `/run` fails with a version error.

### 5) Start API

```bash
set -a; source .env; set +a
source .venv/bin/activate

# Local methods: API must send host paths
export STORAGE_ABS="$(python3 -c 'import os; p=os.environ.get("STORAGE_LOCAL_PATH","runtime/storage"); print(p if os.path.isabs(p) else os.path.realpath(p))')"
mkdir -p "$STORAGE_ABS"
export METHOD_SERVICE_FILE_PREFIX="$STORAGE_ABS"
export HOST_RUNTIME_SHARED_ROOT="$STORAGE_ABS"

# Docker methods: API sends container path but still stages files on host
# export METHOD_SERVICE_FILE_PREFIX="/runtime/storage"
# export HOST_RUNTIME_SHARED_ROOT="$STORAGE_ABS"

npm run dev:api
```

### 5b) Start run worker

Processes `QUEUED` runs and **ingests method outputs into MinIO** (uploads
artifacts, records `run_artifacts` rows). Run in a **separate terminal** from API
and web. Requires postgres, MinIO, and method services to be up. Uses the same
root `.env` as `dev:api` (DB URL, `S3_*`, `METHOD_*_URL`, storage paths).

```bash
npm run dev:worker
```

> The worker no longer reads files from disk — method services upload artifact
> files (PNGs, ZIPs, `job.log`, etc.) directly to MinIO using their scoped
> `MINIO_METHODS_*` credentials. The worker only registers DB rows from the
> manifest each method emits in `result.json`. If artifacts never appear after
> a run completes, check that the `minio-init` container created the
> `phylo-methods` user, and that the method service env carries
> `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` pointing at it.

### 6) Start web UI

```bash
set -a; source .env; set +a
npm run dev:web
```

Open `http://localhost:3000`.

---

## Clean Reset (wipe local DB + storage)

Project-scoped and safe — it only removes **this** project's containers + named
volumes (`postgres_data`, `method_jobs`, `minio_data`) and the local
`./runtime` staging folders. It never runs `docker volume prune` and never
touches unrelated files.

```bash
bash ./scripts/reset-local.sh
```

It stops the stack, drops the project volumes, deletes `./runtime/storage` and
`./runtime/method-jobs`, rebuilds + starts the clean dev stack (buckets are
recreated automatically), and runs the storage check.

Manual equivalent:

```bash
docker compose down -v --remove-orphans
rm -rf ./runtime/storage ./runtime/method-jobs
docker compose --profile dev up -d --build
```

---

## Environment Variables

All runtime configuration should live in root `.env` (copied from
`.env.example`). `.env` is **gitignored** — keep secrets out of version control.

- `CONTRACTS_DIR` — contracts path used by API/methods
- `CORS_ORIGINS` — allowed web origins for API CORS
- `NEXT_PUBLIC_API_BASE_URL` — web -> API base URL
- `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_HOST` / `POSTGRES_PORT` — DB connection pieces
- `DATABASE_URL` — optional explicit DB URL override
**Object storage (MinIO / S3-compatible):**

- `STORAGE_BACKEND` — `minio` (default), `s3`, or `local` (tests only)
- `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` — MinIO root creds (also used as the S3 key/secret by default)
- `S3_ENDPOINT_URL` — S3 endpoint for **host-run** processes/scripts (e.g. `http://localhost:9000`)
- `S3_ENDPOINT_URL_DOCKER` — S3 endpoint **inside** containers (e.g. `http://minio:9000`); Compose injects this as the in-container `S3_ENDPOINT_URL`
- `S3_REGION` — region label (any value for MinIO)
- `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` — S3 credentials (keep in sync with the MinIO root creds, or use a scoped MinIO user)
- `S3_BUCKET_DATASETS` / `S3_BUCKET_ARTIFACTS` — bucket names
- `S3_FORCE_PATH_STYLE` — `true` for MinIO (path-style addressing)
- `MINIO_API_PORT` / `MINIO_CONSOLE_PORT` — host ports for the MinIO container

**Staging / method I/O:**

- `STORAGE_LOCAL_PATH` — host-side **staging** directory (scratch; not the dataset/artifact store)
- `STORAGE_LOCAL_URL` — URL prefix for the local test backend
- `HOST_RUNTIME_SHARED_ROOT` — host absolute staging root the API uses to stage/map method inputs
- `METHOD_SERVICE_FILE_PREFIX` — prefix API rewrites file paths to when calling method services (`/runtime/storage` for Docker methods, host absolute path for local methods)
- `METHOD_JOBS_DIR` — internal per-method-container directory for `status.json` / `request.json` / `job.log`. **Do not set in `.env`** — this is purely internal to each method container. Defaults to `/runtime/method-jobs` inside the container. The worker does NOT read it; artifact files are uploaded directly to MinIO by each method.
- `MINIO_METHODS_USER` / `MINIO_METHODS_PASSWORD` — scoped MinIO credentials (created by `minio-init`) used by method services to upload artifact files directly to the artifact bucket. Restricted to `s3:PutObject` only.
- `METHOD_<ID>_URL` — host URL for each method service
- `METHOD_<ID>_URL_DOCKER` — compose-network URL for each method service
- `METHOD_<ID>_HOST_PORT` / `METHOD_<ID>_CONTAINER_PORT` — generated service ports
- `IGPHYML_BIN` / `IGPHYML_MOTIFS` / `IGPHYML_PATH` / `DNAPARS_PATH` — optional method runtime overrides

`apps/api/.env` and `apps/web/.env` are now legacy compatibility files and should stay empty.

---

## Testing and Coverage

The test suite covers the shared contracts, frontend unit/component behavior,
FastAPI routes, real PostgreSQL migrations and queue concurrency, local/S3/MinIO
storage, worker transitions, and all four Python/R scientific services. Chromium
also exercises signup/login, file deletion and each method's documented example
through form submission to rendered tree results.

```bash
# Once, after npm ci and creating .venv:
.venv/bin/python -m pip install -r requirements-test.txt
npx playwright install chromium

npm test                         # Unit + DB/storage integration + coverage
npm run test:all -- --build       # First complete run, builds scientific images
npm run test:all                  # Complete run reusing existing image dependencies
```

Docker Desktop must be running. Tests use the independent `phylo-tests` Compose
project, disposable databases/buckets and loopback ports 55432, 59000, 58000–58004
and 53000. They do not use the application's `.env`, database or MinIO volumes.
The runner cleans up its test containers/volumes on completion or failure.
No local R installation is needed.

Reports are generated under `coverage/`: contracts and frontend HTML/LCOV;
Python HTML/XML with branch coverage from unit tests and real subprocesses;
separate R covr reports; scientific result/checksum evidence; Playwright reports
and failure traces. Missing infrastructure and coverage regressions fail the
run. Executable shared contracts have a 100% coverage gate; other layers enforce
measured baselines and report uncovered code explicitly.

The verified complete run passed **287 Python tests**, **121 contract tests**,
**156 frontend tests**, **8 scientific E2E scenarios**, **6 browser scenarios**,
and both R suites. Measured line coverage from that run:

| Layer | Line coverage |
|---|---:|
| Executable shared contracts | 100% |
| API (unit/integration + real E2E processes) | 75.75% |
| GCtree service wrapper | 62.99% |
| ClonalTree service wrapper | 79.02% |
| Frontend (unit + Chromium) | 42.98% |
| Dowser R modules | 44.24% |
| BrepPhylo R modules | 61.67% |

R percentages exclude executable entrypoints; Python service percentages exclude
upstream scientific packages/submodule code. Full scope and exclusions are in
[TESTING.md](docs/TESTING.md). These are recorded results, not a claim of complete
branch coverage; regenerated reports are authoritative after changes.

[GitHub Actions](.github/workflows/tests.yml) runs both test stages on pushes,
pull requests, manual dispatch and a weekly schedule, retaining reports for
30 days. [Testing documentation](docs/TESTING.md) details every layer, commands,
coverage exclusions, corrected defects and remaining scientific/browser scope.
Coverage is not a claim that every biological configuration or upstream algorithm
has been validated.

---

## Troubleshooting

- **Ports busy** → stop other processes, or change ports in `.env` and compose files (MinIO: `MINIO_API_PORT` / `MINIO_CONSOLE_PORT`).
- **Dowser schema errors in Local R** → ensure you started R in `services/dowser` (or set `CONTRACTS_DIR` correctly); Docker option mounts contracts automatically.
- **`@phylo/contracts` not found** → run `npm ci` at repo root; ensure `apps/web/package.json` depends on `"@phylo/contracts"`.
- **Docker is slow** → first run downloads large R images; subsequent runs are faster.
- **CORS** → make sure `CORS_ORIGINS` in API includes your web origin.
- **API/worker fails at startup with a MinIO connection error** → MinIO isn't up or the endpoint is wrong. Start it (`docker compose --profile dev up -d minio minio-init`) and confirm `S3_ENDPOINT_URL` is `http://localhost:9000` for host processes. Verify with `npm run storage:check`.
- **Run completes but no artifacts / downloads appear** → method service couldn't upload to MinIO. Check that the `minio-init` container completed cleanly (`docker compose logs minio-init` — expect `methods user ready`), and that the method service env carries the scoped `MINIO_METHODS_*` creds plus a working `S3_ENDPOINT_URL`. In host-run dev mode the method container reaches MinIO via `host.docker.internal:9000` (the `--add-host=host.docker.internal:host-gateway` flag in `method-services.mjs` makes this work on Linux).
- **Buckets missing** → re-run `docker compose --profile dev up -d minio minio-init` and check `docker compose logs minio-init`.
- **`source .env` parse error** (values with `<` / spaces) → use the Node wrappers (`node --env-file=.env ...`) which the npm scripts already do.

---

## Extend: Add a New Method

1. Create `packages/contracts/methods/<id>/` with:
   - `spec.json`, `param.schema.json`, `result.schema.json`, `ui.json`, `service.routes.json`
2. Provide a service exposing `/spec` and the asynchronous `/jobs` lifecycle (containerized or remote).
3. Point the API to it via env: `METHOD_<METHODID_UPPER>_URL=http://host:port`.
4. The UI auto-renders the new parameters and accepts formats from `spec.json`.

---

## Repository Layout

```
apps/
  api/        # FastAPI orchestrator + DB-backed run worker + storage abstraction
  web/        # Next.js app
packages/
  contracts/  # Shared contracts (schemas, UI hints, TS types/routes)
services/
  dowser/     # R/plumber service (Dowser)      + artifact_manifest.R
  brepphylo/  # R/plumber service (BrepPhylo)    + artifact_manifest.R
  gctree/     # FastAPI service (GCtree)         + artifact_manifest.py
  clonaltree/ # FastAPI service (ClonalTree)     + artifact_manifest.py
docs/
  DEPLOYMENT.md          # MinIO/server deployment, volumes, backup/restore
  SECURITY-AUDIT.md      # Dependency/image audit results, open findings, re-run commands
  OBJECT-STORAGE-OPTIONS.md  # MinIO replacement: tested options and recommendation
# helper scripts:
#   run.sh
#   scripts/dev-with-docker.sh
#   scripts/dev-with-local-r.sh
#   scripts/select-mode.mjs
#   scripts/reset-local.sh     # clean-slate reset (DB + MinIO + staging)
#   scripts/storage-check.mjs  # storage connectivity / bucket check
```

---

## License

Phylo-Framework is released under the **MIT License** — see [LICENSE](LICENSE).

The datasets and run outputs archived alongside the paper are released
separately under **CC-BY-4.0**, and are deposited on Zenodo at
[10.5281/zenodo.22233538](https://doi.org/10.5281/zenodo.22233538).

### Third-party components

The framework orchestrates four independently developed reconstruction tools,
which are **not** covered by this licence. Each runs inside its own container
image and retains the licence of its upstream project:

| Component | Upstream project |
|---|---|
| GCtree | [matsengrp/gctree](https://github.com/matsengrp/gctree) |
| ClonalTree | [smhamidi/clonotype](https://github.com/smhamidi/clonotype) (pinned git submodule; publication/access remains an owner action) |
| Dowser | [Immcantation](https://immcantation.readthedocs.io/) suite |
| BrepPhylo | [Fraternalilab/BrepPhylo](https://github.com/Fraternalilab/BrepPhylo) |
| PHYLIP (`dnapars`) | [PHYLIP 3.697](https://phylipweb.github.io/phylip/) |
| MUSCLE | [rcedgar/muscle](https://github.com/rcedgar/muscle) |

Consult each project's own licence before redistributing its image.
