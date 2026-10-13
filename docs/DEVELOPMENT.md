# Development guide

For people who change Phylo-Framework. To run it, the [README](../README.md) is
enough; to deploy it, see [DEPLOYMENT.md](./DEPLOYMENT.md).

Tested in the validation of 2026-10-13: the Docker Compose `dev` profile from a
fresh clone, and every test command. **Not** exercised then: the two
`./run.sh` modes that run the API on the host, and method services run outside
their images. They are documented here as they are in the scripts.

## Ways to run it while developing

| Mode | What runs where | Start it with | Use it for |
|---|---|---|---|
| Everything in Docker | All services in containers; the web app reloads on source changes | `docker compose --profile dev up -d --build` | Trying a change end to end; no Node, Python or R needed on the host |
| API on the host, methods in Docker | API, worker and web on the host with hot reload; database, object store and method services in containers | `./run.sh`, then "Dev — methods in Docker" | Working on the API, the worker or the web app |
| Everything on the host | As above, with the method services as local R and Python processes | `./run.sh`, then "Dev — methods in local R" | Working on a method service itself |

The `dev` and `prod` Compose profiles use the same database and object-store
containers and volumes (`phylo_postgres_data`, `phylo_minio_data`). Do not run
both on one machine, and never run the development commands on a server that
holds real data.

### Everything in Docker

```bash
cp .env.example .env          # first time only
docker compose --profile dev up -d --build
docker compose --profile dev logs -f api api-worker
docker compose --profile dev down        # add -v to also delete the database and the stored files
```

Web: http://localhost:3000. API: http://localhost:8000 (interactive docs at
`/docs`). The API container applies database migrations when it starts and the
`minio-init` container creates both buckets.

The web container mounts the source tree for hot reload but keeps the image's
own `node_modules` and build output. After changing dependencies:

```bash
docker compose --profile dev up -d --build --renew-anon-volumes web
```

The API and worker containers run the code built into their image: rebuild
after changing Python code (`docker compose --profile dev up -d --build api api-worker`),
or use one of the host modes for hot reload.

### API on the host

Prerequisites on the host:

- **Node.js 22** and **Python 3.12** (what CI uses), Docker for the containers.
- For "methods in local R" also **R 4.3+** with the packages of the service you
  run (CRAN: `plumber`, `dowser`, `alakazam`, `shazam`, `ggtree`, `ape`,
  `jsonlite`, `jsonvalidate`, `sodium`; Bioconductor: `Biostrings`, `treeio`,
  `ggtree` and their dependencies), plus PHYLIP, and MUSCLE 5 for ClonalTree.
- On Windows use WSL2: the helper scripts are Bash scripts.

```bash
./run.sh          # choose a development mode
```

The scripts start PostgreSQL and the object store through
`docker-compose.dev.yml`, which publishes them on the host (database on port
5440, object store on 9000 and 9001). That file is for development only; never
load it on a server.

## Method services

Ports and addresses of the four method services come from
`config/method-services.json`. For processes run on the host they are written
into `.env`:

| Command | What it does |
|---|---|
| `npm run services:sync-env` | Write the `METHOD_*` lines in `.env` from `config/method-services.json` |
| `npm run services:list` | List service ids, ports and addresses |
| `npm run services:start` | Build and start all method services as plain containers (`npm run services:start -- gctree dowser` for some) |
| `npm run services:stop` | Stop them (`npm run services:stop -- gctree` for one) |

A deployment does not need these: `docker-compose.yml` carries the same
defaults, and a test keeps the two in step.

Method services upload their result files directly to the object store with a
write-only user (`MINIO_METHODS_USER`), and report what they uploaded. The
worker verifies and records it. There is no shared output directory.

## Running every part by hand

What `./run.sh` does in its development modes, step by step.

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

npm run db:migrate             # brings the database to the newest revision
npm run storage:check          # round-trips both buckets via the host (localhost:9000) — the real readiness gate
```

> `set -a; source .env` needs every value with spaces or `<` in it to be quoted,
> as `SMTP_FROM` is in `.env.example`. An unquoted one stops the shell at that
> line, and everything after it in the file is silently not loaded. The npm
> scripts (`node --env-file=.env …`) and Docker Compose do not have this problem.

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

**ClonalTree (local Python)**

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
If you start ClonalTree manually, ensure `muscle -version` reports major version `>= 5`; otherwise its jobs fail with a version error.

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

### 6) Start the run worker

Takes `QUEUED` runs, follows their method jobs, checks that every result file
is in the object store and records it. Run in a **separate terminal** from API
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

### 7) Start the web UI

```bash
set -a; source .env; set +a
npm run dev:web
```

Open `http://localhost:3000`.

---

## Starting over (local data only)

```bash
bash ./scripts/reset-local.sh
```

Asks for confirmation, then stops the development stack, **deletes the volumes
`phylo_postgres_data` and `phylo_minio_data`** and the `./runtime` staging
folders, starts a clean stack and runs the storage check. It never runs
`docker volume prune` and touches no other project. These are the same volume
names a production deployment on the same machine would use: this script is
for a development machine only.

By hand:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev down -v --remove-orphans
rm -rf ./runtime/storage ./runtime/method-jobs
docker compose --profile dev up -d --build
```

## Database migrations

See [apps/api/database/README.md](../apps/api/database/README.md). In every
containerised mode the API applies pending migrations when it starts.

## Adding a method

1. Create `packages/contracts/methods/<id>/` with `spec.json`,
   `param.schema.json`, `result.schema.json`, `ui.json`, `service.routes.json`
   and `completion.json` (what a finished run must contain to count as done).
2. Provide a service that implements `/spec`, `/capacity` and the asynchronous
   `/jobs` lifecycle (submit, status, result, cancel, log, delete). The four
   existing services show both an R and a Python implementation.
3. Tell the API where it is: `METHOD_<ID>_URL=http://host:port`, and add the
   service to `docker-compose.yml` and `config/method-services.json`.
4. The web app renders the new parameters and accepts the formats in
   `spec.json` without further changes.

## Tests

[TESTING.md](./TESTING.md) describes every layer; [VALIDATION.md](./VALIDATION.md)
the tests that put the real stack under pressure.

```bash
npm test                        # contracts, web, type check, Python against real PostgreSQL and object storage
npm run test:all -- --build     # plus all four methods end to end, browser tests, R tests
npm run test:system             # the real stack under pressure (separate, about 10 minutes)
npm run lint
```

## Commit messages

[COMMIT_GUIDE.md](../COMMIT_GUIDE.md).
