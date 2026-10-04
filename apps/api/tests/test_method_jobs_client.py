"""HTTP contract tests with a real httpx transport and failure injection."""
import json
import httpx
import pytest
from apps.api.services import method_jobs_client as jobs


@pytest.fixture
def transport(monkeypatch):
    requests = []
    responses = []
    def handle(request):
        requests.append(request)
        status, body = responses.pop(0)
        return httpx.Response(status, json=body)
    original = httpx.AsyncClient
    monkeypatch.setattr(jobs.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    return requests, responses


@pytest.mark.parametrize('method', ['gctree', 'clonaltree', 'dowser', 'brepphylo'])
async def test_submit_poll_fetch_cancel_contract(method, transport):
    requests, responses = transport
    responses.extend([(202, {'job_id': 'j1'}), (200, {'status': 'done', 'progress': '100'}),
                      (200, {'ok': True, 'manifest_version': 1}), (409, {})])
    assert await jobs.submit_job(method, file_path='/input.fa', params={'seed': 42}, run_id='run1') == 'j1'
    assert json.loads(requests[0].content) == {'file_path': '/input.fa', 'params': {'seed': 42}, 'run_id': 'run1'}
    status = await jobs.get_job_status(method, 'j1')
    assert (status.job_id, status.status, status.progress) == ('j1', 'DONE', 100)
    assert (await jobs.get_job_result(method, 'j1'))['manifest_version'] == 1
    assert await jobs.cancel_job(method, 'j1') is True
    assert [r.method for r in requests] == ['POST', 'GET', 'GET', 'POST']
    assert str(requests[1].url).endswith('/jobs/j1/status')
    assert str(requests[2].url).endswith('/jobs/j1/result')
    assert str(requests[3].url).endswith('/jobs/j1/cancel')


@pytest.mark.parametrize('progress,expected', [('bad', None), (None, None), (42, 42)])
async def test_invalid_progress_is_tolerated(transport, progress, expected):
    transport[1].append((200, {'progress': progress}))
    assert (await jobs.get_job_status('gctree', 'j')).progress == expected


async def test_failed_submit_is_not_silently_successful(transport):
    transport[1].append((503, {'error': 'unavailable'}))
    with pytest.raises(httpx.HTTPStatusError):
        await jobs.submit_job('gctree', file_path=None, params={})
    transport[1].append((200, {}))
    with pytest.raises(RuntimeError, match='job_id'):
        await jobs.submit_job('gctree', file_path=None, params={})


async def test_unconfigured_service(monkeypatch):
    monkeypatch.setattr(jobs, 'method_service_url', lambda _: None)
    with pytest.raises(jobs.MethodServiceUnavailable):
        await jobs.get_job_status('missing', 'j')
