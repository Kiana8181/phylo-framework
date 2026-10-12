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
  was a job's own process, only that job is lost and its run ends as
  `ERROR [OUT_OF_MEMORY]`; if it was the service's main process, the container
  restarts automatically and the run ends as `ERROR [METHOD_RESTARTED]`. Memory
  does **not** degrade gracefully: nothing slows down, something is killed. The
  protection is not starting a job that will not fit (next section); what
  happens when one is killed anyway is described under
  [When a run cannot finish](#when-a-run-cannot-finish).
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

Waiting is bounded: a run that has been ready to start for longer than
`RUN_QUEUE_WAIT_TIMEOUT_SECONDS` (default 48 hours) ends as
`ERROR [QUEUE_TIMEOUT]` without having executed, and says so.

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

## Limits on creating runs

Three limits apply to each user. They are read by the API from `.env`; a
restart applies a change.

| Setting | Default | Limits |
|---|---|---|
| `MAX_RUNS_PER_USER_PER_HOUR` | `5` | Runs in any rolling 60 minutes. `0` = no limit |
| `MAX_QUEUED_RUNS_PER_USER` | `5` | Runs waiting behind the user's active run |
| `MAX_RUN_SUBMISSIONS_PER_USER_PER_HOUR` | `30` | Every run created in 60 minutes, whatever became of it. `0` = no ceiling |

**What counts against the hourly limit.** Every run the user created in the
last 60 minutes, whether it is waiting, running, finished or failed — except
runs whose analysis never started:

- a run cancelled while it was still queued, or after a worker picked it up but
  before anything was submitted to the method service;
- a run that expired in the queue (`QUEUE_TIMEOUT`).

A run cancelled after its analysis started counts. So does a run that failed
while its input was being prepared: work was done for it.

The window is rolling, not a clock hour: the sixth run becomes possible exactly
60 minutes after the first of the five was created.

**Why there is a third limit.** Runs that never start are free. Without a
ceiling, submitting and cancelling in a loop would be free too. The submission
ceiling counts every created run and cannot be earned back by cancelling. The
queue limit is separate again: it counts runs that have not finished, so
neither cancelling nor a queue timeout lets a user hold more than
`1 + MAX_QUEUED_RUNS_PER_USER` unfinished runs.

**What the user sees.** The run wizard shows "3 of 5 runs used this hour".
When a limit is reached the Run and Add run buttons are disabled and a notice
gives the reason and a countdown to the next possible run. The server remains
the judge: the wizard asks again just before uploading a file, and the API
refuses a run that is over a limit whatever the page shows.

**API.**

- `GET /runs/quota` returns the user's standing: `can_submit`, `blocked_by`,
  `message`, `retry_after_seconds`, and `limit` / `used` / `remaining` /
  `reset_at` for the hourly limit and the submission ceiling, plus the queue.
- `POST /runs` answers `429` with code `RUN_QUOTA_EXCEEDED` or
  `RUN_SUBMISSION_LIMIT_EXCEEDED`, a `Retry-After` header and `reset_at` in the
  body; a full queue is `409 QUEUE_FULL`, as before.

Two requests of the same user arriving at the same moment cannot both take the
last allowance: limit check and run creation happen as one step per user
(a PostgreSQL advisory lock held for that transaction). Different users do not
wait for each other.

Measured: ten simultaneous requests for a user's last allowance admitted
exactly one; twelve simultaneous requests against a queue limit of two admitted
exactly three (one active, two queued).

## When a run cannot finish

Every run ends. It ends as `DONE` only when its result is complete and stored;
otherwise it ends as `ERROR` with a code and a message written for the user, or
as `CANCELLED`. No run holds a slot, or waits for one, without limit.

| What happens | Run ends as | Notes |
|---|---|---|
| The analysis runs longer than the limit | `ERROR [TIMEOUT]` | The job and every program it started are stopped; the slot is free again |
| The run waits too long for a free slot | `ERROR [QUEUE_TIMEOUT]` | Nothing was executed |
| A job is killed for lack of memory | `ERROR [OUT_OF_MEMORY]` | The message tells the user to try a smaller dataset or ask for a higher limit |
| A job's process dies for another reason | `ERROR [JOB_PROCESS_LOST]` | |
| The method container restarts or is redeployed during a run | `ERROR [METHOD_RESTARTED]` | Only the runs that were in progress there; never re-run automatically |
| The method service stays unreachable during a run | `ERROR [METHOD_UNREACHABLE]` | After `WORKER_METHOD_UNREACHABLE_SECONDS` (default 5 minutes) |
| Result files could not be uploaded | `ERROR [ARTIFACT_UPLOAD_FAILED]` | Reported by the method service |
| Result files are not in storage as declared | `ERROR [ARTIFACTS_MISSING]` | Found by the worker's own check |
| The method reports success without a tree or without its result bundle | `ERROR [INCOMPLETE_RESULT]` | Per-method success criteria, see below |
| Storage cannot be asked at completion | `ERROR [ARTIFACT_STORE_UNAVAILABLE]` | After `ARTIFACT_VERIFY_ATTEMPTS` tries |
| A finished result cannot be fetched from the method service | `ERROR [RESULT_UNAVAILABLE]` | |
| The user cancels | `CANCELLED` | Also when the method service is down or does not confirm |

A failed run is not repeated automatically: the user decides whether to submit
it again. After a failure the user's next queued run moves up as usual.

### Time limits

| Setting | Default | Meaning |
|---|---|---|
| `RUN_TIMEOUT_SECONDS` | `86400` (24 h) | Longest a run may execute, counted from the moment it started. `0` = no limit |
| `RUN_TIMEOUT_SECONDS_<METHOD>` | unset | The same for one method (`DOWSER`, `BREPPHYLO`, `GCTREE`, `CLONALTREE`) |
| `RUN_QUEUE_WAIT_TIMEOUT_SECONDS` | `172800` (48 h) | Longest a run that is ready to start may wait for a slot. `0` = no limit |
| `WORKER_METHOD_UNREACHABLE_SECONDS` | `300` | How long a method service may be unreachable while one of its jobs is followed |
| `WORKER_CANCEL_CONFIRM_SECONDS` | `60` | How long the worker waits for a stop (cancel or timeout) to be confirmed |

These are read by the worker from `.env`. Choose `RUN_TIMEOUT_SECONDS` for your
largest legitimate analysis: a limit that is too low stops real work. The
default is generous on purpose.

The time limit is enforced twice. The worker stops a run that passes its limit.
Independently, each method service stops the job itself shortly after the same
moment (the worker hands it the remaining time when it submits the job), so the
limit holds even while the worker is down. The start time is stored with the
run, so a worker restart does not reset the clock.

A worker restart does not lose runs either: the new worker takes over the runs
in progress and keeps following their jobs. It does not submit them a second
time; a method service that receives the same run again while its job is
active returns that job.

### A result counts only when it is stored

Method services upload their result files to the object store themselves. A
run becomes `DONE` only after three independent checks:

1. the method service reports every file it could not upload, and every file
   it declared but did not produce; a job with such a file ends as a failure,
   not as a success;
2. the worker checks the result against the method's **success criteria**
   (below);
3. the worker asks the object store for every declared file and compares its
   size (and the SHA-256 the uploader recorded on the object) with what the
   method declared.

Then the run's status, its trees and its file list are saved in one database
transaction, so nothing can observe a `DONE` run whose files are not listed yet.

**Success criteria.** Checking declared files is not enough on its own: a
method that reports success but declares nothing would pass with an empty
list. Each method therefore states what a successful run always delivers, in
`packages/contracts/methods/<method>/completion.json`:

| Method | At least | Must include |
|---|---|---|
| GCtree, ClonalTree, Dowser, BrepPhylo | 1 tree | the result bundle (the downloadable archive, role `clone_bundle_zip`) |

A result that misses one of these ends as `ERROR [INCOMPLETE_RESULT]`. A method
added later without such a file still needs at least one tree and one output
file.

Deliberately **not** required, because methods legitimately finish without
them: rendered tree images (a method may build a tree it then fails to draw; it
says so in its warnings, and the tree is still shown from its Newick),
method-specific extras (GCtree's abundance charts, BrepPhylo's PDFs), and the
execution log. A run whose scientific output is complete and stored but whose
log could not be saved stays `DONE` and carries the warning
`EXECUTION_LOG_MISSING`.

If the object store is down when a job finishes, the run therefore ends as
`ERROR` and the user is asked to run it again. It is never shown as completed
with nothing to download.

### Measured

On the isolated test stack and on a throwaway copy of the production profile
(default resource plan, methods uploading with the write-only storage account):

- **Object store unreachable while a job runs**, each of the four methods: the
  run ended as `ERROR [ARTIFACT_UPLOAD_FAILED]` naming the files; once the store
  was back, the same user's next run completed with all its files.
- **Files not where the worker looks for them:** `ERROR [ARTIFACTS_MISSING]`.
- **Run limit shorter than the analysis** (Dowser, GCtree): `ERROR [TIMEOUT]`
  within a second of the limit, no job process left in the container, the slot
  free; a ClonalTree run without a short limit was unaffected.
- **Worker stopped right after submitting:** the method service stopped the job
  by itself at its deadline; when the worker returned, the run ended as
  `ERROR [TIMEOUT]`.
- **Dowser's service process killed during a run** (production profile, nobody
  intervening): the container restarted by its restart policy, the run ended
  as `ERROR [METHOD_RESTARTED]` 17 seconds later, the next run completed.
