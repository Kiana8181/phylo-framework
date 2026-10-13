# Deployment guide

How to run Phylo-Framework on a server, and what it does there. To try it on
your own machine the [README](../README.md) is enough; every setting is listed
in [CONFIGURATION.md](./CONFIGURATION.md).

**Contents**

- [Architecture summary](#architecture-summary)
- [Required production secrets](#required-production-secrets)
- [Resource budget and container limits](#resource-budget-and-container-limits)
- [Job execution inside the budget](#job-execution-inside-the-budget)
- [Limits on creating runs](#limits-on-creating-runs)
- [When a run cannot finish](#when-a-run-cannot-finish)
- [Storage lifecycle and retention](#storage-lifecycle-and-retention)
- [Sign-in protection](#sign-in-protection)
- [Email and run notifications](#email-and-run-notifications)
- [Restarts and logs](#restarts-and-logs)
- [Network layout and secret isolation](#network-layout-and-secret-isolation)
- [Server / production deployment](#server--production-deployment): starting,
  checking, updating, version information, ports, the object store image
- [Backup & restore](#backup--restore)
- [Post-deploy checks](#post-deploy-checks)
- [Troubleshooting a deployment](#troubleshooting-a-deployment)

---

## Architecture summary

| Part | Role |
|---|---|
| Web (`web-prod`) | The pages. Holds no secret; reachable only through the reverse proxy |
| API (`api-prod`) | Accounts, uploads, runs, results. The only service a browser talks to; also reached through the reverse proxy |
| Worker (`api-worker-prod`) | Takes runs from the queue, prepares their input, follows their jobs, verifies and records results, sends notification emails, removes expired results |
| Method services (`dowser`, `gctree`, `brepphylo`, `clonaltree`) | Run the analyses, one job process per run. They parse uploaded files, so they have no internet access, no database access and no credentials beyond a write-only storage user |
| PostgreSQL (`postgres`) | Accounts, runs, trees, result summaries, the queue, the notification outbox |
| Object store (`minio`) | Uploaded datasets and result files, in two buckets. S3-compatible; the image is the Silo fork of MinIO |

- **Datasets** are stored as `datasets/{user}/{upload}.{ext}` in
  `S3_BUCKET_DATASETS`; **result files** as `artifacts/{run}/{job}/{file}` in
  `S3_BUCKET_ARTIFACTS`. Nothing binary is stored in the database.
- The worker **stages** a run's input in a scratch directory
  (`STORAGE_LOCAL_PATH`, mounted read-only into the method services). The
  method service uploads its result files to the object store itself and
  reports what it uploaded; the worker checks that every file is really there
  before the run becomes `DONE`.
- **Downloads and previews** are streamed through the API, which checks on
  every request that the file belongs to the user. The object store is never
  exposed to browsers.
- A real S3 service can replace the bundled store by changing the `S3_*`
  settings and `STORAGE_BACKEND`; the bundled store is the default and the
  tested path.

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

`./run.sh prod` runs `--write` for you. If you start the stack with
`docker compose` directly and never run the script, the compose file applies the
plan for the default budget; `./run.sh check` tells you when a budget is set in
`.env` but its limits are not stored.

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
  the limit is real. When a container reaches it, the kernel stops one of its
  processes. Memory does **not** degrade gracefully: nothing slows down,
  something is stopped. The protection is not starting a job that will not fit
  (next section).

  Which process is stopped matters. Left to itself the kernel takes the largest
  one, and while a job is still growing that is the method service itself: in a
  test with real jobs it stopped the service every time, the container
  restarted, and the run ended as `ERROR [METHOD_RESTARTED]` with every other
  job in that container. Each job therefore marks itself as the process to
  stop first (`PHYLO_JOB_OOM_SCORE_ADJ`, default `800`; `0` switches this off).
  With that, the job that needed too much is stopped, its run ends as
  `ERROR [OUT_OF_MEMORY]` with a message that says so and keeps a log, the
  service keeps running, and the next job is accepted. The same tests then gave
  this outcome every time, in both R services. See also
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
| Fetching and preparing the input takes too long | `ERROR [STAGING_TIMEOUT]` | The method was not started; the work directory is removed |
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
| `RUN_STAGING_TIMEOUT_SECONDS` | `1800` (30 min) | Longest the worker may take to fetch and prepare a run's input before the method starts. `0` = no limit |
| `WORKER_METHOD_UNREACHABLE_SECONDS` | `300` | How long a method service may be unreachable while one of its jobs is followed |
| `WORKER_CANCEL_CONFIRM_SECONDS` | `60` | How long the worker waits for a stop (cancel or timeout) to be confirmed |
| `WORKER_DATABASE_UNAVAILABLE_SECONDS` | `90` | How long the worker waits for the database while it follows a job (see below) |

These are read by the worker from `.env`. Choose `RUN_TIMEOUT_SECONDS` for your
largest legitimate analysis: a limit that is too low stops real work. The
default is generous on purpose.

The time limit is enforced twice. The worker stops a run that passes its limit.
Independently, each method service stops the job itself shortly after the same
moment (the worker hands it the remaining time when it submits the job), so the
limit holds even while the worker is down. The start time is stored with the
run, so a worker restart does not reset the clock.

**A database that is briefly away does not cost a run.** A job needs no
database; only the worker does, to record progress and the result. If
PostgreSQL restarts or is unreachable while a job runs, the worker leaves the
job alone, waits (`WORKER_DATABASE_UNAVAILABLE_SECONDS`, at most half the run
lease) and carries on when the database answers again. If it stays away longer,
the run is neither failed nor cleaned up: it is left exactly as it is, and
picked up again once the database is back, like a run after a worker restart.
The API answers with errors while the database is away and recovers by itself.

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

## Storage lifecycle and retention

Nothing here grows without limit: results expire, unfinished uploads are
cleaned up, method containers keep nothing of a finished job, and one upload
has a maximum size. **This section describes automatic, permanent deletion of
user data. Read it before changing `RESULT_RETENTION_DAYS`.**

### What is kept and for how long

| What | Kept | Removed by |
|---|---|---|
| A run's result files (bundle, trees, images, tables, log) in the object store | `RESULT_RETENTION_DAYS` after the run ended (default 60) | The worker's retention task |
| A run's trees, stored result and logs in the database | The same date | The same task, after the files are gone |
| The run itself: method, parameters, dataset name, status, message, times | For ever, marked "results expired" | Never |
| Uploaded datasets | Until the owner deletes them (they count against the storage quota) | **Never automatically** |
| Uploads that were started and never finished | `UPLOAD_SESSION_GRACE_HOURS` (default 24) | The API's upload clean-up |
| A job's scratch data inside a method container | Until the job ends | The method service |
| A finished job's record and log inside a method container | Until the worker has collected the result; at most `PHYLO_JOB_RETENTION_HOURS` (default 24) | The worker, or the method service itself |
| The record of a run's notification email | With the run's results (a notification still waiting to be sent is left alone) | The retention task |

Runs of every final state get a date: `DONE`, `ERROR` and `CANCELLED`. A run
that is waiting or running has none and is never touched.

### Settings

| Setting | Default | Meaning |
|---|---|---|
| `RESULT_RETENTION_DAYS` | `60` | Days results are kept after a run ended. `0` = keep for ever (nothing is ever removed) |
| `MAX_UPLOAD_MB` | `500` | Largest single file a user may upload |
| `UPLOAD_SESSION_GRACE_HOURS` | `24` | Age after which an unfinished upload is cleaned up |
| `RETENTION_SWEEP_SECONDS` | `3600` | How often expired results and abandoned uploads are looked for |
| `PHYLO_JOB_LOG_MAX_MB` | `5` | Largest execution log kept for a run |
| `PHYLO_JOB_RETENTION_HOURS` | `24` | How long a method service keeps a finished job nobody collected |
| `RUN_STAGING_TIMEOUT_SECONDS` | `1800` | See [Time limits](#time-limits) |

The first four are read from `.env` by the API and the worker; the two
`PHYLO_JOB_*` values are passed to the method containers by compose. A value
that is not a number is ignored in favour of the default; it never switches
retention off by accident.

### How the date is set, and what changing the setting does

- The date is fixed at the moment a run ends (`runs.expires_at`) and does not
  move afterwards. Changing `RESULT_RETENTION_DAYS` applies to runs that end
  **after** the change. A date the user has already been shown is kept, in both
  directions: shortening the period deletes nothing earlier than promised.
- **Runs that had already ended when this version was first deployed** got
  their date counted from the day of that deployment (migration
  `016_result_retention`), not from the day they ended. No existing result is
  removed on upgrade day, however old it is. The migration reads
  `RESULT_RETENTION_DAYS` from the environment of the container that runs it;
  with `0` those runs get no date.
- Setting `RESULT_RETENTION_DAYS=0` stops all removal at once, including for
  runs whose date has passed but which have not been cleaned up yet.

### What the user sees

- On a finished run's page: "These results are kept until 2026-12-11 (60 days
  left)", highlighted during the last 7 days. The run history shows the same
  date, and the notification email for a finished run states it.
- After the date: the run is still in the history, marked "Results expired".
  Its page shows the method, the dataset name and the parameters (which can be
  reused for a new run) and says when the results were removed.
- The API answers `410 Gone` with `code: RESULT_EXPIRED` for the result, the
  trees and every file of such a run, and reports `expires_at`,
  `results_expired` and `results_expired_at` on the run. Expired runs are no
  longer offered for comparison with other runs.

### How removal works

The worker runs the retention task next to run processing (start-up log line:
`result retention: 60 days after a run ends`). For each run that has ended and
is past its date it

1. deletes everything under the run's prefix in the artifact bucket
   (`artifacts/<run id>/`), which also catches files a failed run uploaded
   without registering them;
2. only when that succeeded, marks the file records deleted, removes the trees
   and the stored result, and marks the run expired, in one transaction.

If the object store cannot be reached, nothing changes in the database and the
run is tried again at the next sweep. If the worker stops between the two
steps, the next sweep finds no files and completes the second step. The check
that a run has ended and is due is made again immediately before its files are
deleted. Running the task twice changes nothing.

**No backup is taken before deletion, and this project sets up no automatic
backups.** Removal is permanent. Whoever needs results for longer must download
them before the date, or the retention period must be chosen accordingly.

### Uploads

A file larger than `MAX_UPLOAD_MB` is refused with `413` and
`code: UPLOAD_TOO_LARGE`: at once when the browser announces the size, and
otherwise while the bytes arrive (the partial file is deleted). `GET
/uploads/limits` reports the limit and the user's remaining storage quota.

The reverse proxy in front of the application must accept request bodies at
least as large as `MAX_UPLOAD_MB` (for nginx: `client_max_body_size`), or
uploads fail at the proxy with an error the application cannot explain.

An upload that was started and not finished (closed tab, lost connection, API
restart) leaves a partial file in the API container's temporary directory.
These are removed once they are older than `UPLOAD_SESSION_GRACE_HOURS`.
Finished uploads are datasets and are not touched.

### Execution logs

Every run that failed has a log to download, including runs that were stopped
at their time limit or whose job was killed: when the job could not upload its
own log, the worker fetches it from the method service and stores it with the
run's files. A log longer than `PHYLO_JOB_LOG_MAX_MB` keeps its beginning and
its end, with a line in between saying how much was left out. Logs expire with
the run's other files. The one exception is a run whose method container was
replaced while it ran (a redeploy): the job's files, its log among them, were
inside that container and went with it.

### Method containers

Each job gets its own scratch directory, set as `TMPDIR` for the job and every
tool it starts. It is deleted when the job ends, however it ends (finished,
failed, timed out, cancelled, killed). Once the worker has taken a job's result
it tells the service to forget the job; a job the worker never collected is
forgotten after `PHYLO_JOB_RETENTION_HOURS`. A method container's disk use
therefore returns to its baseline between jobs.

## Sign-in protection

Four things protect the sign-in, sign-up and password-reset forms. All are on
by default and configured in `.env`. The API logs one line at start-up saying
which are active, and warns in production about any that are not.

### CAPTCHA (self-hosted proof of work)

Every submission of the three forms carries the answer to a small computing
task. The API hands out a signed challenge (`GET /auth/challenge`); the
visitor's browser searches for a number whose SHA-256 hash, together with the
challenge, starts with a set number of zero bits; the API checks the answer
with one hash computation and accepts each challenge once. No third-party
service is involved, nothing has to be reachable from the server or from the
visitor's network, and there is nothing to click.

| Setting | Default | Meaning |
|---|---|---|
| `CAPTCHA_ENABLED` | `true` | `false` switches the check off |
| `CAPTCHA_DIFFICULTY_BITS` | `18` | Work per submission; each bit doubles it |
| `CAPTCHA_TTL_SECONDS` | `300` | How long a challenge may be used |

Measured time to solve in a browser engine on a laptop: 16 bits about 30 ms,
18 bits about 90 ms, 20 bits about 0.4 s (medians; individual challenges vary
several-fold, and phones are several times slower).

**What it does and does not do.** It makes every attempt cost computing time:
nothing for a person, a real cost for a script making thousands of attempts.
It does not tell a person from a program, and an attacker with fast hardware
can pay the price. It is a cost multiplier in front of the rate limits below,
which are what actually bounds the number of attempts.

### Rate limits

Counted in PostgreSQL (no extra service), so they hold across API restarts.
Each is written `N/SECONDS`; `0` switches that one off.

| Setting | Default | Limits |
|---|---|---|
| `AUTH_LIMIT_LOGIN_IP` | `30/900` | Sign-in attempts per client address |
| `AUTH_LIMIT_LOGIN_ACCOUNT` | `10/900` | **Failed** sign-in attempts per account |
| `AUTH_LIMIT_REGISTER_IP` | `10/3600` | Registrations per client address |
| `AUTH_LIMIT_FORGOT_IP` | `10/3600` | Password-reset requests per client address |
| `AUTH_LIMIT_FORGOT_ACCOUNT` | `3/3600` | Password-reset emails per account |
| `AUTH_LIMIT_VERIFY_IP` | `10/3600` | Confirmation-email requests per client address |
| `AUTH_LIMIT_VERIFY_ACCOUNT` | `3/3600` | Confirmation emails per account |
| `AUTH_RATE_LIMITS_ENABLED` | `true` | Master switch |

A request over a limit gets `429` with `Retry-After`. Things to know:

- After ten failed sign-ins for an account, that account accepts no sign-in,
  right or wrong, until the 15-minute window ends. This stops password
  guessing; it also means someone can keep a known address locked out of
  sign-in by failing on purpose. Password reset is not affected by it.
- Account limits apply to any address typed in, whether or not it has an
  account, so they reveal nothing about which addresses are registered.
- Windows are aligned to the clock, so up to twice a limit can pass in a short
  time across a window boundary.
- A whole lab behind one public address shares the per-address limits; raise
  `AUTH_LIMIT_REGISTER_IP` before a course signs up together.
- The table stores keyed hashes, not addresses or email addresses.

### The visitor's address behind the reverse proxy

**Required for the per-address limits to work on a server.** Browsers reach the
API through the reverse proxy, so the API sees the proxy's address unless told
to trust what the proxy reports:

```
FORWARDED_ALLOW_IPS=<address or network of the reverse proxy>
```

for example the subnet of the Docker network the proxy shares with the API
(`docker network inspect proxy_net`). Only requests coming *from* that address
have their `X-Forwarded-For` header believed, and the proxy's own entry (the
last one) is the one used, so a visitor cannot pass off another address by
sending the header themselves. The proxy must set or append the header (nginx:
`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`).

Check it after deploying, from your own machine:

```bash
curl https://<your site's API>/auth/client-ip
```

It must show your public address. If it shows a private address such as
`172.18.0.3`, the setting is missing or wrong, and all visitors share one
per-address allowance (30 sign-in attempts per 15 minutes for everybody
together). The API warns about an unset value at start-up in production.

### Email verification

| Setting | Default | Meaning |
|---|---|---|
| `EMAIL_VERIFICATION` | `auto` | `auto`: required when `SMTP_HOST` is set. `required`: always. `off`: never |
| `EMAIL_VERIFICATION_EXPIRE_HOURS` | `24` | How long a confirmation link works |

With `auto` nothing changes until a mail server is configured; from then on:

- Signing up answers "if this address can be registered, we have sent a
  confirmation link to it" and does not sign in. The answer is the same whether
  or not the address already has an account; what really happened is told to
  the mailbox (a confirmation link, or "you already have an account").
- Opening the link confirms the address and signs in. A link works once.
- Until then the account can sign in and request a new link (a banner offers
  it), but cannot upload data or create runs (`403 EMAIL_NOT_VERIFIED`) and
  gets no run notifications.
- Accounts that existed before this version are treated as confirmed.
- Signing in with Google counts as confirmation, provided Google itself has
  verified the address; a Google account with an unverified address is refused.
- Using a password-reset link also confirms the address.

If someone registers an address that is not theirs and its real owner later
arrives, through Google or a password reset, the account passes to the owner:
the password that was set without proof stops working and every session made
with it ends.

While verification is not required (no mail server, or `off`), sign-up works as
before, and the sign-up form does reveal whether an address is registered.

### Other changes to authentication

- **Password reset and confirmation tokens are stored only as hashes.** Someone
  who can read the database cannot use what is there to reset a password.
  Reset links issued before the upgrade stop working; users request a new one.
- **A password reset ends every earlier session** of the account.
- **Google sign-in carries a `state` value** issued by this API and required
  back, so a sign-in that was not started here cannot be completed here.
- **Sign-in takes the same time** for an unknown address as for a wrong
  password, and email addresses are compared without regard to letter case.

Measured on the isolated test stack and in the test suite: a form submitted
without the check was refused (`CAPTCHA_REQUIRED`), and the same answer used
six times at once was accepted once. Twenty simultaneous failed sign-ins
against a limit of five let exactly five through. A sign-up for an existing
address returned the same response as one for a new address. An unconfirmed
account was refused uploads and runs and allowed them after opening its link;
its first link stopped working when a new one was requested. After a password
reset, the previous session and its refresh token were refused. With
`FORWARDED_ALLOW_IPS` set to the proxy's network, `/auth/client-ip` returned
the forwarded visitor address, including when the visitor sent a forged header
of their own; without it, the proxy's address.

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
ports (3000, 8000) are unchanged by default, so the reverse-proxy configuration
does not need to change. The ports are configurable; see
[Internal ports](#internal-ports) before changing them.

**Upgrading an existing server:** set these in the server's `.env`, because old
values still point at the short names:

```
S3_ENDPOINT_URL_DOCKER=http://phylo-minio:9000
METHOD_DOWSER_URL_DOCKER=http://phylo-dowser:8001
METHOD_GCTREE_URL_DOCKER=http://phylo-gctree:8002
METHOD_BREPPHYLO_URL_DOCKER=http://phylo-brepphylo:8003
METHOD_CLONALTREE_URL_DOCKER=http://phylo-clonaltree:8004
```

Or remove these lines: without them the compose file uses exactly these
addresses. The old names keep working, so nothing breaks if you forget; they
are just not unique.

---

## Local development

Running the application on a development machine is described in the
[README](../README.md#quick-start-on-your-own-machine) and in
[DEVELOPMENT.md](./DEVELOPMENT.md). Two things matter for a server:

- `docker-compose.dev.yml` publishes the database and the object store on the
  host for development. **Never load it on a server.**
- `scripts/reset-local.sh` and `docker compose down -v` delete the volumes
  `phylo_postgres_data` and `phylo_minio_data`, which are the ones a deployment
  on the same machine uses. **Never run them on a server.**

---

## Server / production deployment

The `prod` compose profile includes `postgres`, `minio`, `minio-init`,
`api-prod`, `api-worker-prod`, `web-prod`, and the four method services.

### Starting and checking a deployment

The server needs Docker with Compose 2.17 or newer, and nothing else: no Node
and no Python on the host.

```bash
git clone --recurse-submodules <repository> && cd phylo-framework   # the ClonalTree code is a submodule
cp .env.example .env     # then replace every secret listed under "Required production secrets"
./run.sh check           # can it start? changes nothing
./run.sh prod            # start, or update after `git pull`
./run.sh status          # is it complete?
```

`./run.sh prod` is a convenience, not a requirement. It stores the container
limits for the resource budget in `.env`, runs the pre-start check, and then
runs exactly this command, which you may also run yourself:

```bash
docker compose --profile prod up -d --build
```

To pick up security updates of the base images and their operating-system
packages, rebuild with fresh base images from time to time (and whenever the
weekly CI scan asks for it), then start as usual:

```bash
docker compose --profile prod build --pull
./run.sh prod --no-build
```

The first start creates the project's networks and volumes, builds the images,
creates both buckets and the methods' storage user (`minio-init`), and brings
the database to the newest revision (`alembic upgrade head` runs each time the
API container starts). No further step is needed.

| Command | What it does |
|---|---|
| `./run.sh check` | Pre-start check, read-only: Docker and Compose version, `.env` present and complete, internal ports consistent, container limits match the resource budget, the reverse-proxy network exists, git information available for the image build, the ClonalTree submodule checked out, and whether the data volumes exist already (their data is used as it is) or will be created empty |
| `./run.sh prod [args]` | The above check, then `docker compose --profile prod up -d --build [args]`. `--no-build` starts what is already built; `--pull always` also refreshes base images |
| `./run.sh status` | Post-start check, read-only: every container running and healthy, `minio-init` finished, and, asked from inside the API container, database reachable, migrations at the newest revision, both buckets usable, every method service answering, version information present, email configured |
| `./run.sh ports` | Internal ports in effect, and whether they are consistent |
| `./run.sh down` | Stops the stack. Data volumes are kept |

Both checks print one line per item, name what is wrong and how to fix it, never
print a secret, and exit non-zero when something must be fixed. A warning is a
state you may have chosen (email switched off, no git information).

### Version information

Every stored result carries a `version_info` block: the commit the deployment
was built from, the image and base image of the method that ran, and its pinned
tool versions. The API image writes this itself when it is built
(`scripts/generate_version_info.py`); there is no step to run on the host and
no file to keep next to the compose file. Rebuilding after `git pull` updates
it.

- The build reads the commit from the repository's `.git` directory, which
  Compose hands to it as a separate, named build context (`.git` is not part of
  the normal build context). Only `HEAD` and the refs are copied; nothing of it
  ends up in the image. This is what needs Compose 2.17.
- `framework.version` is the tag when the deployed commit is exactly a tagged
  one, otherwise the abbreviated commit. `framework.git_commit` is always the
  full commit.
- An image build cannot see the working tree or ask the Docker daemon. Whether
  the checkout had local modifications (`git_dirty`) and image digests are
  therefore recorded as unknown, with the reason, under `unavailable`. Deploy
  from a clean checkout.
- **Deploying from an archive without `.git`:** set `PHYLO_GIT_DIR=config/no-git`
  in `.env`. The stack builds and runs; results then record that the commit is
  unknown, and `./run.sh status` shows a warning.

### Internal ports

No port is published on the host in production. Inside the project's networks
each service listens on its usual port, set by one variable from which every
URL, command and health check is built:

| Variable | Default | Service |
|---|---|---|
| `PHYLO_PORT_POSTGRES` | `5432` | PostgreSQL |
| `PHYLO_PORT_MINIO` | `9000` | Object store (S3 API) |
| `PHYLO_PORT_MINIO_CONSOLE` | `9001` | Object store console |
| `PHYLO_PORT_API` | `8000` | API (`phylo-api-prod`) |
| `PHYLO_PORT_WEB` | `3000` | Web (`phylo-web-prod`) |
| `METHOD_<NAME>_CONTAINER_PORT` | `8001`–`8004` | Dowser, GCtree, BrepPhylo, ClonalTree |

```bash
./run.sh ports                   # ports in effect + consistency check
./run.sh ports randomize         # random ports for database, object store and methods
./run.sh ports randomize --all   # ...and for the API and the web server
```

- Changing a port means recreating the containers
  (`docker compose --profile prod up -d`).
- **The reverse proxy addresses `phylo-api-prod` and `phylo-web-prod` by port.**
  If `PHYLO_PORT_API` or `PHYLO_PORT_WEB` changes, its configuration must change
  with it, or the site is unreachable. That is why `randomize` leaves these two
  alone unless `--all` is given.
- Random ports are optional and are written once: a later `randomize` keeps
  them (`--force` generates new ones). They add no real protection, because the
  networks are private to this project; use them when the server's rules ask
  for non-default ports.
- `S3_ENDPOINT_URL_DOCKER` and `METHOD_<NAME>_URL_DOCKER`, when present in
  `.env`, take precedence over the port variables. `./run.sh ports` and
  `./run.sh check` refuse a configuration in which they disagree; `randomize`
  rewrites them together with the ports.
- Valid ports are 1024–65535.

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

Notes:

- The object store publishes no port in production: neither its API nor its
  console is reachable from outside the project's internal network, and
  downloads go through the API. Keep it that way; put TLS on the reverse proxy.
- The API and the worker use the store's administrator credentials by default.
  For least privilege, create a user limited to the two buckets and put its
  credentials in `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY`. The method
  services already use a separate write-only user.
- `phylo_minio_data` holds every dataset and result file. Keep it on reliable
  storage.

### Persistent volumes

| Volume | Holds |
|---|---|
| `phylo_postgres_data` | PostgreSQL data |
| `phylo_minio_data` | All datasets + artifacts |

Per-job state of the method services lives inside their containers and is
removed when a job ends (see [Method containers](#method-containers)); it needs
no volume.

---

## Backup & restore

Backups are a manual step: **nothing in this project takes or schedules them.**
What needs backing up is the database and the object store, **together**: runs
in the database refer to files in the store by name. Take both in the same
maintenance window, ideally with no run in progress.

The commands below were executed on a throwaway copy of the production profile
on 2026-10-13: a deployment with an account, a dataset and a finished run was
backed up, destroyed, started empty and restored; afterwards the user could
sign in, the run's result and files were there byte for byte, and
`./run.sh status` reported a complete deployment.

Run them from the repository root, with the stack running. The object store
publishes no port, so its client joins the store's network; the store's
address and credentials are read from the API container, not from `.env`
(a `.env` with spaces in a value cannot be read by a shell).

```bash
mkdir -p backups/minio && chmod 700 backups
val() { docker compose --profile prod exec -T api-prod printenv "$1" | tr -d '\r'; }
STORE="$(val S3_ENDPOINT_URL | sed "s#://#://$(val S3_ACCESS_KEY_ID):$(val S3_SECRET_ACCESS_KEY)@#")"
BUCKETS="$(val S3_BUCKET_DATASETS) $(val S3_BUCKET_ARTIFACTS)"
NET=$(docker inspect phylo-minio --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}')
MC=pgsty/mc@sha256:cfc83108c3abb371f8fb84d99c1fdc88f8c237e022409b0081fb7c0a3be634dd
```

### Back up

```bash
docker compose --profile prod exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/backup_db.sql
for bucket in $BUCKETS; do
  docker run --rm --network "$NET" -v "$PWD/backups/minio:/backup" -e MC_HOST_store="$STORE" \
    "$MC" mirror --overwrite "store/$bucket" "/backup/$bucket"
done
```

Check that `backups/backup_db.sql` is not empty and that `backups/minio`
holds one directory per bucket. Keep `.env` with the backup: without the
same `JWT_SECRET_KEY` every session ends, which is harmless, but without the
same storage credentials the restored store cannot be opened.

### Restore

Into a deployment that is running (start an empty one with `./run.sh prod`
first, and set the variables above). **This replaces the database and
overwrites files of the same name in the store.**

```bash
# 1. Stop everything that uses the database.
docker compose --profile prod stop api-prod api-worker-prod web-prod

# 2. Replace the database with the dump. A deployment that has started already
#    created its tables: loading a dump on top of them fails halfway and leaves
#    a partial database, so the database is recreated first, and the load stops
#    at the first error instead of carrying on.
docker compose --profile prod exec -T postgres sh -c \
  'dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose --profile prod exec -T postgres sh -c \
  'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$POSTGRES_DB"' < backups/backup_db.sql

# 3. Put the files back.
for bucket in $BUCKETS; do
  docker run --rm --network "$NET" -v "$PWD/backups/minio:/backup:ro" -e MC_HOST_store="$STORE" \
    "$MC" mirror --overwrite "/backup/$bucket" "store/$bucket"
done

# 4. Start again. The API brings an older database to the current schema.
./run.sh prod --no-build
./run.sh status
```

Alternatively, with the stack stopped, snapshot the two volumes
`phylo_postgres_data` and `phylo_minio_data` with the tools of the host.

Not captured by any of this: files users have already downloaded, and results
that had expired before the backup was taken.

---

## Post-deploy checks

```bash
./run.sh status                          # containers, migrations, buckets, method services, version information, email
docker compose exec -T api-prod python -m apps.api.scripts.storage_check   # write/read/delete round-trip on both buckets
curl -fsS "$PUBLIC_API_BASE_URL/health"  # API health, through the reverse proxy
```

Then run one method end-to-end and confirm:
- the dataset appears in `phylo-datasets` (not in the repo/DB),
- artifacts appear in `phylo-artifacts`,
- `GET /runs/{id}/result` contains **no** base64 / `data:` URLs,
- image previews load via `/artifacts/{id}/preview`,
- the ZIP downloads via `/artifacts/{id}/download`.

---

## Troubleshooting a deployment

Start with `./run.sh status`: it names what is wrong and usually how to fix it.

| Symptom | Where to look, what to do |
|---|---|
| `./run.sh check` fails | It prints the reason and the fix for each item; nothing was started |
| A container shows `Restarting` | `docker compose --profile prod logs <service>`. For `api-prod` and `api-worker-prod` the usual cause is a secret that still has its example value ("Refusing to start", with the variable names) |
| `minio-init` ended with an error | `docker compose --profile prod logs minio-init`. The object store was not reachable, or the administrator credentials changed after the volume was first created |
| The site is unreachable but `./run.sh status` is complete | The reverse proxy: it must be on the `proxy_net` network and address `phylo-web-prod` and `phylo-api-prod` on `PHYLO_PORT_WEB` and `PHYLO_PORT_API` |
| Uploads fail at a certain size | The reverse proxy's body-size limit is below `MAX_UPLOAD_MB` |
| Every visitor shares one sign-in allowance, or limits trigger for everybody | `FORWARDED_ALLOW_IPS` is not set to the proxy's address. `curl <api>/auth/client-ip` must show your own address |
| No email arrives | `./run.sh status` shows whether mail is configured; the worker log shows each delivery attempt and its error. Runs are never affected |
| Runs wait for a long time | `docker compose --profile prod logs api-worker-prod`, and the run's own status message: it names the method that has no free slot or not enough memory |
| A run failed | Its status carries a code and a message written for the user ([When a run cannot finish](#when-a-run-cannot-finish)); failed runs keep a downloadable log. Internal errors carry a reference id that is also in the API or worker log |
| Results disappeared | They expire `RESULT_RETENTION_DAYS` after a run ends ([Storage lifecycle and retention](#storage-lifecycle-and-retention)). The worker logs each removal |
| The disk fills up | Images and build cache (`docker system df`), the two data volumes, and `STORAGE_LOCAL_PATH`, which should be nearly empty between runs |
| A vulnerability scan reports fixable findings | Rebuild with fresh base images: `docker compose --profile prod build --pull`, then `./run.sh prod --no-build` |

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
