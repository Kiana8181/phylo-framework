"""Real DB/worker transitions; only the remote scientific job is controlled."""
from uuid import UUID
from unittest.mock import AsyncMock
from datetime import datetime, timezone
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy import select
from apps.api.database.models import RunStatus, RunTree, RunArtifact
from apps.api.repositories.run_repository import RunRepository
from apps.api.workers import run_worker as worker
from apps.api.services.method_jobs_client import JobStatus, MethodServiceUnavailable

pytestmark = pytest.mark.integration


@pytest.fixture
def artifact_store(tmp_path, monkeypatch):
    """The artifact bucket the worker verifies uploads against (on disk here)."""
    from apps.api.storage.local_storage import LocalStorage
    store = LocalStorage(str(tmp_path / 'artifact-bucket'))
    monkeypatch.setattr(worker, '_artifact_storage', store)
    return store


@pytest.fixture
async def queued(session, account, monkeypatch, artifact_store):
    monkeypatch.setattr(worker, 'AsyncSessionLocal', async_sessionmaker(session.bind, expire_on_commit=False))
    monkeypatch.setattr(worker, 'METHOD_POLL_INTERVAL', 0)
    repo = RunRepository(session)
    run = await repo.create_run(method_id='gctree', params={}, user_id=UUID(account['user']['id']))
    await repo.promote_next_for_user(run.user_id)
    await repo.claim_next_run('test-worker', 60)
    return run.id


def mock_jobs(monkeypatch, statuses, result=None):
    submit = AsyncMock(return_value='job-1')
    monkeypatch.setattr(worker.jobs, 'submit_job', submit)
    monkeypatch.setattr(worker.jobs, 'get_job_status', AsyncMock(side_effect=statuses))
    monkeypatch.setattr(worker.jobs, 'get_job_result', AsyncMock(return_value=result))
    monkeypatch.setattr(worker.jobs, 'cancel_job', AsyncMock(return_value=True))
    return submit


async def fresh(session, run_id):
    session.expire_all()
    return await RunRepository(session).get_by_id(run_id)


async def test_worker_recovers_transient_poll_failure_persists_trees_and_artifacts(session, queued, monkeypatch, artifact_store):
    await artifact_store.upload(b'(a:1,b:2)root:0;\n\n', 'runs/test/tree.nwk')
    mock_jobs(monkeypatch, [RuntimeError('transient network failure'),
        JobStatus(True, 'job-1', 'RUNNING', stage='BUILDING_TREES', progress=50),
        JobStatus(True, 'job-1', 'DONE')], {
        'ok': True, 'trees': ['(a:1,b:2)root:0;'], 'manifest_version': 1,
        'artifacts': [{'object_key': 'runs/test/tree.nwk', 'filename': 'tree.nwk', 'size_bytes': 18, 'kind': 'newick'}],
    })
    await worker.process_run(queued, 'test-worker')
    run = await fresh(session, queued)
    assert run.status == RunStatus.DONE
    assert run.progress == 100
    assert run.method_job_id == 'job-1'
    trees = (await session.execute(select(RunTree).where(RunTree.run_id == queued))).scalars().all()
    assert len(trees) == 1
    assert trees[0].newick == '(a:1,b:2)root:0;'
    artifacts = (await session.execute(select(RunArtifact).where(RunArtifact.run_id == queued))).scalars().all()
    assert len(artifacts) == 1
    assert artifacts[0].object_key == 'runs/test/tree.nwk'
    assert 'newick' not in run.result['trees'][0]


@pytest.mark.parametrize('status,expected', [('ERROR', RunStatus.ERROR), ('CANCELLED', RunStatus.CANCELLED)])
async def test_worker_terminal_failure_states(session, queued, monkeypatch, status, expected):
    mock_jobs(monkeypatch, [JobStatus(False, 'job-1', status, message='method failure')])
    await worker.process_run(queued, 'test-worker')
    run = await fresh(session, queued)
    assert run.status == expected
    assert run.finished_at is not None
    assert run.worker_lease_until is None


async def test_invalid_manifest_fails_instead_of_reporting_success(session, queued, monkeypatch):
    mock_jobs(monkeypatch, [JobStatus(True, 'job-1', 'DONE')], {'ok': True, 'trees': ['(a,b);']})
    await worker.process_run(queued, 'test-worker')
    run = await fresh(session, queued)
    assert run.status == RunStatus.ERROR
    assert 'manifest' in run.error.lower()
    assert not (await session.execute(select(RunTree).where(RunTree.run_id == queued))).scalars().all()


async def test_cancel_before_submit_does_not_start_computation(session, queued, monkeypatch):
    submit = mock_jobs(monkeypatch, [])
    await RunRepository(session).update(queued, cancel_requested_at=datetime.now(timezone.utc))
    await worker.process_run(queued, 'test-worker')
    submit.assert_not_awaited()
    assert (await fresh(session, queued)).status == RunStatus.CANCELLED


async def test_reclaimed_run_resumes_existing_job_without_duplicate_submission(session, queued, monkeypatch):
    await RunRepository(session).set_method_job_id(queued, 'existing-job')
    submit = mock_jobs(monkeypatch, [JobStatus(False, 'existing-job', 'CANCELLED')])
    await worker.process_run(queued, 'replacement-worker')
    submit.assert_not_awaited()
    worker.jobs.get_job_status.assert_awaited_once_with('gctree', 'existing-job')


async def test_missing_method_service_marks_error_and_promotes_next(session, queued, monkeypatch):
    run = await fresh(session, queued)
    repo = RunRepository(session)
    waiting = await repo.create_run(method_id='gctree', params={}, user_id=run.user_id)
    waiting_id = waiting.id
    monkeypatch.setattr(worker.jobs, 'submit_job', AsyncMock(side_effect=MethodServiceUnavailable('unconfigured')))
    await worker.process_run(queued, 'test-worker')
    assert (await fresh(session, queued)).status == RunStatus.ERROR
    assert (await fresh(session, waiting_id)).dispatch_seq is not None


async def test_unexpected_worker_fault_stores_a_reference_not_the_exception(session, queued, monkeypatch, caplog):
    """An orchestration fault is shown to the run owner, so it must not carry
    internal detail; the cause stays in the worker log under the same reference."""
    import logging
    import re

    internal = 'could not connect to 10.0.0.7:5432 as phylo_app'
    monkeypatch.setattr(worker.jobs, 'submit_job', AsyncMock(side_effect=RuntimeError(internal)))
    with caplog.at_level(logging.ERROR, logger='phylo.api.errors'):
        await worker.process_run(queued, 'test-worker')
    run = await fresh(session, queued)
    assert run.status == RunStatus.ERROR
    stored = ' '.join(str(v) for v in (run.error, run.message, run.stage_message, run.result))
    assert internal not in stored
    reference = re.search(r'reference ([0-9a-f]{12})', run.message).group(1)
    record = next(r for r in caplog.records if reference in r.getMessage())
    assert internal in str(record.exc_info[1])
    assert str(queued) in record.getMessage()
