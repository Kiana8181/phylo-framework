# Configuration reference

Every setting of a Phylo-Framework deployment, with its default, what it does
and the constraints on it. Behaviour is explained in
[DEPLOYMENT.md](./DEPLOYMENT.md); this page is the list.

## How configuration works

- **One file.** All settings live in `.env` at the repository root. Create it
  with `cp .env.example .env`. It is ignored by git and must never be
  committed.
- **Who reads it.** The API and the worker read the whole file. Every other
  container (web, database, object store, the four method services) receives
  only the values `docker-compose.yml` passes to it, so the services that parse
  uploaded files never see the database password or the signing key.
- **Applying a change.** Recreate the containers:
  `docker compose --profile prod up -d` (or `./run.sh prod --no-build`). A
  change of the resource budget also needs `sh scripts/resource-plan.sh --write`
  first, which `./run.sh prod` does for you.
- **Checking it.** `./run.sh check` validates the file before anything starts;
  `./run.sh status` reports what a running deployment actually uses.
- **Wrong values.** A value that is not a number where one is expected is
  ignored in favour of the default; it never switches a limit off by accident.
  Missing or weak secrets stop a production start, with the names of the
  variables in the log (never their values).

In the tables, **Default** is what applies when the variable is unset. "—"
means there is none and the variable is required or optional as noted.

## 1. Required secrets

Docker Compose refuses to start when one of these is unset, and a production
API or worker exits at start-up when one still has its `.env.example` value.
Generate each with `openssl rand -hex 32`.

| Variable | Constraint |
|---|---|
| `POSTGRES_USER`, `POSTGRES_DB` | Required. Any name |
| `POSTGRES_PASSWORD` | Required. Not the example value. If you set `DATABASE_URL` yourself it must contain the same password |
| `MINIO_ROOT_USER` | Required. Any name |
| `MINIO_ROOT_PASSWORD` | Required. Not the example value |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Must be the root user and password above (the default), or the credentials of your own object-store user |
| `MINIO_METHODS_USER` | Required. Any name. The write-only user the method services upload results with |
| `MINIO_METHODS_PASSWORD` | Required. Not the example value |
| `JWT_SECRET_KEY` | Required. Unique, random, at least 32 characters. Changing it signs everyone out |

## 2. Application

| Variable | Default | Meaning |
|---|---|---|
| `ENV` | `development` | For processes run directly on a host. The production containers always get `production` from `docker-compose.yml`, whatever this says |
| `FRONTEND_URL` | `http://localhost:3000` | Public address of the web app. Used in every link sent by email: on a server it must be the address users open |
| `PUBLIC_API_BASE_URL` | `http://localhost:8000` | Public address of the API |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Address the browser calls the API at. Built into the web image: rebuild after changing it |
| `CORS_ORIGINS` | `http://localhost:3000` | Browser origins allowed to call the API, comma-separated. `*` is rejected in production |
| `API_DOCS_ENABLED` | off in production | `true` exposes `/docs`, `/redoc` and `/openapi.json` in production |
| `LOG_LEVEL` | `INFO` | Log level of the API and the worker |
| `PHYLO_LOG_MAX_SIZE`, `PHYLO_LOG_MAX_FILES` | `10m`, `5` | Rotation of each container's log |
| `STORAGE_QUOTA_PER_USER_GB` | `2` | Total size of the datasets one user may keep |
| `HTTP_CLIENT_TIMEOUT`, `SPEC_TIMEOUT` | `600`, `60` | Seconds the API waits for a method service (general calls, method specification) |
| `CONTRACTS_DIR`, `STRICT_CONTRACT_ROUTES` | `packages/contracts`, `true` | Where the method contracts are read from, and whether a method must declare all its routes. Containers get `/contracts` mounted; leave both alone |

## 3. Database

| Variable | Default | Meaning |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | — | See required secrets. In containers the connection is built from these |
| `POSTGRES_HOST`, `POSTGRES_PORT`, `DATABASE_URL` | `127.0.0.1`, `5440`, built from the above | Only for an API or worker run directly on a host (development). Containers ignore them and connect to `phylo-postgres` on `PHYLO_PORT_POSTGRES` |

## 4. Object storage

Datasets and result files are kept in an S3-compatible object store. The
default is the self-hosted store started by Compose (the Silo fork of MinIO).

