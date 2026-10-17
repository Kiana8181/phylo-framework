"""Storage lifecycle through the whole stack: API -> worker -> method -> object store.

Requires docker-compose.test.yml --profile full. The stack keeps results for
the default 60 days and looks for expired ones every 2 seconds; a test moves
one run's date into the past (the only thing done behind the application's
back) and then observes what the application does about it.
"""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg
import httpx
import pytest
from minio import Minio

from tests.support.accounts import messages_for, register_verified

ROOT = Path(__file__).resolve().parents[2]
PARAMS = json.loads((ROOT / 'tests/fixtures/scientific-params.json').read_text())
SAMPLE = ROOT / 'apps/web/public/samples/ExampleAirr_clone_3128.tsv'
API = 'http://127.0.0.1:58000'
MAIL = 'http://127.0.0.1:58025'
GCTREE = 'http://127.0.0.1:58002'
DATABASE = 'postgresql://phylo_test:phylo_test@127.0.0.1:55432/phylo_e2e_test'
BUCKET = 'phylo-test-artifacts'
MB = 1024 * 1024
pytestmark = pytest.mark.scientific


def unwrap(response):
    response.raise_for_status()
    value = response.json()
    return value['data'] if isinstance(value, dict) and value.get('status') == 'success' and 'data' in value else value


def stored_under(prefix: str) -> list[str]:
    store = Minio('127.0.0.1:59000', access_key='phylo_test', secret_key='phylo_test_secret', secure=False)
    return sorted(o.object_name for o in store.list_objects(BUCKET, prefix=prefix, recursive=True))


async def wait_for(check, seconds: float, what: str):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = await check()
        if value:
            return value
        await asyncio.sleep(0.5)
    raise AssertionError(f'timed out waiting for {what}')


