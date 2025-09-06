# phylo-framework

A one-page UI to run phylogeny/lineage tree methods behind a simple orchestrator API.

- **Web**: Next.js (apps/web)
- **API**: FastAPI (apps/api)
- **Methods**: pluggable microservices (R/plumber for **Dowser** provided)
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

1. **Install Node & workspace deps (root)** and **API Python deps**:

```bash
# Node deps (root — installs workspaces too)
npm i

# Python deps for the API
python -m pip install -U pip
python -m pip install -r apps/api/requirements.txt
```

2. **Make helper scripts executable** (they are expected at the repo root):

```bash
chmod +x ./run.sh ./dev-with-docker.sh ./dev-with-local-r.sh
```

3. **Run the interactive menu** (uses Inquirer under the hood):

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

| Service | URL                   | Port |
| ------: | --------------------- | ---: |
|     Web | http://localhost:3000 | 3000 |
|     API | http://localhost:8000 | 8000 |
|  Dowser | http://localhost:8001 | 8001 |

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

## Manual Run (Developers)

If you want to run everything **without** the helper scripts, follow this.

### 1) Prepare environment files

Create and fill these files (adjust ports/paths if you changed them).

**apps/api/.env**

```env
CONTRACTS_DIR=packages/contracts
METHOD_DOWSER_URL=http://localhost:8001
CORS_ORIGINS=http://localhost:3000
```

**apps/web/.env.local**

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

### 2) Install project dependencies

From the **repo root**:

```bash
# Node deps (monorepo)
npm i

# Python venv for API
python -m venv .venv
source .venv/bin/activate      # Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r apps/api/requirements.txt

# (Optional if your contracts package compiles TS)
npm -w @phylo/contracts run build
```

### 3) Start a method service (Dowser) — pick ONE option

#### Option A — Docker (recommended; no local R needed)

Build the image **from the dowser folder**, then run it **from repo root**:

```bash
# build
cd services/dowser
docker build -t phylo-dowser:dev .

# run (from REPO ROOT)
cd ../..
docker run --rm -p 8001:8001   -v "$(pwd)/packages/contracts:/contracts:ro"   -e CONTRACTS_DIR=/contracts   phylo-dowser:dev
```

**Windows PowerShell** (repo root):

```powershell
docker run --rm -p 8001:8001 `
  -v ${PWD}/packages/contracts:/contracts:ro `
  -e CONTRACTS_DIR=/contracts `
  phylo-dowser:dev
```

This exposes Dowser at **http://localhost:8001** with contracts mounted read-only.

#### Option B — Local R (requires R 4.3+ & packages)

From the **repo root**:

```bash
Rscript -e 'setwd("services/dowser"); Sys.setenv(CONTRACTS_DIR="../../packages/contracts"); pr <- plumber::plumb("plumber.R"); pr$run(host="0.0.0.0", port=8001)'
```

Keep this terminal open; it’s your method server.

### 4) Start the API (FastAPI)

In a **new terminal** (repo root):

```bash
# load API env
set -a; source apps/api/.env; set +a

# start API
npm run dev:api
```

### 5) Start the Web UI (Next.js)

In another **new terminal** (repo root):

```bash
# Next.js will read apps/web/.env.local automatically
npm run dev:web
```

Open **http://localhost:3000** and you should see the app. The UI will call the API on `:8000`, which in turn calls Dowser on `:8001`.

---

## Environment Variables

- `CONTRACTS_DIR` — path to `packages/contracts` (API & methods use this)
- `CORS_ORIGINS` — dev default includes `http://localhost:3000`
- `METHOD_DOWSER_URL` — URL of Dowser service, e.g. `http://localhost:8001` in dev
- `NEXT_PUBLIC_API_BASE_URL` — Web UI → API base URL (set in `apps/web/.env*`)

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
# helper scripts are placed at repo root:
#   run.sh, dev-with-docker.sh, dev-with-local-r.sh, select-mode.mjs
```