| Variable | Default | Meaning |
|---|---|---|
| `STORAGE_BACKEND` | `minio` | `minio`, `s3` (any S3-compatible service) or `local` (tests only) |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | — | Administrator of the bundled store. See required secrets |
| `MINIO_METHODS_USER`, `MINIO_METHODS_PASSWORD` | — | User created at first start, allowed only to add objects to the artifact bucket. Given to the method services |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | the root user and password | Credentials the API and worker use |
| `S3_BUCKET_DATASETS`, `S3_BUCKET_ARTIFACTS` | `phylo-datasets`, `phylo-artifacts` | Bucket names. Both are created at first start |
| `S3_REGION`, `S3_FORCE_PATH_STYLE` | `us-east-1`, `true` | Region label (any value for the bundled store) and path-style addressing (required for it) |
| `S3_ENDPOINT_URL_DOCKER` | `http://phylo-minio:<PHYLO_PORT_MINIO>` | Address of the store as containers see it. Normally leave unset. If set, its port must equal `PHYLO_PORT_MINIO` |
| `S3_ENDPOINT_URL` | `http://localhost:9000` | Address of the store for processes run on a host (development) |
| `PHYLO_OBJECT_STORE_IMAGE`, `PHYLO_OBJECT_STORE_CLIENT_IMAGE` | pinned by digest | Pull the store and its client from your own registry mirror. Keep the digest unchanged |
| `STORAGE_LOCAL_PATH` | `runtime/storage` | Host directory where a run's input is staged for its method service. Scratch space, not the store. Created at first start |
| `HOST_RUNTIME_SHARED_ROOT`, `METHOD_SERVICE_FILE_PREFIX`, `STORAGE_LOCAL_URL` | `/runtime/storage`, `/runtime/storage`, `/storage` | How that directory is named inside containers. Leave alone |

## 5. Sign-in and accounts

| Variable | Default | Meaning |
|---|---|---|
| `JWT_SECRET_KEY` | — | See required secrets |
| `JWT_ALGORITHM` | `HS256` | Signing algorithm of session tokens |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `30`, `7` | Lifetime of a session token and of the token that renews it |
| `PASSWORD_MIN_LENGTH` | `8` | Shortest password accepted at sign-up and password reset (longest: 128) |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | empty, empty, `http://localhost:3000/auth/callback` | Google sign-in. Empty switches it off. The redirect must be `<FRONTEND_URL>/auth/callback` and be registered with Google |
| `CAPTCHA_ENABLED` | `true` | Proof-of-work check on sign-in, sign-up and password reset. Self-hosted |
| `CAPTCHA_DIFFICULTY_BITS` | `18` | Work per form submission; each extra bit doubles it. 1 to 30; anything else means the default |
| `CAPTCHA_TTL_SECONDS` | `300` | How long an issued challenge may be used |
| `AUTH_RATE_LIMITS_ENABLED` | `true` | Master switch for the limits below |
| `AUTH_LIMIT_LOGIN_IP` | `30/900` | Sign-in attempts per client address, written `count/seconds`. `0` switches one limit off |
| `AUTH_LIMIT_LOGIN_ACCOUNT` | `10/900` | Failed sign-in attempts per account; then the account accepts none until the window ends |
| `AUTH_LIMIT_REGISTER_IP` | `10/3600` | Registrations per client address |
| `AUTH_LIMIT_FORGOT_IP`, `AUTH_LIMIT_FORGOT_ACCOUNT` | `10/3600`, `3/3600` | Password-reset requests per address, and reset emails per account |
| `AUTH_LIMIT_VERIFY_IP`, `AUTH_LIMIT_VERIFY_ACCOUNT` | `10/3600`, `3/3600` | Confirmation-email requests per address, and confirmation emails per account |
| `FORWARDED_ALLOW_IPS` | unset | Address or network of the reverse proxy, comma-separated. **Required behind a proxy**: without it every visitor appears to come from the proxy and shares one allowance. Check with `curl <api>/auth/client-ip` |
| `EMAIL_VERIFICATION` | `auto` | `auto`: new accounts must confirm their address when a mail server is configured. `required`: always. `off`: never |
| `EMAIL_VERIFICATION_EXPIRE_HOURS` | `24` | How long a confirmation link works |

## 6. Email

All email (confirmation, password reset, run notifications) goes through one
SMTP server. The values come from whoever runs that server.

