# phylo-framework

A one-page UI to run phylogeny/lineage tree methods behind a simple orchestrator API.

- **Web**: Next.js (apps/web)
- **API**: FastAPI (apps/api)
- **Methods**: pluggable microservices (Dowser, GCtree, BrepPhylo included)
- **Contracts**: JSON schemas (packages/contracts) used by both UI & API to drive parameters, validation, and results

> **Heads-up**: Running with Docker for the first time is **time-consuming** because large R images and packages need to be downloaded and built.

---

## Table of Contents

- [Quick Start](#quick-start)
- [What You Get](#what-you-get)
- [Architecture](#architecture)
- [Ports](#ports)
- [Prerequisites](#prerequisites)
  - [macOS](#macos) · [Linux](#linux) · [Windows](#windows)
- [Run It](#run-it)
  - [Dev (Docker methods)](#dev-docker-methods)
  - [Dev (Local R methods)](#dev-local-r-methods)
  - [Prod (Docker Compose)](#prod-docker-compose)
- [Manual Run (Developers)](#manual-run-developers)
- [Environment Variables](#environment-variables)
- [Troubleshooting](#troubleshooting)
- [Extend: Add a New Method](#extend-add-a-new-method)
- [Repository Layout](#repository-layout)
- [License](#license)

---

## Quick Start

1. **Clone with submodules** (required for ClonalTree base code):

```bash
git clone --recurse-submodules <repo-url>
cd phylo-framework
```

If you already cloned without submodules:

```bash
git submodule update --init --recursive
```

2. **Install Node & workspace deps (root)** and **API Python deps**:

```bash
# Node deps (root — installs workspaces too)
npm i

# Python deps for the API
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r apps/api/requirements.txt
```

3. **Make helper scripts executable** (they are expected at the repo root):

```bash
chmod +x ./run.sh ./scripts/dev-with-docker.sh ./scripts/dev-with-local-r.sh
```

4. **Run the interactive menu** (uses Inquirer under the hood):

```bash
./run.sh
```

Pick:

- **Dev → Docker** (no local R needed; slower first run)
- **Dev → Local R** (fast if you already have R 4.3+ with packages)
- **Prod → docker compose** (recommended for deployments)

> The scripts perform port checks and dependency checks and print **meaningful errors** if something is missing or a port is busy.

---

## What You Get

- **UI**: dynamic schema-driven form; upload data (CSV/TSV/RDS/RDA/FASTA for Dowser); display trees/results.
- **API** (FastAPI):
  - `GET /methods` — list methods
  - `GET /methods/{id}/spec` — method spec + UI hints
  - `POST /runs?method={id}` — upload file(s) + params; **errors if required files are missing**
  - `GET /runs/{id}/result` — results envelope (e.g., Newick, images, tables)
- **Method service (Dowser)**: R/plumber HTTP exposing `/spec` and `/run`.

---

## Architecture

![Architecture](./architecture.png)

- **Contracts** (packages/contracts/methods/<id>/…)
  - `spec.json`: name, version, accepted MIME types
  - `param.schema.json`: JSON-Schema parameters (drives UI)
  - `result.schema.json`: JSON-Schema results (validated by API)
  - `ui.json`: UI hints (required files, control order, etc.)
  - `service.routes.json`: maps method endpoints (`/spec`, `/run`)

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

> Ensure these ports are **free** before running. The helper scripts will check and exit with a clear error if not.

---

## Prerequisites

You do **not** need everything for every mode; the helper will tell you what’s missing.

### macOS

- **Node.js 20+** (`brew install node@20`)
- **Python 3.10+** (3.12 OK)
- **Docker Desktop** (for Docker modes)
- **R 4.3+** (only for Local-R dev)
  - Helpful libs: `brew install pkg-config cairo pango harfbuzz fribidi libgit2 v8`

### Linux (Ubuntu/Debian)

- **Node.js 20+**, **Python 3.10+**
- **Docker Engine + compose plugin** (for Docker modes)
- **R 4.3+** (only for Local-R dev) + system libs:
  ```bash
  sudo apt-get update && sudo apt-get install -y     libcurl4-openssl-dev libssl-dev libxml2-dev libgit2-dev     libfontconfig1-dev libfreetype6-dev libharfbuzz-dev libfribidi-dev     libpng-dev libtiff5-dev libjpeg-dev libcairo2-dev libxt-dev     zlib1g-dev libbz2-dev liblzma-dev libsodium-dev pkg-config libicu-dev     libv8-dev make g++
  ```

### Windows

- **Prod/Dev (Docker)**: Install **Docker Desktop**; run `./run.sh` using **Git Bash** or **PowerShell**.
- **Dev (Local R)**: Recommended to use **WSL2 (Ubuntu)** and follow Linux steps. Native Windows R is possible but requires proper Rtools/toolchain setup.

---

## Run It

### Dev (Docker methods)

No local R needed. Starts **Dowser** in a container on **:8001**, the **API** on **:8000**, and the **Web** dev server on **:3000**.

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

Everything in containers with internal networking.

```bash
./run.sh
# choose: Prod → docker compose
```

- Web → http://localhost:3000
- API → http://localhost:8000

> First run can take a **long time** for images to download/build.

---

## Central control for method services

Ports and service endpoints come from one config file and sync into one root env file.

- **Config source:** `config/method-services.json`
- **Runtime env source:** `.env` (repo root)

| Command | Description |
|--------|-------------|
| `npm run services:sync-env` | Generate/update `METHOD_*` vars in root `.env` from `config/method-services.json` |
| `npm run services:list` | List service IDs, host/container ports, and local/docker URLs |
| `npm run services:start` | Build + start all method services in Docker |
| `npm run services:start -- gctree dowser` | Build + start only selected method services |
| `npm run services:stop` | Stop all managed method containers |
| `npm run services:stop -- gctree` | Stop one managed method container |

Generated keys include both local and compose-network URLs:

- `METHOD_<ID>_URL` (example: `http://localhost:8002`)
- `METHOD_<ID>_URL_DOCKER` (example: `http://gctree:8002`)
- `METHOD_<ID>_HOST_PORT`
- `METHOD_<ID>_CONTAINER_PORT`

---

## Manual Run (Developers)

If you want to run without `./run.sh`, use this flow.

### 1) Sync + edit the single env file

From repo root:

```bash
npm run services:sync-env
```

Then edit only root `.env` for project configuration (API, web, DB, storage, method URLs, auth/email keys, etc.).

### 2) Install dependencies

```bash
# Node deps (monorepo/workspaces)
npm i

# Python venv for API + migrations
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r apps/api/requirements.txt

# Optional contracts build
npm -w @phylo/contracts run build
```

### 3) Start PostgreSQL and run migrations

```bash
docker compose --profile dev up -d postgres
source .venv/bin/activate
npm run db:migrate
```

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

Use ports from root `.env` (`METHOD_*_HOST_PORT`) and make sure API sends a host-readable prefix:

```bash
# from repo root
set -a; source .env; set +a
export CONTRACTS_DIR="$(pwd)/${CONTRACTS_DIR:-packages/contracts}"
export METHOD_SERVICE_FILE_PREFIX="$(pwd)/${STORAGE_LOCAL_PATH:-runtime/storage}"
mkdir -p "$METHOD_SERVICE_FILE_PREFIX"
```

Run each local service in its own terminal (you can run only one if you want):

**Dowser (local R)**

```bash
set -a; source .env; set +a
export CONTRACTS_DIR="$(pwd)/${CONTRACTS_DIR:-packages/contracts}"
export STRICT_CONTRACT_ROUTES="${STRICT_CONTRACT_ROUTES:-true}"
Rscript --vanilla -e "setwd('services/dowser'); pr <- plumber::plumb('plumber.R'); pr\$run(host='0.0.0.0', port=${METHOD_DOWSER_HOST_PORT})"
```

Notice: if you use `tree_model=igphyml`, configure `IGPHYML_BIN` and motif path vars (`IGPHYML_MOTIFS` or `IGPHYML_PATH`).

**GCtree (local Python)**

```bash
set -a; source .env; set +a
export CONTRACTS_DIR="$(pwd)/${CONTRACTS_DIR:-packages/contracts}"
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
export CONTRACTS_DIR="$(pwd)/${CONTRACTS_DIR:-packages/contracts}"
export STRICT_CONTRACT_ROUTES="${STRICT_CONTRACT_ROUTES:-true}"
Rscript --vanilla -e "setwd('services/brepphylo'); pr <- plumber::plumb('plumber.R'); pr\$run(host='0.0.0.0', port=${METHOD_BREPPHYLO_HOST_PORT})"
```

Notice: default `tree_type=dnapars` expects `dnapars` on `PATH` (or `DNAPARS_PATH`). If using `tree_type=igphyml`, set `IGPHYML_BIN` and motifs (`IGPHYML_MOTIFS` or `IGPHYML_PATH`).

**ClonalTree (local Python)**

```bash
set -a; source .env; set +a
export CONTRACTS_DIR="$(pwd)/${CONTRACTS_DIR:-packages/contracts}"
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

# If methods run in Docker:
# export METHOD_SERVICE_FILE_PREFIX=/runtime/storage
#
# If methods run locally:
# export METHOD_SERVICE_FILE_PREFIX="$(pwd)/${STORAGE_LOCAL_PATH:-runtime/storage}"

npm run dev:api
```

### 6) Start web UI

```bash
set -a; source .env; set +a
npm run dev:web
```

Open `http://localhost:3000`.

---

## Environment Variables

All runtime configuration should live in root `.env`.

- `CONTRACTS_DIR` — contracts path used by API/methods
- `CORS_ORIGINS` — allowed web origins for API CORS
- `NEXT_PUBLIC_API_BASE_URL` — web -> API base URL
- `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_HOST` / `POSTGRES_PORT` — DB connection pieces
- `DATABASE_URL` — optional explicit DB URL override
- `STORAGE_LOCAL_PATH` — host-side storage directory
- `STORAGE_LOCAL_URL` — API URL prefix for local storage
- `METHOD_SERVICE_FILE_PREFIX` — path prefix that method services use to read uploaded files
- `METHOD_<ID>_URL` — host URL for each method service
- `METHOD_<ID>_URL_DOCKER` — compose-network URL for each method service
- `METHOD_<ID>_HOST_PORT` / `METHOD_<ID>_CONTAINER_PORT` — generated service ports
- `IGPHYML_BIN` / `IGPHYML_MOTIFS` / `IGPHYML_PATH` / `DNAPARS_PATH` — optional method runtime overrides

`apps/api/.env` and `apps/web/.env` are now legacy compatibility files and should stay empty.

---

## Troubleshooting

- **Ports busy** → stop other processes, or change ports in `.env` and compose files.
- **Dowser schema errors in Local R** → ensure you started R in `services/dowser` (or set `CONTRACTS_DIR` correctly); Docker option mounts contracts automatically.
- **`@phylo/contracts` not found** → run `npm i` at repo root; ensure `apps/web/package.json` depends on `"@phylo/contracts"`.
- **Docker is slow** → first run downloads large R images; subsequent runs are faster.
- **CORS** → make sure `CORS_ORIGINS` in API includes your web origin.

---

## Extend: Add a New Method

1. Create `packages/contracts/methods/<id>/` with:
   - `spec.json`, `param.schema.json`, `result.schema.json`, `ui.json`, `service.routes.json`
2. Provide a service exposing `/spec` and `/run` (containerized or remote).
3. Point the API to it via env: `METHOD_<METHODID_UPPER>_URL=http://host:port`.
4. The UI auto-renders the new parameters and accepts formats from `spec.json`.

---

## Repository Layout

```
apps/
  api/        # FastAPI orchestrator
  web/        # Next.js app
packages/
  contracts/  # Shared contracts (schemas, UI hints)
services/
  dowser/     # R/plumber service (Dowser)
# helper scripts:
#   run.sh
#   scripts/dev-with-docker.sh
#   scripts/dev-with-local-r.sh
#   scripts/select-mode.mjs
```
