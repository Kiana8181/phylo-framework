# Deployment & Storage Operations

This project stores **uploaded datasets** and **generated run artifacts** in a
self-hosted, S3-compatible object store (**MinIO**) — not in the repository or
on the API's local disk, and never as base64 inside the database. PostgreSQL
holds relational metadata together with run parameters, result summaries,
normalized trees, mappings and annotations. No AWS or paid cloud storage is
required.

The storage layer is S3-compatible, so a real S3 endpoint can be used later by
changing environment variables only — but the default and documented path is
self-hosted MinIO via Docker Compose.

---

## Architecture summary

- **Datasets** → MinIO bucket `S3_BUCKET_DATASETS` (key: `datasets/{user_id}/{upload_id}.{ext}`)
- **Artifacts** → MinIO bucket `S3_BUCKET_ARTIFACTS` (key: `artifacts/{run_id}/{artifact_id}/{filename}`)
- **Postgres** → users, file/run/artifact metadata,
  parameters, result JSON, normalized trees, mappings and annotations
- **Shared staging volume** (`/runtime/storage`) → where the worker stages a
  dataset for a method service to read, and where method services write outputs.
  The worker uploads those outputs to MinIO; this volume is scratch space, not
  the system of record.
- **Downloads/previews** are streamed **through the API** (`/artifacts/{id}/download`,
  `/artifacts/{id}/preview`, `/datasets/{id}/download`). MinIO is **not** exposed
  to browsers; the API enforces per-request authorization and streams bytes.

---

## Required environment variables

Copy `.env.example` to `.env` and set real secrets. Storage-related variables:

| Variable | Purpose | Example |
|---|---|---|
| `STORAGE_BACKEND` | `minio` (default), `s3`, or `local` (tests only) | `minio` |
| `MINIO_ROOT_USER` | MinIO root user (also used as S3 access key) | `phylo_minio` |
| `MINIO_ROOT_PASSWORD` | MinIO root password (also used as S3 secret) | `change-me-strong` |
| `S3_ENDPOINT_URL` | S3 endpoint for **host-run** scripts | `http://localhost:9000` |
| `S3_ENDPOINT_URL_DOCKER` | S3 endpoint **inside** containers | `http://minio:9000` |
| `S3_REGION` | Region label (any value for MinIO) | `us-east-1` |
| `S3_ACCESS_KEY_ID` | S3 access key | `phylo_minio` |
| `S3_SECRET_ACCESS_KEY` | S3 secret key | `change-me-strong` |
| `S3_BUCKET_DATASETS` | Dataset bucket name | `phylo-datasets` |
| `S3_BUCKET_ARTIFACTS` | Artifact bucket name | `phylo-artifacts` |
| `S3_FORCE_PATH_STYLE` | Path-style addressing (required for MinIO) | `true` |
| `PUBLIC_API_BASE_URL` | Public base URL of the API | `https://phylo.example.org` |

> The compose file injects `S3_ENDPOINT_URL` inside containers from
> `S3_ENDPOINT_URL_DOCKER` so a host-oriented `.env` value (localhost) never
> leaks into the cluster. Keep `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` in
> sync with `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` (or create a dedicated
> MinIO user/policy for least privilege).

---

## Required production secrets

`.env.example` ships public development values. A production deployment refuses
to start until they are replaced:

| Variable | Requirement |
|---|---|
| `POSTGRES_PASSWORD` | Not a value from `.env.example`; the same password must appear in `DATABASE_URL` if you set that yourself |
| `MINIO_ROOT_PASSWORD` | Not a value from `.env.example` |
| `S3_SECRET_ACCESS_KEY` | Must match `MINIO_ROOT_PASSWORD` (or belong to your own MinIO user) |
| `MINIO_METHODS_PASSWORD` | Not a value from `.env.example` |
| `JWT_SECRET_KEY` | Unique, random, at least 32 characters |

Generate each one with `openssl rand -hex 32`.

Two layers enforce this:

