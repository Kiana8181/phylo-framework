# Async run orchestration + cancellable uploads — testing

This documents the tests added for the async orchestration / cancellable
upload work and the exact commands to run them, plus what cannot run locally
and why.

## What runs locally

### Backend unit tests (pytest)

Coarse stage→progress mapping is a pure function (no timers, terminal states
never imply completion):

```bash
# from the repo root, using the project venv
.venv/bin/python -m pytest apps/api/tests/test_stage_map.py -v
```

### Method-service job lifecycle (pytest)

Exercises the per-job child-process `JobManager` end to end with a lightweight
stub runner (no scientific deps), via the injectable `runner_path`:

- `POST /jobs` returns quickly with a `job_id` (does not block on compute).
- Status transitions to `DONE` and `result.json` is only served once `DONE`.
- Cancel terminates a long-running child (SIGTERM then SIGKILL) and is
  idempotent.

```bash
.venv/bin/python -m pytest services/gctree/tests/test_job_manager.py -v
```

The `clonaltree` service shares the same `job_manager.py`, so the gctree test
covers both Python services' job lifecycle.

Run both backend suites together:

```bash
.venv/bin/python -m pytest apps/api/tests services/gctree/tests -v
```

> Note: `pytest` is not declared in `apps/api/pyproject.toml` runtime deps;
> install it in the venv first with `.venv/bin/python -m pip install pytest`.

### Frontend unit tests (vitest)

Stage-state derivation for the Mermaid flowchart is extracted into a pure module
(`apps/web/components/phylo/runStageNodes.ts`) and tested directly:

- earlier stages `done`, current `active`, later `pending`;
- `DONE` marks all nodes done;
- `ERROR`/`CANCELLED` are represented without implying success (the
  `COMPLETED` node is never `done`);
- unknown method-reported stages are tolerated (inserted, not crashing);
- labels are sanitized for Mermaid.

```bash
cd apps/web && npx vitest run
```

### Type checks

```bash
cd apps/web && npx tsc --noEmit          # web app
npm run build --workspace packages/contracts   # contracts (emits dist/ consumed by web)
```

## What cannot run locally (blockers)

- **Full API integration tests** (`POST /runs` queues fast, `cancel` queued →
  CANCELLED, `cancel` running → method cancel → CANCELLED, upload
  init→content→File row, upload cancel cleanup). Blocker: these need a live
  Postgres database and the FastAPI app's full dependency set (SQLAlchemy
  models, Alembic-migrated schema). No test database/fixtures are configured in
  the repo. Run them against a database via docker-compose (`db` + `api` +
  `api-worker`) once a pytest DB fixture is added.
- **R method services** (Dowser, BrepPhylo) `/jobs` + `job_runner.R` cancel
  behavior. Blocker: `Rscript` is not installed locally and the R package set
  (plumber + method deps) is only available in the service Docker images. Verify
  via `docker compose up dowser brepphylo` and hitting `/jobs`.
- **GCtree/ClonalTree real `/jobs` execution** (not the stubbed lifecycle).
  Blocker: requires each method's scientific Python environment from its Docker
  image. The lifecycle/cancel mechanics are covered by the stub-runner test
  above; the real computation path is validated in-container.
- **Frontend component/hook tests** (Cancel Upload aborts XHR + calls cleanup;
  Stop Run enters cancelling UI). Blocker: the repo's vitest setup has no DOM
  environment (`jsdom`) or `@testing-library/react`, and the `include` glob only
  picks up `components/**/__tests__/**/*.test.ts`. The pure stage logic is tested
  instead; adding `jsdom` + testing-library would enable the interaction tests.
