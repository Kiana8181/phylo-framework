# Testing and coverage

The reproducible entry point is `npm run test:all`. It runs tests across contracts,
React, the API, PostgreSQL, storage, the worker, Python/R method services and the
browser. Missing required infrastructure fails the run; it does not silently skip
integration tests. CI uses the same command.

A second, separate entry point, `npm run test:system`, puts the real stack under
pressure (memory limits, crashed containers, restarts, a mail outage). It is
described in [VALIDATION.md](./VALIDATION.md), together with the result of the
most recent complete validation.

## Setup and commands

Use Node 22, Python 3.12 and Docker Compose v2.
On Windows run the orchestrator under WSL2. R and scientific Python dependencies
run in Docker; they need not be installed in the host Python environment.

```bash
npm ci
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
npx playwright install chromium

# Contracts, web unit/component tests, type checking, API/service unit tests,
# actual PostgreSQL migrations/repositories, and actual MinIO/S3 integration:
npm test

# First full run: build the five production service images, then test layers.
npm run test:all -- --build

# Later full runs can reuse scientific dependencies in existing images.
# Current checked-out service sources are bind-mounted read-only.
npm run test:all
```

Linux CI installs Chromium system libraries using
`npx playwright install --with-deps chromium`. Set `TEST_PYTHON` if the Python
interpreter is elsewhere. `npm run test:coverage` aliases the complete suite.
`--keep-services` preserves the test containers for inspection; Python services
are still stopped gracefully to flush subprocess coverage. Cleanup is:

```bash
docker compose -f docker-compose.test.yml --profile full down -v
```

For targeted debugging:

```bash
# No external services required:
npm run test:js
.venv/bin/python -m pytest -c pytest.ini -m 'not integration'

# Provision isolated dependencies before direct integration commands:
docker compose -f docker-compose.test.yml up -d --wait postgres minio
.venv/bin/python scripts/init-test-services.py
.venv/bin/python -m pytest -c pytest.ini apps/api/tests/test_run_queue.py -v

# With the full stack started (see docker-compose.test.yml):
npm run test:e2e
npm run test:r

# The real stack under pressure. Starts and removes its own stack; needs
# Docker Compose 2.24+. Never at the same time as test:all.
npm run test:system
npm run test:system -- -k memory      # extra arguments go to pytest
```

The R coverage dependency volume `phylo-tests-r-library` is retained as a cache.
The test runner uses fixed loopback ports: PostgreSQL **55432**, MinIO **59000**,
API **58000**, methods **58001–58004**, and web **53000**. Production/dev Compose
is a separate project and is never stopped or reset. Test PostgreSQL and MinIO
use disposable tmpfs; worker staging uses a project-scoped test volume. The API
and integration harness use separate databases (`phylo_e2e_test` and
`phylo_test`) so truncation cannot race the live worker. Root `conftest.py` sets
isolated credentials, filesystem paths and disabled external email/OAuth keys
before application imports. The E2E containers do not mount `.env`.

Do not run two copies of the suite concurrently on the same machine: the reserved
test ports/project and integration database are shared. A CI job owns its runner.

## Coverage and evidence

| Layer | Tool and evidence | Report |
|---|---|---|
| Shared executable TS contracts | Vitest V8, 100% line/branch/function/statement gate | `coverage/contracts/index.html` |
| Entire frontend source | Vitest plus source-mapped Istanbul from real Chromium navigation | `coverage/web-combined/index.html` |
| Frontend unit tests alone | Includes unimported app/component/feature/lib files | `coverage/web/index.html` |
| API and Python services | pytest-cov plus actual API/worker/job child-process coverage | `coverage/python/combined-html/index.html` |
| Python unit/integration tests alone | Branch coverage including unimported source | `coverage/python/html/index.html` |
| R modules, independently for both methods | covr, validator/orchestration/manifest/process-lifecycle tests | `coverage/dowser/cobertura.xml`, `coverage/brepphylo/cobertura.xml` |
| Browser runs | Playwright HTML, JUnit, screenshot and trace on failure | `coverage/browser/index.html`, `test-results/browser/` |
| Real scientific executions | JUnit and per-method result/tree/artifact JSON | `coverage/scientific/` |
| Container diagnostics | Captured before cleanup, even after failure | `coverage/docker.log` |

`scripts/check-coverage.py` enforces separate line/branch baselines for the API and
each Python service and separate frontend/R baselines. Contracts enforce 100%
for executable code, including the functions in `src/types.ts`. Whole-application
baselines are deliberately the measured starting point, **not a claim of 100%
coverage**. Raise them as uncovered behavior is tested. Reports include files
never imported by tests; they do not count only the selected tested utilities.

The full runner deletes previous raw browser/process measurements before a run.
Python child processes are instrumented with a test-only `.pth` file; SIGTERM and
normal exit save coverage, then source paths from each container are mapped back
to the corresponding repository service. Each service gets a distinct mapping,
so the two different `app.py` files cannot be mistaken for each other. Browser
instrumentation is enabled only by `TEST_BROWSER_COVERAGE=1`, and collected before
navigation and at test teardown. Source maps remap post-SWC counters to TS/TSX.