1. **Docker Compose** stops with `required variable X is missing a value` when
   `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `MINIO_ROOT_USER`,
   `MINIO_ROOT_PASSWORD`, `MINIO_METHODS_USER`, `MINIO_METHODS_PASSWORD` or
   `JWT_SECRET_KEY` is unset. There are no built-in fallback credentials.
2. **The API and the worker** run with `ENV=production` (set by
   `docker-compose.yml` for `api-prod` and `api-worker-prod`) and exit at
   start-up when a secret is missing, equal to a known default, or too short.
   The message lists the variable names, never their values:

   ```bash
   docker compose --profile prod logs api-prod api-worker-prod | grep -A8 "Refusing to start"
   ```

In production, error responses carry a fixed message and an `error_id`; the
cause is in the container log under the same id. The interactive API docs
(`/docs`, `/redoc`, `/openapi.json`) are off unless `API_DOCS_ENABLED=true`.

---

## Resource budget and container limits

The server is shared, so the whole stack runs inside **one budget** that you set
in `.env`:

| Variable | Meaning | Default |
|---|---|---|
| `PHYLO_CPU_BUDGET` | CPU cores for all containers together | `4` |
| `PHYLO_MEMORY_BUDGET_MB` | RAM in MiB for all containers together | `8192` |
| `PHYLO_PIDS_BUDGET` | Processes + threads for all containers together | `4096` |
| `PHYLO_RESOURCE_MODE` | `strict` or `pooled` (see below) | `strict` |
| `PHYLO_CGROUP_PARENT` | Optional host cgroup that enforces the total | unset |

The defaults are placeholders, not a recommendation for any server. Set them to
the share the infrastructure team gives this deployment.

```bash
sh scripts/resource-plan.sh            # show the plan for the budget in .env
sh scripts/resource-plan.sh --write    # store it in .env (managed block)
docker compose --profile prod up -d    # recreate containers with the new limits
sh scripts/resource-plan.sh --check    # verify .env still matches the budget
```

`./run.sh` (production mode) runs `--write` for you. If you start the stack with
`docker compose` directly and never run the script, the compose file applies the
plan for the default budget.

### How the budget is split

Docker Compose has no shared, elastic pool: each container gets its own cap,
fixed when it starts. The script therefore gives every container a measured
minimum plus a weighted part of what is left:

- Each R service (Dowser, BrepPhylo) idles near 800 MiB and needs about 1.7 GiB
  for one small job, so its minimum is 2048 MiB.
- GCtree's minimum is 512 MiB, ClonalTree's 384 MiB.
- Postgres, MinIO, the API, the worker and the web server together need about
  1.3 GiB.

That makes the smallest usable budget **2.05 CPU, 6592 MiB, 2432 PIDs**. Below
it the script stops with an error instead of producing limits that cannot work.

Plan for the default budget:

| Container | CPUs | Memory | PIDs |
|---|---|---|---|
| postgres | 0.36 | 389 MiB | 384 |
| minio | 0.30 | 450 MiB | 384 |
| minio-init (runs once) | 0.10 | 256 MiB | 64 |
| api | 0.48 | 322 MiB | 256 |
| worker | 0.15 | 225 MiB | 192 |
| web | 0.15 | 289 MiB | 256 |
| dowser | 0.60 | 2448 MiB | 512 |
| brepphylo | 0.60 | 2448 MiB | 512 |
| gctree | 0.60 | 778 MiB | 768 |
| clonaltree | 0.60 | 584 MiB | 768 |
| **total** | **3.94** | **8189 MiB** | **4096** |

### `strict` and `pooled`

- **strict** (default): the caps add up to at most the budget. The stack cannot
  exceed it even when every container is busy at the same moment. The price is
  that each method service only ever gets its own slice of the CPU (0.60 cores
  each in the table above), even while the other three are idle.
- **pooled**: every method service may use the whole method share of the CPU
  (2.40 cores in the example). The CPU caps then add up to more than the budget,
  so this mode is only safe when something else enforces the total: set
  `PHYLO_CGROUP_PARENT` to a host cgroup that the infrastructure team limits.
  Memory and process limits stay strictly split in both modes.

A host parent cgroup is the only way to get a true shared pool. On a host that
uses systemd it is a slice, for example `/etc/systemd/system/phylo.slice`:

```ini
[Slice]
CPUQuota=400%
MemoryMax=8G
MemorySwapMax=0
TasksMax=4096
```

followed by `systemctl daemon-reload` and `PHYLO_CGROUP_PARENT=phylo.slice` in
`.env`. This needs root on the host and was **not tested here** (the
development machine does not run systemd); only the hand-over of the setting to
Docker was verified. Without it, use `strict`.

### What happens at the limits

- **CPU:** a container that wants more than its cap is slowed down, never
  killed. Jobs take longer; nothing fails.
- **Memory:** a limit is a hard ceiling and swap is disabled per container, so
  the limit is real. A process that exceeds it is killed by the kernel. If that
  was a job's own process, only that job is lost; if it was the service's main
  process, the container restarts automatically. Memory does **not** degrade
  gracefully: nothing slows down, something is killed. The protection is not
  starting a job that will not fit (next section).
- **Processes:** new processes are refused at the limit; the service keeps
  running and recovers when the extra processes end.

Measured on a throwaway copy of the production profile with the default
budget: four busy processes in GCtree used 0.60 cores; a process asking for
1.5 GiB in GCtree (limit 778 MiB) was killed while the container, the API and
the other methods stayed up; ClonalTree could not go beyond 768 processes; one
real run per method completed with no out-of-memory kill.

## Job execution inside the budget

Limits on a container say how much it may use. This section is about what runs
inside: how many jobs at once, how many threads each, and what happens to a job
that does not fit.

### Job slots and threads per job

Each method service reads its **own effective limits** when it starts (the
container's CPU quota and memory limit, never the host's core count) and derives:

- **job slots** = whole CPUs of the container, but no more jobs than its memory
  can hold: `idle service + N × job estimate ≤ limit − headroom`;
- **threads per job** = whole CPUs ÷ job slots, at least 1.

So `jobs × threads` never exceeds the container's CPUs. `GET /capacity` on a
method service shows the result. With the default strict plan every method
runs one job at a time with one thread.

| Setting (all optional) | Meaning |
|---|---|
| `PHYLO_<METHOD>_MAX_JOBS` | Jobs at once (memory still caps it). Set `1` on a container with several CPUs to give one job all of them |
| `PHYLO_<METHOD>_THREADS_PER_JOB` | CPU budget of one job; cannot exceed the container's CPUs |
| `PHYLO_<METHOD>_JOB_MEMORY_MB` | Estimated peak memory of one job |
| `PHYLO_MEMORY_HEADROOM_PERCENT` | Share of each method's memory limit kept free (default 10) |
| `WORKER_MAX_CONCURRENT_RUNS` | Runs the worker drives at once; unset = sum of all job slots |

`<METHOD>` is `DOWSER`, `BREPPHYLO`, `GCTREE` or `CLONALTREE`.

The memory estimates are **measured on the sample dataset** (Dowser and
BrepPhylo: 850 MiB idle + 950 MiB per job; GCtree 160 + 256; ClonalTree
60 + 192). A much larger dataset needs more. If your users run large datasets,
raise `PHYLO_<METHOD>_JOB_MEMORY_MB`; an estimate that is too low lets jobs start
that then collide. The estimate is the one number here that cannot be derived
automatically.

### Waiting instead of oversubscribing

The worker asks each method service for its capacity and only dispatches a run
when that method has a free slot. Otherwise the run stays `QUEUED`, with stage
`WAITING_FOR_CAPACITY` and a message such as
"Waiting for a free dowser slot (1 of 1 in use)". It keeps its place in the
queue. A full method does not block runs for other methods.

A method service also refuses a job when a slot is free but the job's memory
does not fit (it counts measured use and the estimates of jobs that have just
started). The run then waits with "Not enough free memory for another … job".

Two cases are not a wait:

- The container can never hold even one job (limit smaller than idle service +
  one job). The run fails at once with that explanation and the setting to
  change, instead of waiting forever.
- The method service is unreachable. Its runs wait with "service is not
  reachable right now" and start when it is back.

There is no limit yet on how long a run may wait; that comes with job timeouts.

### Parallelism inside each method

What each method does with CPU cores, and how it is kept inside the job's
thread budget `T`:

| Method | Where it parallelises | Control |
|---|---|---|
| **Dowser** | User parameter `nproc`: one forked R process per clone (`mclapply`), and IgPhyML's `--threads`. RAxML-NG is always called with `--threads 1` | `nproc` is reduced to `T` on the server. The result records "requested" and "effective" and carries a warning when it was reduced. BLAS/OpenMP are held at 1 thread so processes × threads cannot multiply |
| **BrepPhylo** | Sequential by design: clones one after another, IgPhyML with `--threads 1`, `dnapars` single-threaded | BLAS/OpenMP held at 1 thread; `OMP_THREAD_LIMIT = T` as a ceiling |
| **GCtree** | No process pool. NumPy/SciPy linear algebra (OpenBLAS) started one thread per host core | BLAS/OpenMP thread variables set to `T` |
| **ClonalTree** | A `multiprocessing` pool sized by `cpu_count()` (the host's cores) and MUSCLE, which also started one thread per host core | `cpu_count()` reports `T` to the pipeline (through `sitecustomize.py`, without changing the pinned pipeline code); MUSCLE follows `OMP_NUM_THREADS = T`; BLAS held at 1 thread inside pool workers |

`OMP_THREAD_LIMIT = T` is set for every job as a hard ceiling, including for
programs that ask for a thread count explicitly.

**Effect on results.** Thread counts change speed, not output, in every case
that was checked: all four methods produced identical trees on the regression
dataset before and after; MUSCLE's alignment is byte-identical for 1, 2, 4 and
8 threads; the ClonalTree pool returns results in input order whatever its
size. One caveat for Dowser: with `nproc` above 1 its per-clone random streams
depend on the number of workers, so a run whose `nproc` was reduced is
reproducible with the *effective* value, which is why that value is recorded.

Measured with one job each and no container limit: GCtree used 2.35 cores and
51 processes/threads before, 1.01 and 23 after; ClonalTree 2.06 and 15 before,
0.96 and 7 after. In a 4-CPU container MUSCLE ran faster with 4 threads (7.3 s)
than with its default of 8 (9.1 s).

Measured on a throwaway copy of the production profile, Dowser limited to
2 CPUs and one slot: three users submitted Dowser runs with `nproc=64` at the
same moment. Each ran with 2 workers (never 64), one at a time, the other two
waiting with the message above; CPU peaked at 1.85 of 2.00 cores; GCtree and
ClonalTree runs submitted at the same moment were not held up; no
out-of-memory kill.

## Restarts and logs

Every long-running container has `restart: unless-stopped`: it comes back after
a crash, an out-of-memory kill or a host reboot, but not after you stop it
yourself. `minio-init` runs once and is never restarted. Measured recovery after
killing the main process: API healthy again in about 5 seconds, worker and
Python method services in about 2 seconds, Dowser serving again in about 12.

A production container that refuses to start because of weak secrets (see
above) will be restarted repeatedly; `docker compose ps` shows `Restarting` and
the log repeats the reason.

Container logs are rotated: `PHYLO_LOG_MAX_SIZE` (default `10m`) per file,
`PHYLO_LOG_MAX_FILES` (default `5`) files per container.

---

## Network layout and secret isolation

| Network | Type | Members |
|---|---|---|
| `phylo_db` | internal, no internet | Postgres, API, worker |
| `phylo_internal` | internal, no internet | MinIO, the four method services, API, worker |
| `phylo_egress` | outbound allowed | API, worker |
| `proxy_net` | external, owned by the infrastructure team | API, web |

- The method services parse uploaded files. They have no route to the internet,
  cannot open a connection to the database, hold no Linux capabilities, and
  receive only the write-only object-store user (it can add artifacts and
  nothing else).
- The web container is only on `proxy_net` and holds no secret.
- Only the API and the worker read `.env`. Postgres and MinIO get just their own
  credentials.
- Internal addresses use names unique to this project (`phylo-postgres`,
  `phylo-minio`, `phylo-dowser`, …) so they cannot resolve to another project's
  container on the shared proxy network.

The container names on `proxy_net` (`phylo-web-prod`, `phylo-api-prod`) and their
ports (3000, 8000) are unchanged, so the reverse-proxy configuration does not
need to change.

**Upgrading an existing server:** set these in the server's `.env`, because old
values still point at the short names:

```
S3_ENDPOINT_URL_DOCKER=http://phylo-minio:9000
METHOD_DOWSER_URL_DOCKER=http://phylo-dowser:8001
METHOD_GCTREE_URL_DOCKER=http://phylo-gctree:8002
METHOD_BREPPHYLO_URL_DOCKER=http://phylo-brepphylo:8003
METHOD_CLONALTREE_URL_DOCKER=http://phylo-clonaltree:8004
```

(`./run.sh` rewrites the four `METHOD_*` lines for you.) The old names keep
working, so nothing breaks if you forget; they are just not unique.

---

## Local development

```bash
cp .env.example .env            # the example values are fine for local development
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev up -d --build
# The `api` service runs `alembic upgrade head` on start.
# The `minio-init` service creates both buckets automatically.
npm run storage:check:docker    # verifies connectivity + buckets
```

`docker-compose.yml` publishes no host ports for Postgres or MinIO.
`docker-compose.dev.yml` adds them for local development (the `./run.sh` dev
modes pass both files for you). Never load the dev file on the server.

A full clean-slate reset (wipes DB + MinIO + staging, recreates buckets):

```bash
bash ./scripts/reset-local.sh
```

---

## Server / production deployment

The `prod` compose profile includes `postgres`, `minio`, `minio-init`,
`api-prod`, `api-worker-prod`, `web-prod`, and the four method services.

```bash
# On your server:
cp .env.example .env            # then replace every secret listed under "Required production secrets"
docker compose --profile prod build --pull          # --pull picks up patched base images
docker compose --profile prod up -d
docker compose exec api-prod alembic upgrade head   # (also runs automatically on start)
npm run storage:check:docker
```

### Object store image

The object store is **Silo** (`pgsty/silo`), the maintained community fork of
MinIO; upstream MinIO no longer publishes images. It uses the same settings
(`MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, …), the same client commands and the
same on-disk format, so the compose service is still called `minio` and nothing
else in the configuration changes. Both images are pinned by digest in
`docker-compose.yml`. Background and test evidence:
[OBJECT-STORAGE-OPTIONS.md](./OBJECT-STORAGE-OPTIONS.md).