| Variable | Default | Meaning |
|---|---|---|
| `SMTP_HOST` | empty | Mail server. **Empty switches email off**: nothing is sent and nothing else stops working |
| `SMTP_SECURITY` | `starttls` | `starttls`, `ssl` or `none` |
| `SMTP_PORT` | by security: `587`, `465`, `25` | Port of the mail server |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | empty | Login. Set both or neither. Refused with `SMTP_SECURITY=none`: a password is never sent without TLS |
| `SMTP_FROM` | — | Sender shown to recipients. Required when `SMTP_HOST` is set |
| `SMTP_TIMEOUT_SECONDS` | `15` | Wait for the mail server at each step |
| `SMTP_TLS_VERIFY`, `SMTP_TLS_CA_FILE` | `true`, unset | Certificate verification, and a CA bundle for a server with a private CA. Prefer the bundle to switching verification off |
| `RUN_NOTIFICATIONS_ENABLED` | `true` | One email to the owner when a run ends as done or failed, or expires in the queue. Cancelled runs never send one |
| `NOTIFICATION_MAX_ATTEMPTS` | `6` | Attempts per email |
| `NOTIFICATION_RETRY_BASE_SECONDS`, `NOTIFICATION_RETRY_MAX_SECONDS` | `60`, `21600` | Wait before the second attempt; each further wait is four times longer, up to the maximum |
| `NOTIFICATION_POLL_SECONDS` | `15` | How often the worker looks for email to send |

## 7. Resource budget and container limits

One budget for the whole stack. These are not server sizes and there is no
built-in percentage: use the share the infrastructure team gives this
deployment.

| Variable | Default | Meaning |
|---|---|---|
| `PHYLO_CPU_BUDGET` | `4` | CPU cores for all containers together. Minimum 2.05 |
| `PHYLO_MEMORY_BUDGET_MB` | `8192` | Memory in MiB for all containers together. Minimum 6592 |
| `PHYLO_PIDS_BUDGET` | `4096` | Processes and threads for all containers together. Minimum 2432 |
| `PHYLO_RESOURCE_MODE` | `strict` | `strict`: CPU limits add up to at most the budget. `pooled`: each method may use the whole method share; only with `PHYLO_CGROUP_PARENT` |
| `PHYLO_CGROUP_PARENT` | unset | A host cgroup (for example a systemd slice) that enforces the total |
| `PHYLO_CPUS_<SERVICE>`, `PHYLO_MEM_<SERVICE>`, `PHYLO_PIDS_<SERVICE>` | the plan for the default budget | **Generated**, in a marked block, by `sh scripts/resource-plan.sh --write`. Do not edit by hand |

## 8. Job execution

Normally leave all of these unset: each method service derives its job slots
and threads from its own container limits.

| Variable | Default | Meaning |
|---|---|---|
| `PHYLO_<METHOD>_MAX_JOBS` | derived | Jobs a method service runs at once (memory still caps it). `<METHOD>` is `DOWSER`, `BREPPHYLO`, `GCTREE` or `CLONALTREE` |
| `PHYLO_<METHOD>_THREADS_PER_JOB` | derived | CPU budget of one job. Cannot exceed the container's CPUs |
| `PHYLO_<METHOD>_JOB_MEMORY_MB` | Dowser, BrepPhylo `950`; GCtree `256`; ClonalTree `192` | Estimated peak memory of one job, measured on the sample dataset. Raise it for much larger datasets |
| `PHYLO_MEMORY_HEADROOM_PERCENT` | `10` | Share of each method container's memory kept free |
| `WORKER_MAX_CONCURRENT_RUNS` | sum of all job slots | Runs the worker follows at once |
| `PHYLO_JOB_OOM_SCORE_ADJ` | `800` | How strongly a job offers itself as the process to stop when its container runs out of memory. `0` to `1000`; `0` lets the kernel pick the largest process, usually the service |

## 9. Limits per user

| Variable | Default | Meaning |
|---|---|---|
| `MAX_RUNS_PER_USER_PER_HOUR` | `5` | Runs in any rolling 60 minutes. Runs whose analysis never started do not count. `0` = no limit |
| `MAX_QUEUED_RUNS_PER_USER` | `5` | Runs waiting behind a user's active run |
| `MAX_RUN_SUBMISSIONS_PER_USER_PER_HOUR` | `30` | Every run created in 60 minutes, whatever became of it. Never applied below the hourly limit. `0` = no ceiling |

## 10. Time limits and recovery

Seconds.