- **Method container recreated during a run:** `ERROR [METHOD_RESTARTED]`,
  nothing resubmitted. **Left down:** `ERROR [METHOD_UNREACHABLE]` after the
  allowed time, while a new run for that method waited and later completed.
- **Worker restarted during a run:** the run completed; exactly one job had
  been started for it.
- **A ClonalTree job that needed more memory than its container had**
  (limit lowered to 90 MiB for the test): the kernel killed the job, the run
  ended as `ERROR [OUT_OF_MEMORY]`, the container stayed up and accepted the
  next job. With the limit lowered further the kernel killed the service
  itself instead; that is the `METHOD_RESTARTED` case above.
- **Run waiting for a method that was down** with a 12-second waiting limit:
  `ERROR [QUEUE_TIMEOUT]` after 12 seconds, never started; the user's next run
  for another method completed.
- **User cancel** during a Dowser, BrepPhylo and GCtree job: `CANCELLED`, no job
  process left. (ClonalTree's sample job finishes before a cancel can land.)

What these tests do not cover: datasets larger than the samples, cgroup v1
hosts, and an out-of-memory kill inside the R services (their handling of it is
tested with a simulated kernel counter, not with a real kill).

## Email and run notifications

All email leaves through one SMTP server that you name in `.env`: password
reset, account emails, and run notifications. No third-party mail API is used.
The mail server and its credentials are provided by whoever runs it; nothing is
built in.

| Setting | Default | Meaning |
|---|---|---|
| `SMTP_HOST` | empty | Mail server. Empty switches email off |
| `SMTP_PORT` | by security | 587 (`starttls`), 465 (`ssl`), 25 (`none`) |
| `SMTP_SECURITY` | `starttls` | `starttls`, `ssl` or `none` |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | empty | Optional login; set both or neither |
| `SMTP_FROM` | none | Sender, e.g. `Phylo Runner <phylo@example.org>`. Required with `SMTP_HOST` |
| `SMTP_TIMEOUT_SECONDS` | `15` | Wait at each step of a delivery |
| `SMTP_TLS_VERIFY` | `true` | Verify the server's certificate |
| `SMTP_TLS_CA_FILE` | empty | CA bundle for a server with a private CA |
| `FRONTEND_URL` | `http://localhost:3000` | Address users open; used for the links in emails |

These reach only the API and the worker containers (through `.env`). The mail
password is sent only over TLS: a login with `SMTP_SECURITY=none` is refused as
a configuration error, and with `starttls` nothing is sent if the server does
not offer it. The password never appears in logs.

With `SMTP_HOST` empty, nothing is sent and nothing else changes. With an
invalid configuration (for example no `SMTP_FROM`) the API and the worker still
start; each logs one line at start-up saying that email cannot be sent and
which variable is wrong. On a server, set `FRONTEND_URL` to the public address,
or the links in emails will point to `localhost` (also reported at start-up).

### Run notifications

The owner of a run gets **one** email when the run ends by itself:

| Run ends as | Email |
|---|---|
| `DONE` | "Your … run has finished", with a link to the results |
| `ERROR` | "Your … run failed", with the code and reason shown in the app |
| Expired in the queue (`QUEUE_TIMEOUT`) | "Your … run expired before it could start": it waited too long for a free slot, never started, computed nothing, and should be submitted again |
| `CANCELLED` | none, however and whenever it was cancelled |

**Email can never change a run.** The need to send an email is recorded in the
database table `notification_outbox`, in the same transaction that gives the
run its final status. A separate task of the worker delivers from that table.
Run processing never waits for a mail server and never reads the result of a
delivery, so an outage, a timeout or a refusal only ever changes the outbox
row: a `DONE` run stays `DONE`.

**Retries are bounded.** A delivery that fails for a reason that may pass (server
unreachable, timeout, a temporary `4xx` answer, a rejected login) is tried
again later; one that the server refuses for good (`5xx`) is not.

| Setting | Default | Meaning |
|---|---|---|
| `RUN_NOTIFICATIONS_ENABLED` | `true` | `false` sends no run emails (password reset still works) |
| `NOTIFICATION_MAX_ATTEMPTS` | `6` | Attempts per email |
| `NOTIFICATION_RETRY_BASE_SECONDS` | `60` | Wait before the second attempt; each further wait is four times longer |
| `NOTIFICATION_RETRY_MAX_SECONDS` | `21600` | Longest wait between attempts |
| `NOTIFICATION_POLL_SECONDS` | `15` | How often the worker looks for emails to send |

With the defaults an email is attempted about 0, 1, 5, 21 and 85 minutes and
5.7 hours after the run ended, then given up. An email that could not be sent
is not sent later: a row ends as `SENT`, `FAILED` (given up, with the reason in
`last_error`) or `SKIPPED` (email was switched off when it came up).

**No duplicates.** There is at most one outbox row per run (a unique constraint
in the database), so repeated status writes, polling and worker restarts cannot
queue a second email. A row is held by one sender at a time, so two workers do
not send it twice. One case remains that SMTP cannot rule out: the mail server
accepted the message and the worker died in the instant before recording it;
that email is sent again when the row is next picked up.

To see what happened to a run's notification:

```sql
SELECT outcome, status, attempts, next_attempt_at, sent_at, last_error
FROM notification_outbox WHERE run_id = '<run id>';
```

Measured, with a local test mail server: each of `DONE`, `ERROR` and
`QUEUE_TIMEOUT` produced exactly one email with the wording above and
`CANCELLED` none (cancelled while queued, before submission, while running, and
while the method service was unreachable). With the mail server refusing
connections while a run finished, the run ended `DONE` with its trees, no email
was sent, and one email arrived after the server was back. With the server
answering "try again later" every time and three attempts allowed, delivery
stopped after the third and the run stayed `DONE`. With a mail server that
accepted connections and never answered, a complete run finished in under 1.5
seconds while the delivery task waited for its timeout. Three senders working
on six pending emails at once sent six emails. STARTTLS and implicit TLS were
exercised with a real handshake, including refusal of an untrusted
certificate.

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