**Upgrading a server that ran MinIO:** no data migration. Take a backup (next
section), then start the stack as usual; Silo opens the existing
`phylo_minio_data` volume. Buckets, objects, the methods user and its policy
carry over. This was tested on throwaway volumes with data written by the old
MinIO image, and going back to the old image afterwards also worked.

**Deployment prerequisite — mirror the two images.** They are currently pulled
from the fork's Docker Hub repository. If that repository ever disappears, as
MinIO's did, a fresh host cannot start the stack. Copy both images, by digest,
into a registry the group controls and point the deployment at the copy:

```bash
# Run once, logged in to your registry. Copying by digest keeps the digest, so
# the mirror provably serves the same images.
docker buildx imagetools create --tag registry.example.org/phylo/silo:RELEASE.2026-09-16 \
  pgsty/silo@sha256:32a8a777d90f3296294c9a57da5e8d397121187c4b868b2a7fc7874c726c0291
docker buildx imagetools create --tag registry.example.org/phylo/mc:RELEASE.2026-09-16 \
  pgsty/mc@sha256:cfc83108c3abb371f8fb84d99c1fdc88f8c237e022409b0081fb7c0a3be634dd
```

then in `.env`:

```
PHYLO_OBJECT_STORE_IMAGE=registry.example.org/phylo/silo@sha256:32a8a777d90f3296294c9a57da5e8d397121187c4b868b2a7fc7874c726c0291
PHYLO_OBJECT_STORE_CLIENT_IMAGE=registry.example.org/phylo/mc@sha256:cfc83108c3abb371f8fb84d99c1fdc88f8c237e022409b0081fb7c0a3be634dd
```

