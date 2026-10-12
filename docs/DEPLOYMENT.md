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

## Server / production deployment (self-hosted MinIO)

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

> **MinIO images:** `minio/minio` and `minio/mc` can no longer be pulled from
> Docker Hub. A server that already has them cached keeps working; a fresh host
> cannot download them. Do not prune images on the server (`docker image prune -a`,
> `docker system prune -a`) until a replacement is decided. See finding 1 in
> [SECURITY-AUDIT.md](./SECURITY-AUDIT.md).

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

**MinIO (object storage):** mirror both buckets with the `mc` client:
```bash
docker run --rm --network=host -v "$PWD/backups/minio:/backup" -e MC_HOST_local="http://$S3_ACCESS_KEY_ID:$S3_SECRET_ACCESS_KEY@localhost:9000" \
  minio/mc mirror --overwrite local/phylo-datasets  /backup/phylo-datasets
docker run --rm --network=host -v "$PWD/backups/minio:/backup" -e MC_HOST_local="http://$S3_ACCESS_KEY_ID:$S3_SECRET_ACCESS_KEY@localhost:9000" \
  minio/mc mirror --overwrite local/phylo-artifacts /backup/phylo-artifacts
# restore = mirror the backup directory back into the bucket.
```
Alternatively snapshot the `phylo_minio_data` volume while the stack is stopped.
These commands do not capture copies already downloaded by users or versions
retained by an externally configured versioned object store.

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