async def test_results_expire_files_leave_the_store_and_the_run_stays_in_the_history():
    async with httpx.AsyncClient(base_url=API, timeout=60, trust_env=False) as api:
        email = f'{uuid4().hex}@example.org'
        await register_verified(api, email, email.split('@')[0], 'e2e-password')
        init = unwrap(await api.post('/uploads/init', json={'original_filename': SAMPLE.name}))
        uploaded = unwrap(await api.put(init['content_url'], content=SAMPLE.read_bytes()))
        run_id = unwrap(await api.post('/runs?method=gctree', json={'file_id': uploaded['file_id'], 'params': PARAMS['gctree']}))['run_id']

        async def finished():
            status = unwrap(await api.get(f'/runs/{run_id}/status'))
            return status if status['status'] in ('DONE', 'ERROR', 'CANCELLED') else None
        status = await wait_for(finished, 300, 'the run to end')
        assert status['status'] == 'DONE', status

        # --- before the date ------------------------------------------------
        kept_for = datetime.fromisoformat(status['expires_at']) - datetime.fromisoformat(status['finished_at'])
        assert timedelta(days=59, hours=23) < kept_for < timedelta(days=60, hours=1)
        assert status['results_expired'] is False
        artifacts = unwrap(await api.get(f'/runs/{run_id}/artifacts'))['artifacts']
        trees = unwrap(await api.get(f'/runs/{run_id}/trees'))['trees']
        prefix = f'artifacts/{run_id}/'
        in_store = stored_under(prefix)
        assert artifacts and trees and len(in_store) >= len(artifacts)
        assert any(a['filename'].endswith('.log') for a in artifacts), 'a finished run keeps its execution log'

        # The owner is told the date by email as well.
        async def done_mail():
            mine = [m for m in await messages_for(email) if 'has finished' in m['subject']]
            return mine[0] if mine else None
        mail = await wait_for(done_mail, 30, 'the notification email')
        assert f"The results are kept until {status['expires_at'][:10]}." in mail['text']

        # The method service keeps nothing of the job once the worker has its result.
        db = await asyncpg.connect(DATABASE)
        try:
            job_id = await db.fetchval('SELECT method_job_id FROM runs WHERE id = $1', run_id)
            assert job_id
            async with httpx.AsyncClient(base_url=GCTREE, timeout=10, trust_env=False) as service:
                async def forgotten():
                    return (await service.get(f'/jobs/{job_id}/status')).status_code == 404
                await wait_for(forgotten, 30, 'the method service to forget the job')
                assert (await service.get(f'/jobs/{job_id}/log')).status_code == 404
                assert (await service.delete(f'/jobs/{job_id}')).status_code == 404

            # --- the date passes --------------------------------------------
            await db.execute("UPDATE runs SET expires_at = now() - interval '1 minute' WHERE id = $1", run_id)
        finally:
            await db.close()

        async def expired():
            current = unwrap(await api.get(f'/runs/{run_id}/status'))
            return current if current['results_expired'] else None
        status = await wait_for(expired, 60, 'the results to expire')

        # --- after the date -------------------------------------------------
        assert stored_under(prefix) == []                                 # nothing of the run is left in the store
        assert status['status'] == 'DONE' and status['results_expired_at'] and status['method_id'] == 'gctree'
        gone = [f'/runs/{run_id}/result', f'/runs/{run_id}/trees', f"/runs/{run_id}/trees/{trees[0]['treeId']}",
                f'/runs/{run_id}/artifacts', f"/artifacts/{artifacts[0]['id']}/download"]
        for path in gone:
            response = await api.get(path)
            assert response.status_code == 410, (path, response.status_code)
            body = response.json()
            assert body['data']['code'] == 'RESULT_EXPIRED' and 'expired on' in body['message']
        listed = [r for r in unwrap(await api.get('/runs')) if r['id'] == run_id]
        assert len(listed) == 1 and listed[0]['results_expired'] is True and listed[0]['params'] is not None
        # The dataset is the user's own file: retention does not touch it.
        assert (await api.get(f"/datasets/{uploaded['file_id']}/download")).status_code == 200
        files = unwrap(await api.get('/files'))
        assert any(f['id'] == uploaded['file_id'] for f in (files['files'] if isinstance(files, dict) else files))
        # And the account can start the same analysis again.
        again = await api.post('/runs?method=gctree', json={'file_id': uploaded['file_id'], 'params': PARAMS['gctree']})
        assert again.status_code in (200, 201, 202), again.text
        await api.post(f"/runs/{unwrap(again)['run_id']}/cancel")


async def test_a_file_over_the_upload_limit_is_refused_and_leaves_nothing_behind():
    async with httpx.AsyncClient(base_url=API, timeout=120, trust_env=False) as api:
        email = f'{uuid4().hex}@example.org'
        await register_verified(api, email, email.split('@')[0], 'e2e-password')
        limits = unwrap(await api.get('/uploads/limits'))
        assert limits['max_upload_bytes'] == 20 * MB and limits['used_bytes'] == 0

        announced = await api.post('/uploads/init', json={'original_filename': 'big.fa', 'expected_size': 21 * MB})
        assert announced.status_code == 413 and announced.json()['data']['code'] == 'UPLOAD_TOO_LARGE'
        assert '20 MB' in announced.json()['message']

        # A client that does not announce the size is stopped while it sends.
        init = unwrap(await api.post('/uploads/init', json={'original_filename': 'big.fa'}))
        sent = await api.put(init['content_url'], content=b'A' * (21 * MB))
        assert sent.status_code == 413 and sent.json()['data']['code'] == 'UPLOAD_TOO_LARGE'

        within = unwrap(await api.post('/uploads/init', json={'original_filename': 'ok.fa', 'expected_size': MB}))
        assert (await api.put(within['content_url'], content=b'A' * MB)).status_code == 200
        after = unwrap(await api.get('/uploads/limits'))
        assert after['used_bytes'] == MB                                  # only the accepted file counts
        files = unwrap(await api.get('/files'))
        names = [f['original_filename'] for f in (files['files'] if isinstance(files, dict) else files)]
        assert names == ['ok.fa']