This has **not** been done: no group registry was available when the images
were adopted. Until it is, the deployment depends on Docker Hub for these two
images.

Hardening notes:

- **Do not publish the MinIO API port publicly.** Only the API/worker need it on
  the internal Docker network. Remove/restrict the `minio` `ports:` mapping in
  production (or bind to `127.0.0.1`), and front the web/API with your reverse
  proxy + TLS. Downloads/previews flow through the API, so MinIO never needs to
  be browser-reachable.
- The MinIO **console** (`:9001`) is for ops only — restrict or keep it internal.
- Use a dedicated MinIO access key with a policy scoped to the two buckets
  instead of the root credentials, if you need least privilege.
- Persist `phylo_minio_data` on reliable storage (named volume by default; a host bind
  mount under your data directory is fine).

### Persistent volumes

| Volume | Holds |
|---|---|
| `phylo_postgres_data` | PostgreSQL data |
| `phylo_minio_data` | All datasets + artifacts |
| `method_jobs` | Per-job scratch/state (ephemeral; safe to lose) |

---

## Backup & restore

Back up the database and object storage **together** for a consistent snapshot
(runs reference artifact objects by key).

Create a restricted backup directory first. Database and object snapshots must
come from the same maintenance window.

**Database:**
```bash
mkdir -p backups/minio
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/backup_db.sql
# restore:
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"' < backups/backup_db.sql
```