| Variable | Default | Meaning |
|---|---|---|
| `RUN_TIMEOUT_SECONDS` | `86400` | Longest a run may execute. `0` = no limit |
| `RUN_TIMEOUT_SECONDS_<METHOD>` | unset | The same for one method |
| `RUN_QUEUE_WAIT_TIMEOUT_SECONDS` | `172800` | Longest a run that is ready may wait for a free slot. `0` = no limit |
| `RUN_STAGING_TIMEOUT_SECONDS` | `1800` | Longest the worker may take to fetch and prepare a run's input. `0` = no limit |
| `WORKER_METHOD_UNREACHABLE_SECONDS` | `300` | How long a method service may be unreachable while one of its jobs is followed |
| `WORKER_CANCEL_CONFIRM_SECONDS` | `60` | How long the worker waits for a stop to be confirmed |
| `WORKER_DATABASE_UNAVAILABLE_SECONDS` | `90` | How long the worker waits for the database while it follows a job. Never more than half of `WORKER_LEASE_SECONDS` |
| `ARTIFACT_VERIFY_ATTEMPTS`, `ARTIFACT_VERIFY_RETRY_SECONDS`, `ARTIFACT_VERIFY_TIMEOUT_SECONDS` | `3`, `5`, `30` | The check that every result file is in the store before a run becomes done |
| `PHYLO_METHOD_JOB_TIMEOUT_SECONDS` | unset | Time limit a method service applies to a job that arrives without one. The worker always sends one |

## 11. Storage lifecycle

