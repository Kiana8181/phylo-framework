# Phylo-Framework

A web application for reconstructing B-cell lineage trees with four established
methods — **Dowser**, **GCtree**, **BrepPhylo** and **ClonalTree** — through one
workflow. Upload a dataset once, run any of the methods on it, and compare the
resulting trees side by side. Every run is recorded with its parameters, its
random seed and the version of the software that produced it.

![Architecture](./architecture.png)

| Component | What it is | Where |
|---|---|---|
| Web app | Next.js. Forms are generated from each method's contract | `apps/web` |
| API | FastAPI. Accounts, uploads, runs, results; the only part a browser talks to | `apps/api` |
| Worker | Follows each run from the queue to its stored result | `apps/api/workers` |
| Method services | One container per method (R for Dowser and BrepPhylo, Python for GCtree and ClonalTree) | `services/` |
| Contracts | JSON schemas that define each method's parameters and results for both the web app and the API | `packages/contracts` |
| PostgreSQL | Accounts, runs, trees and metadata | container |
| Object store | Uploaded datasets and result files (S3-compatible, self-hosted) | container |

## Choose your path

| You want to | Go to |
|---|---|
| **Try it on your own machine** | [Quick start](#quick-start-on-your-own-machine) below |
| **Deploy it on a server** | [Deploying on a server](#deploying-on-a-server), then [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) |
| **Change the code** | [docs/DEVELOPMENT.md](./docs/DEVELOPMENT.md) |

## Prerequisites

- **Docker** with the Compose plugin, version **2.17 or newer**
  (`docker compose version`). Docker Desktop on macOS and Windows includes it.
- **Git**.
- About **30 GB** of free disk space for the images (the two R method images
  are about 13 GB each) and **8 GB** of memory for Docker.

Nothing else. Node, Python and R are needed only to develop or to run the
tests.

## Quick start on your own machine

```bash
git clone git@github.com:Kiana8181/phylo-framework.git
cd phylo-framework
cp .env.example .env
docker compose --profile dev up -d --build
```

Then open **http://localhost:3000**.

- **The first build takes a long time** (tens of minutes): the R images are
  downloaded and several packages are compiled. Later starts take seconds.
- The example values in `.env` are enough for a local start. They are public,
  so they are refused in production.

**What happens at the first start**, without any further command: the database
is created and brought to the newest schema, both storage buckets and the
method services' write-only storage user are created, and the web app, the
API, the worker and the four method services start.

**First use:** choose *Sign up* and create an account (locally no email is
sent and the account works at once), open *Documentation → Try it yourself*,
pick a method and press *Run*. The sample dataset is included.

```bash
docker compose --profile dev ps                       # what is running
docker compose --profile dev logs -f api api-worker   # follow the logs
docker compose --profile dev down                     # stop; your data is kept
```

The API is at http://localhost:8000, with interactive documentation at
http://localhost:8000/docs.

## Deploying on a server

A deployment runs the `prod` profile behind a reverse proxy. It publishes no
port on the host, enforces resource limits on every container and refuses to
start with the example secrets. The server needs Docker with Compose 2.17+ and
nothing else.

```bash
git clone git@github.com:Kiana8181/phylo-framework.git
cd phylo-framework
cp .env.example .env     # then set the values listed below
./run.sh check           # can it start? changes nothing
./run.sh prod            # start, or update after `git pull`
./run.sh status          # is it complete?
```

Before the first start, set in `.env`:

1. **The secrets**: `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD` (and
   `S3_SECRET_ACCESS_KEY` to the same value), `MINIO_METHODS_PASSWORD`,
   `JWT_SECRET_KEY`. Generate each with `openssl rand -hex 32`.
2. **The public addresses**: `FRONTEND_URL`, `PUBLIC_API_BASE_URL`,
   `NEXT_PUBLIC_API_BASE_URL`, `CORS_ORIGINS`.
3. **The resource budget** the server grants this application:
   `PHYLO_CPU_BUDGET`, `PHYLO_MEMORY_BUDGET_MB`, `PHYLO_PIDS_BUDGET`.
4. **The reverse proxy's address**: `FORWARDED_ALLOW_IPS`.
5. **The mail server**, if email is wanted: `SMTP_HOST`, `SMTP_FROM` and, where
   needed, `SMTP_USERNAME` and `SMTP_PASSWORD`.

The reverse proxy must share the Docker network `proxy_net` with the
application and send requests to `phylo-web-prod:3000` and
`phylo-api-prod:8000`. Everything else — limits, quotas, retention, backups,
updates — is in [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md).

## `./run.sh`

| Command | What it does |
|---|---|
| `./run.sh check` | Checks everything a production start depends on. Read-only |
| `./run.sh prod` | The check, then `docker compose --profile prod up -d --build`. Extra arguments are passed on; `--no-build` starts what is already built |
| `./run.sh status` | Checks a running deployment: containers, database schema, buckets, method services, recorded version, email |
| `./run.sh ports` | Shows and checks the internal ports; `./run.sh ports randomize` stores random ones |
| `./run.sh down` | Stops the production stack. Data volumes are kept |
| `./run.sh` | Interactive menu, including the development modes (see [docs/DEVELOPMENT.md](./docs/DEVELOPMENT.md)) |

`./run.sh prod` is a convenience: you may run the Compose command yourself.

## Docker Compose commands

Both profiles are in `docker-compose.yml`. Use one of them, not both on one
machine: they share the database and storage volumes.

| | Local (`dev`) | Server (`prod`) |
|---|---|---|
| Start or update | `docker compose --profile dev up -d --build` | `docker compose --profile prod up -d --build` |
| State | `docker compose --profile dev ps` | `docker compose --profile prod ps` |
| Logs | `docker compose --profile dev logs -f api api-worker` | `docker compose --profile prod logs -f api-prod api-worker-prod` |
| Stop, keep data | `docker compose --profile dev down` | `docker compose --profile prod down` |
| Published ports | web 3000, API 8000 | none (reverse proxy) |
| Secrets | example values accepted | example values refused |

`down -v` also **deletes the database and all stored files**. Never use it on a
server.

## Configuration

One file, `.env`, copied from [`.env.example`](./.env.example), which describes
every setting. The complete list with defaults and constraints is
[docs/CONFIGURATION.md](./docs/CONFIGURATION.md). The settings an
administrator most often decides on:

| Setting | Default | Meaning |
|---|---|---|
| `RESULT_RETENTION_DAYS` | `60` | Days a run's results are kept. **They are deleted afterwards**; datasets and the run's history are not |
| `MAX_RUNS_PER_USER_PER_HOUR` | `5` | Runs a user may start in any 60 minutes |
| `MAX_UPLOAD_MB` | `500` | Largest file a user may upload |
| `RUN_TIMEOUT_SECONDS` | `86400` | Longest a run may execute |
| `PHYLO_CPU_BUDGET`, `PHYLO_MEMORY_BUDGET_MB` | `4`, `8192` | What all containers together may use |
| `SMTP_HOST` | empty | Mail server. Empty: no email is sent, and new accounts need no confirmation |
| `CAPTCHA_ENABLED` | `true` | Proof-of-work check on the sign-in forms. Self-hosted |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `required variable … is missing a value` | `.env` is missing or incomplete. `cp .env.example .env`, or set the variable named in the message |
| A production container keeps restarting; its log says "Refusing to start" | A secret still has its example value, or `JWT_SECRET_KEY` is shorter than 32 characters. The log names the variables |
| `network proxy_net declared as external, but could not be found` | The reverse proxy's network does not exist. On a server ask whoever runs the proxy; on a test machine `docker network create proxy_net` |
| `port is already allocated` at a local start | Something else uses 3000 or 8000. Set `WEB_PORT` / `API_PORT` in `.env`, and `NEXT_PUBLIC_API_BASE_URL`, `PUBLIC_API_BASE_URL`, `CORS_ORIGINS` and `FRONTEND_URL` to match, then start again with `--build` |
| The page loads but every request fails (CORS) | `CORS_ORIGINS` does not contain the address in the browser's address bar, or `NEXT_PUBLIC_API_BASE_URL` was changed without rebuilding the web image |
| A run stays "waiting for capacity" | Its method service is busy; each runs one job at a time by default. It starts when the slot is free |
| A run ends with `OUT_OF_MEMORY` | The job needed more than its container may use. Try a smaller dataset or raise the memory budget |
| Sign-up says "check your email" and nothing arrives | A mail server is configured but not delivering. `./run.sh status` and the worker log show why |
| "Results expired" on an old run | Results are removed after `RESULT_RETENTION_DAYS`. The run's settings are kept: run it again |
| Something else | `./run.sh status` on a server; `docker compose --profile <dev or prod> logs <service>` |

More, including what every run error code means:
[docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md#when-a-run-cannot-finish).

## Documentation

| Document | Contents |
|---|---|
| [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) | Running it on a server: secrets, resource budget, limits and quotas, time limits, retention, sign-in protection, email, networks, ports, updates, backup and restore |
| [docs/CONFIGURATION.md](./docs/CONFIGURATION.md) | Every setting, with default and constraints |
| [docs/DEVELOPMENT.md](./docs/DEVELOPMENT.md) | Development modes, running parts by hand, adding a method |
| [docs/TESTING.md](./docs/TESTING.md) | The test suites and what each covers |
| [docs/VALIDATION.md](./docs/VALIDATION.md) | Tests of the whole system under pressure, and the result of the last validation |
| [docs/SECURITY-AUDIT.md](./docs/SECURITY-AUDIT.md) | Dependency and image scans, open findings |
| [docs/HISTORY-CLEANUP.md](./docs/HISTORY-CLEANUP.md) | Credentials committed in the past: what to rotate, how the history was cleaned |
| [docs/OBJECT-STORAGE-OPTIONS.md](./docs/OBJECT-STORAGE-OPTIONS.md) | Why the object store is the Silo fork of MinIO |

The running application has its own user documentation under *Documentation*:
data requirements, each method's parameters, and the example.

## Tests

```bash
npm ci && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-test.txt
npx playwright install chromium

npm test                       # contracts, web, type check, Python (real PostgreSQL and object storage)
npm run test:all -- --build    # plus all four methods end to end, browser and R tests
npm run test:system            # the real stack under pressure
```

They run in their own Compose project with throwaway data and never touch a
running application. Details: [docs/TESTING.md](./docs/TESTING.md).

## Repository layout

```
apps/api/            API and worker (FastAPI, SQLAlchemy, Alembic migrations)
apps/web/            web application (Next.js)
packages/contracts/  method contracts: parameters, results, routes
services/            the four method services
scripts/             deployment checks, resource plan, ports, scans, development helpers
tests/               integration, deployment, end-to-end, browser and system tests
docs/                documentation
docker-compose.yml   the application: `dev` and `prod` profiles
run.sh               entry point for deployment and development
.env.example         every setting, described
```

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
| ClonalTree | [smhamidi/clonotype](https://github.com/smhamidi/clonotype) (copied unchanged into `services/clonaltree/base-codes/` from upstream commit `1122537`, with its MIT licence) |
| Dowser | [Immcantation](https://immcantation.readthedocs.io/) suite |
| BrepPhylo | [Fraternalilab/BrepPhylo](https://github.com/Fraternalilab/BrepPhylo) |
| PHYLIP (`dnapars`) | [PHYLIP 3.697](https://phylipweb.github.io/phylip/) |
| MUSCLE | [rcedgar/muscle](https://github.com/rcedgar/muscle) |

Consult each project's own licence before redistributing its image.
