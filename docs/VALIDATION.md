# System validation

How the application is validated as a whole, what each command proves, and
what the validation of 2026-10-13 found. Everything here runs on a development
machine or in CI, against the isolated `phylo-tests` Docker Compose project
with throwaway volumes. **None of it is meant for a server that runs the
application**: the system tests stop, kill and reconfigure containers.

## Commands

| Command | What it runs | Needs |
|---|---|---|
| `npm test` | Contracts, web unit tests, type check, all Python tests against real PostgreSQL and object storage | Docker, Node, Python |
| `npm run test:all -- --build` | The above, plus: end-to-end tests of all four methods on the real stack, browser tests, R tests, coverage gates | the same; about 10 minutes |
| `npm run test:system` | The system under pressure (next section) | Docker Compose 2.24+; about 10 minutes |
| `npm run lint`, `npm -w web run build` | Lint and the production web build | Node |
| `bash scripts/security-audit.sh` | `npm audit` and `pip-audit` on the locked dependencies | Node, `pip-audit` |
| `python3 scripts/scan_secrets.py [--history]` | Committed credentials and env files | git |
| `python3 scripts/scan_images.py`, `python3 scripts/audit_r_packages.py` | Known vulnerabilities in the built images and their R packages | Docker, network |
| `./run.sh check`, `./run.sh status` | A deployment before and after it starts | Docker |

`npm run test:all` and `npm run test:system` use the same compose project; do
not run them at the same time.

## The system under pressure (`npm run test:system`)

`tests/system` drives the real stack: real API, worker, database, object
store, mail server and all four method services, with container memory limits
and restart policies as in production (`tests/system/docker-compose.system.yml`).
Nothing is mocked. Each test produces one situation and checks that the
outcome is correct, visible to the user, and that the next run is served.

| Situation | What is checked |
|---|---|
| Several users submit at once (8 runs, 4 users, 4 methods) | Every run finishes; each user sees only their own; no service ever runs more jobs than it has slots; one run at a time per user |
| A job asks for 64 cores in a 1-CPU container | Runs with 1; the container stays at its CPU limit; the result records "requested 64, effective 1" |
| A job the service can never hold in memory | Refused with the reason, never started; accepted again when the limit allows |
| A job that needs more memory than the container has (Dowser, BrepPhylo) | **Real kernel out-of-memory kill** of the job: `ERROR [OUT_OF_MEMORY]`, message says what to do, the service keeps running, the slot is free, a log is kept, the next job completes |
| The kernel stops the service instead (Dowser, BrepPhylo) | Container restarts by its policy, the run ends as `METHOD_RESTARTED`, the next run completes |
| No free capacity | Runs wait with a visible `WAITING_FOR_CAPACITY` stage and reason, then run one after the other |
| A job over its time limit | `ERROR [TIMEOUT]`, job and tools gone, a downloadable size-limited log, which expires with the run (410) |
| A job process that disappears | `ERROR [JOB_PROCESS_LOST]` with its log; the slot is free |
| Input preparation over its limit | `ERROR [STAGING_TIMEOUT]`, method never started, no work directory left, next run starts |
| A method service crashes | Only its own run fails; another user's run on another method is unaffected; the container comes back; not repeated automatically |
| The worker restarts during a run | The same job is followed to `DONE`; one notification |
| The API restarts during a run | The run and the user's session are unaffected |
| The database restarts during a run | The run is not failed: the worker waits and follows the same job to `DONE` |
| A queued run is cancelled | `CANCELLED`, never started, costs no quota, sends no email |
| The sixth run within an hour | 429 with code and `Retry-After`; other users unaffected; giving back queued runs gives back the allowance |
| The mail server is away | The run is `DONE` regardless; the notification is kept, retried and delivered once when mail is back |

## Result of 2026-10-13

Run on macOS (Apple Silicon; the R images run under amd64 emulation), Docker
29.6, Compose 5.3, at commit `f3463b4` plus the fixes below.

| Layer | Result |
|---|---|
| Contracts | 126 passed |
| Web unit tests, type check | 242 passed; no type errors |
| Python: API, services, integration, deployment | 1163 passed; coverage gates met |
| End-to-end, all four methods on the real stack | 14 passed |
| Browser | 10 passed |
| R services, both images | 0 failures |
| System tests | 18 passed, in each of two complete runs from a fresh stack |
| Lint | no errors (10 warnings) |
| Production web build | succeeds |
| `npm audit` (production dependencies), `pip-audit` | no known vulnerabilities |
| Image scan (8 images) | passes after fix 5 below: no fixable critical finding in the images this project builds |
| R package audit (both R images) | three advisories, all previously accepted; nothing new |
| Fresh clone, production profile, isolated | healthy; `./run.sh status` complete; one real run per method; a crashed service restarted by itself |
| Tracked files and the whole history, for credentials | nothing found |

### Defects found by this validation, and fixed

1. **Out of memory stopped the service, not the job.** In the R services the
   service process is the largest one while a job is still growing, so the
   kernel stopped it: the container restarted and the run was reported as
   "service restarted, submit it again". Jobs now mark themselves as the
   process to stop first (`PHYLO_JOB_OOM_SCORE_ADJ`). Before: 3 of 3 real
   over-limit jobs restarted the container. After: 6 of 6 ended as
   `OUT_OF_MEMORY` with the service still running.
2. **A database restart failed running jobs.** The worker treated the lost
   connection as a failure of the run, deleted the input the job was still
   reading, and minutes later the run ended with an unrelated error. The
   worker now waits for the database (`WORKER_DATABASE_UNAVAILABLE_SECONDS`),
   and if it stays away leaves the run untouched for recovery.
3. **Two submissions at the same moment could answer 500.** When a user's two
   submissions (or one submission and the worker's sweep) raced, one request
   failed after its run had already been created. Before: 3 of 64
   simultaneous submissions; after: 0 of 192.
4. **Internal error text reached clients.** Every exception in a route with a
   database session was answered as `Database error: <exception text>` and
   never logged with its traceback. These now reach the application's error
   handler (reference id, traceback in the log, fixed message in production);
   a database that is away is answered with 503 and `Retry-After`.
5. **Stale operating-system packages in two images.** The API and GCtree
   images did not apply pending distribution updates, so the vulnerability
   scan failed on fixable critical findings (OpenSSL, GnuTLS, `perl-base`).
   Both builds now apply them; see [SECURITY-AUDIT.md](./SECURITY-AUDIT.md).
6. Smaller: an internal worker error now also stops the method job it
   abandons; a run's work directories are all removed when its job is over,
   including one left by an interrupted earlier attempt; one worker never
   processes the same run twice.

Each has regression tests at unit level and, for 1–3, on the real stack.

### Not covered

- Behaviour on the ComputImm server itself: nothing was run there.
- Native amd64 timing and memory figures. On the server the R service
  processes are smaller than under emulation, which changes the numbers, not
  the mechanisms tested.
- Load beyond a handful of concurrent users, and long-running (hours) jobs.
- One test of the job manager failed once in about forty repetitions of its
  file and could not be reproduced or identified; the complete suite passed
  three times afterwards.
- A real SMTP provider and a real reverse proxy; a test mail server and direct
  access were used.
- Loss of the object store *during* a run on the real stack (covered at
  integration level only).
- Host-wide memory pressure: the tests exhaust one container's limit, never
  the machine's memory.