The Python denominator excludes tests, migrations, the upstream ClonalTree
pipeline code (`services/clonaltree/base-codes/`) and GCtree environment bootstrap. Migrations are exercised by building
the real PostgreSQL schema, including sequences, enums and partial unique indexes.
R coverage measures service **modules**; executable `plumber.R`/`job_runner.R`
entrypoints are exercised through real HTTP scientific E2E tests, but their
subprocess line coverage is not included in covr's percentage. These percentages
must not be described as whole-R-service coverage. Browser-only and unit-only
percentages use different instrumentation denominators; compare like with like.

## Test matrix and audit findings

| Area | Tests and failure cases |
|---|---|
| Contracts | Every route helper, URL escaping, envelopes, stage sequences, scientific result normalization, JSON Schema validation of documented requests and lightweight results |
| Input preprocessing | Existing cross-method malformed-input matrix, tabular/FASTA conversion, row widths, required columns, root insertion and abundance IDs; staging mount boundaries and cleanup ownership |
| Authentication | Real register/login/me/refresh, duplicate identities, inactive accounts, malformed/expired/wrong-type tokens, reset single-use and non-enumeration; simulated Google HTTP failures |
| Uploads/datasets | Raw content round-trip, SHA-256, actual-byte quota, empty upload, duplicate completion, cancellation/cleanup, ownership, soft deletion, active-run protection and rerun of a deleted dataset |
| Run/artifact access | Owner, other user and anonymous requests, listing/streaming/preview, nullable artifact roles, private run cancellation |
| Database/queue | Migration chain, per-user quota/fairness, partial unique index, simultaneous workers on independent connections, lease expiry/reclaim and stale-owner lease renewal |
| Worker | Submit/poll/persist, transient polling failure, method failure/cancel, cancellation before submission, resume without resubmission, malformed manifest and next-user-turn promotion |
| Storage | Shared behavioral suite for local disk, boto3 S3 against MinIO, and MinIO SDK; streaming, rename, missing keys, signed downloads, path escape and binary stream upload |
| Python methods | Existing scientific helper tests; lifecycle tests parameterized over both implementations; real artifact upload/checksum and manifest failure paths |
| R methods | Existing validators and Dowser scientific orchestration; both methods' disk state, manifests, real child completion and process-group cancellation |
| React/frontend | Existing scientific tree/layout/trace tests; actual upload hook progress/abort/cleanup, stop-run interaction, confirmation locking/cleanup, auth storage, HTTP failures and multipart conversion |
| Scientific E2E | All four methods run the documented ExampleAirr clone through API → database → worker → real method → MinIO → tree/artifact downloads; graph invariants/checksums/history, the deployed commit recorded in the result, plus malformed dataset failure for each method |
| Limits and quotas | Rolling hourly quota, submission ceiling and queue limit under concurrent requests; capacity-aware dispatch, waiting and time limits; lost jobs, restarts and artifact verification before `DONE` |
| Sign-in protection | Proof-of-work CAPTCHA (single use, expiry), rate limits per address and per account, proxy-header trust, email verification, hashed one-time tokens, session invalidation |
| Email | SMTP delivery against a local test server (STARTTLS, authentication, outages), the notification outbox, retries, exactly one email per finished run, none for cancelled runs |
| Storage lifecycle | Expiry dates, removal order and retries, 410 for expired results, upload size limit, abandoned-upload clean-up, per-job scratch data and logs in all four services |
| Deployment tooling | The compose file's limits, networks, secret isolation and ports; the resource plan, port tool, pre-start and post-start checks and `run.sh`, run against a stand-in `docker`; the version-information generator; the history rewrite on throwaway repositories; the secret scanner |
| Documentation | Every relative link, every `npm run` and `./run.sh` command, every script path and every setting named in the documentation exists; the configuration reference and `.env.example` cover the same settings |
| System under pressure | `npm run test:system`: see [VALIDATION.md](./VALIDATION.md) |
| Browser E2E | Protected navigation, signup/login/reload, actual dataset deletion, each method's documented example, and zero-abundance persistence through API and node details |

The initial audit found that `npm test` ran only TS suites, 13 PostgreSQL tests
were silently skipped, no CI/coverage/browser harness existed, and the R suites
were manual. Two frontend tests asserted constants constructed inside the test
itself; they were removed in favor of tests of actual contract behavior.

New failing regression tests drove these production fixes:

- Refresh tokens can no longer authenticate access endpoints; malformed refresh
  subjects return 401 instead of 500, and error normalization preserves auth headers.
- Anonymous callers cannot read or cancel user-owned runs or download their artifacts.
- Artifacts with a null role no longer disappear because of SQL null comparison.
- Local storage validates resolved paths and supports synchronous binary streams.
- MinIO signed downloads use the SDK's `expires=timedelta(...)` argument.
- The frontend calls a failure callback once and removes an explicit content type
  after converting an upload body to FormData, preserving multipart boundaries.