**Object storage:** mirror both buckets with the `mc` client. The object store
publishes no host port, so the client container joins the store's internal
network:

```bash
set -a; . ./.env; set +a
NET=$(docker inspect phylo-minio --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}')
MC=pgsty/mc@sha256:cfc83108c3abb371f8fb84d99c1fdc88f8c237e022409b0081fb7c0a3be634dd
for bucket in "$S3_BUCKET_DATASETS" "$S3_BUCKET_ARTIFACTS"; do
  docker run --rm --network "$NET" -v "$PWD/backups/minio:/backup" \
    -e MC_HOST_store="http://$MINIO_ROOT_USER:$MINIO_ROOT_PASSWORD@phylo-minio:9000" \
    "$MC" mirror --overwrite "store/$bucket" "/backup/$bucket"
done
# restore = mirror the backup directory back into the bucket.
```

Alternatively snapshot the `phylo_minio_data` volume while the stack is stopped.
These commands do not capture copies already downloaded by users or versions
retained by an externally configured versioned object store. Backups are a
manual step; nothing in this project schedules them.

---

## Post-deploy checks

```bash
docker compose ps                        # all services up; minio-init exited 0
npm run storage:check:docker             # upload/exists/download/stream/delete round-trip on both buckets
curl -fsS "$PUBLIC_API_BASE_URL/health"  # API health
```

Then run one method end-to-end and confirm:
- the dataset appears in `phylo-datasets` (not in the repo/DB),
- artifacts appear in `phylo-artifacts`,
- `GET /runs/{id}/result` contains **no** base64 / `data:` URLs,
- image previews load via `/artifacts/{id}/preview`,
- the ZIP downloads via `/artifacts/{id}/download`.

---

## Optional future migration of legacy base64 data

This implementation is clean-slate (the dev DB/volumes are wiped). If a legacy
production database with base64 in `runs.result` / `run_trees.service_image`
ever needs migrating, write a one-off idempotent script that: detects base64
artifacts, decodes them, uploads to the artifact bucket, inserts `run_artifacts`
rows, and rewrites `result` to drop base64 and reference artifacts — with a
`--dry-run` mode, per-record logging, a pre-migration backup, and a documented
rollback (restore the backup). The new system is **not** designed around
preserving old base64 data.