**`RESULT_RETENTION_DAYS` deletes user data.** Read
[Storage lifecycle and retention](./DEPLOYMENT.md#storage-lifecycle-and-retention)
before changing it.

| Variable | Default | Meaning |
|---|---|---|
| `RESULT_RETENTION_DAYS` | `60` | Days a run's result files, trees and logs are kept after it ended. The run itself stays in the history. Datasets are not removed. `0` = keep for ever |
| `MAX_UPLOAD_MB` | `500` | Largest single file a user may upload. The reverse proxy must accept request bodies at least this large |
| `UPLOAD_SESSION_GRACE_HOURS` | `24` | Age after which an unfinished upload is cleaned up |
| `RETENTION_SWEEP_SECONDS` | `3600` | How often expired results and abandoned uploads are looked for |
| `PHYLO_JOB_LOG_MAX_MB` | `5` | Largest execution log kept for a run |
| `PHYLO_JOB_RETENTION_HOURS` | `24` | How long a method service keeps a finished job nobody collected |

## 12. Ports, networks and the image build

No port is published on the host in production. See
[Internal ports](./DEPLOYMENT.md#internal-ports).

| Variable | Default | Meaning |
|---|---|---|
| `PHYLO_PORT_POSTGRES` | `5432` | Port PostgreSQL listens on inside the project network |
| `PHYLO_PORT_MINIO`, `PHYLO_PORT_MINIO_CONSOLE` | `9000`, `9001` | Object store API and console. Must differ |
| `PHYLO_PORT_API`, `PHYLO_PORT_WEB` | `8000`, `3000` | The two ports the reverse proxy connects to. Changing one means changing the proxy |
| `METHOD_<NAME>_CONTAINER_PORT` | `8001`–`8004` | Port of each method service (Dowser, GCtree, BrepPhylo, ClonalTree) |
| `METHOD_<NAME>_URL_DOCKER` | `http://phylo-<name>:<port>` | Address of each method service as containers see it. Normally leave unset. If set, its port must equal the one above |
| `PHYLO_GIT_DIR` | `./.git` | Where the image build reads the deployed commit from. `config/no-git` when deploying from an archive |
| `IMMCANTATION_PLATFORM` | `linux/amd64` | Platform of the two R service images, whose base image exists for amd64 only |

All ports must be between 1024 and 65535. `./run.sh ports` shows and checks
them.

## 13. Local development only

Ignored by a production deployment.

| Variable | Default | Meaning |
|---|---|---|
| `WEB_PORT`, `API_PORT` | `3000`, `8000` | Host ports the `dev` Compose profile publishes the web app and the API on |
| `POSTGRES_PORT`, `MINIO_API_PORT`, `MINIO_CONSOLE_PORT`, `DEV_MINIO_BIND` | `5440`, `9000`, `9001`, `0.0.0.0` | Host ports (and interface) `docker-compose.dev.yml` publishes the database and the store on, for an API run on the host |
| `METHOD_<NAME>_HOST_PORT`, `METHOD_<NAME>_URL` | `8001`–`8004`, `http://localhost:<port>` | Where an API run on the host finds each method service. Written by `npm run services:sync-env` from `config/method-services.json` |
| `IGPHYML_BIN`, `IGPHYML_MOTIFS`, `IGPHYML_PATH`, `DNAPARS_PATH`, `DNAML_PATH`, `RAXML_BIN` | set in the images | Paths of the external tools, for method services run outside their images |

## 14. Internal tuning

Rarely worth changing. Listed so that nothing the application reads is
undocumented.

| Variable | Default | Meaning |
|---|---|---|
| `WORKER_POLL_INTERVAL` | `3` | Seconds between the worker's looks at the queue |
| `WORKER_METHOD_POLL_INTERVAL` | `10` | Seconds between status requests for a running job. A finished run becomes visible at the next one |
| `WORKER_LEASE_SECONDS` | `180` | How long a worker's claim on a run lasts without renewal. After that another worker may take the run over |
| `WORKER_CAPACITY_REFRESH_SECONDS` | `5` | How long the worker trusts a method service's capacity report |
| `WORKER_RESULT_FETCH_ATTEMPTS` | `3` | Attempts to fetch a finished job's result |
| `WORKER_METHOD_DEADLINE_GRACE_SECONDS` | `120` | Extra time a method service's own deadline gets, so that the worker normally reports a timeout first |
| `JOB_SUBMIT_TIMEOUT`, `JOB_STATUS_TIMEOUT`, `JOB_CANCEL_TIMEOUT`, `JOB_RESULT_TIMEOUT`, `METHOD_CAPACITY_TIMEOUT` | `30`, `30`, `30`, `300`, `5` | Seconds the worker waits for each kind of request to a method service |
| `JOB_CANCEL_GRACE_SECONDS` | `5` | Seconds a cancelled job gets to stop before it is killed |
| `MINIO_ENDPOINT`, `MINIO_SECURE` | from `S3_ENDPOINT_URL` | Alternative way to name the store for `STORAGE_BACKEND=minio` |

## 15. Set by the system

These exist inside containers but are set by `docker-compose.yml`, the images
or the code. Setting them in `.env` has no effect or is overridden.

| Inside the container | Comes from |
|---|---|
| `ENV=production` (API, worker) | fixed in `docker-compose.yml` for the production services |
| `DATABASE_URL`, `POSTGRES_HOST`, `S3_ENDPOINT_URL`, `METHOD_<NAME>_URL` | built from the names and ports above |
| `METHOD_MAX_CONCURRENT_JOBS`, `METHOD_THREADS_PER_JOB`, `METHOD_JOB_MEMORY_MB` | `PHYLO_<METHOD>_MAX_JOBS`, `…_THREADS_PER_JOB`, `…_JOB_MEMORY_MB` |
| `METHOD_MEMORY_HEADROOM_PERCENT`, `METHOD_JOB_OOM_SCORE_ADJ` | `PHYLO_MEMORY_HEADROOM_PERCENT`, `PHYLO_JOB_OOM_SCORE_ADJ` |
| `METHOD_JOB_LOG_MAX_MB`, `METHOD_JOB_RETENTION_HOURS`, `METHOD_JOB_TIMEOUT_SECONDS` | `PHYLO_JOB_LOG_MAX_MB`, `PHYLO_JOB_RETENTION_HOURS`, `PHYLO_METHOD_JOB_TIMEOUT_SECONDS` |
| `METHOD_JOBS_DIR`, `METHOD_BASELINE_MEMORY_MB`, `METHOD_CPU_LIMIT` | internal to each method service |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` (method services) | `MINIO_METHODS_USER`, `MINIO_METHODS_PASSWORD` |
| `PGPORT`, `MINIO_ADDRESS`, `MINIO_CONSOLE_ADDRESS`, `PORT` | `PHYLO_PORT_POSTGRES`, `PHYLO_PORT_MINIO`, `PHYLO_PORT_MINIO_CONSOLE`, `PHYLO_PORT_WEB` |
| `PHYLO_VERSION_INFO_PATH` | the file the image build writes |
| `PHYLO_JOB_CHILD`, `PHYLO_JOB_THREADS`, `PHYLO_JOB_OOM_BASELINE`, thread-count variables (`OMP_NUM_THREADS`, …) | set per job by its method service |