- The shared result schema accepts the actual lightweight tree summaries; Newick
  is retrieved separately from the per-tree endpoint.

## Automation and limits

`.github/workflows/tests.yml` runs on pushes, pull requests, manual dispatch and a
weekly schedule. It runs a unit/integration job followed by the full scientific,
R and browser job. A failure or coverage regression fails the job. Coverage,
JUnit, scientific evidence and failure traces are retained as GitHub artifacts
for 30 days. No Codecov token or external reporting account is needed.

The first build downloads large scientific R/Python dependencies and can be much
slower than tests against cached images. Local execution validates the workflow's
commands; the hosted GitHub Actions run itself needs a push to the repository.

Coverage is not proof of scientific validity or publication acceptance. The
scientific suite covers a documented single-clone scenario with fixed parameters,
not every stochastic seed, external tree builder, DTA/time-evolution combination,
or large-data performance limit. Upstream algorithm internals are not tested here.
Google and email boundaries are simulated; no real accounts or mail are used.
The browser suite currently covers Chromium, not Firefox/WebKit/mobile. Remaining
uncovered branches and UI flows stay visible in the reports.

## Earlier verified run (2026-10-05, historical)

This section records a run made before the production hardening. The current
figures are in [VALIDATION.md](./VALIDATION.md). The commit id below is from
before the repository history was rewritten on 2026-10-13 and no longer exists;
by its position (the first commit after tag `v2.1.0`) it corresponds to
`4d8946ef9be5`.

The revised checkout at base commit
`a596dbf0a01fd066d396be39a77f8cbb82e8c491` passed `npm run test:all` after a
complete `npm run test:all -- --build` image rebuild. The rebuild used cached
dependency layers and rebuilt the changed source layers; it was a local arm64
Docker Desktop run, not hosted CI or an anonymous public checkout. The test run
used Node 24.13.0, Python 3.12.12, Docker 29.6.2, Docker Compose 5.3.1, pytest
8.4.1, pytest-asyncio 1.1.0, coverage.py 7.10.6, Vitest 3.2.4, Playwright
1.55.1 and covr 3.6.5. Node 22 was not installed locally; CI remains configured
for Node 22.

`npm run lint` exited successfully with existing unused-disable warnings in two
test files and one unused `vi` import warning. `npm run build` initially failed
because the sandbox could not resolve `fonts.googleapis.com`; the same command
passed with network access, compiling all 24 static/SSG routes. Type checking
passed both in the suite and production build.

| Suite | Result |
|---|---:|
| Python unit/integration | 312 passed, 0 skipped |
| TS shared contracts | 123 passed |
| Frontend unit/component | 161 passed |
| Real scientific success/failure scenarios | 8 passed |
| Real Chromium workflows | 7 passed |
| Dowser and BrepPhylo R tests | All validator/module/process/lifecycle assertions passed |

| Layer | Line coverage | Branch coverage |
|---|---:|---:|
| API, combined | 74.57% | 54.06% |
| GCtree service, combined | 63.74% | 51.01% |
| ClonalTree service, combined | 78.70% | 63.23% |
| Executable TS contracts | 100% | 100% |
| Frontend unit + browser | 43.60% | 60.57% |
| Dowser R modules | 45.39% | Not measured by this covr report |
| BrepPhylo R modules | 65.35% | Not measured by this covr report |

The unit-only frontend line figure is 17.67%; the combined figure includes real
page behavior, zero-abundance inspection and all four result views. Python's
combined line-and-branch aggregate is 68.44%; the
layer-specific figures above are more informative. One rebuilt run encountered a
single Dowser browser timeout after the same method had passed the scientific
suite; the immediately repeated complete suite passed all seven browser workflows.
Generated reports, not these snapshots, are authoritative for subsequent runs.

### Isolated production-profile clean start

A scratch copy of the revised source was started as Compose project
`phylo-nargab-clean` with separate container names, local image tags, ports,
bind-mounted staging and named volumes. This isolation was necessary because the
ordinary Compose definition contains fixed container names and image tags. The
host was arm64. Changed source layers were rebuilt; dependency layers were partly
cached, and the web image ran a fresh `npm ci` before its successful production
build. This was a local-source exercise rather than an anonymous public checkout.

`docker compose --profile prod up -d --build` applied all migrations, initialized
both MinIO buckets and the scoped method user, started the worker, and reached
healthy API, web and PostgreSQL states. The
documented in-container storage check passed upload/exists/download/stream/delete
round trips for both datasets and artifacts. A real Chromium flow completed a
GCtree run with the documented 43-sequence sample, retrieved three trees and
three API artifact entries, and downloaded `gctree_run_artifacts.zip`.

The isolated containers, network and volumes were then removed. Ordinary
developer and test volumes were not used or reset.

Tool configuration references: [Vitest 3 coverage](https://v3.vitest.dev/guide/coverage/)
and [Playwright web server lifecycle](https://playwright.dev/docs/test-webserver).
