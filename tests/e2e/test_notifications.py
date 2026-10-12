"""Run notifications through the whole stack: API -> worker -> outbox -> SMTP.

Requires docker-compose.test.yml --profile full, which includes a local test
mail server (tests/support/smtp_sink.py) that the API and the worker send to.
Every test uses its own freshly registered address, so mail is matched by
recipient and tests do not see each other's messages.
"""
import asyncio
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
PARAMS = json.loads((ROOT / 'tests/fixtures/scientific-params.json').read_text())
SAMPLE = ROOT / 'apps/web/public/samples/ExampleAirr_clone_3128.tsv'
API = 'http://127.0.0.1:58000'
MAIL = 'http://127.0.0.1:58025'
pytestmark = pytest.mark.scientific


def unwrap(response):
    response.raise_for_status()
    value = response.json()
    return value['data'] if isinstance(value, dict) and value.get('status') == 'success' and 'data' in value else value


class Account:
    """A new user with one uploaded file."""

    def __init__(self, api: httpx.AsyncClient):
        self.api = api
        self.email = f'{uuid4().hex}@example.org'

    async def register(self, content: bytes = None, filename: str = None):
        account = unwrap(await self.api.post('/auth/register', json={
            'email': self.email, 'username': self.email.split('@')[0], 'password': 'e2e-password'}))
        self.api.headers['Authorization'] = f"Bearer {account['access_token']}"
        init = unwrap(await self.api.post('/uploads/init', json={
            'original_filename': filename or SAMPLE.name, 'mime_type': 'text/tab-separated-values'}))
        uploaded = unwrap(await self.api.put(init['content_url'], content=content or SAMPLE.read_bytes()))
        self.file_id = uploaded['file_id']
        return self

    async def start(self, method: str) -> str:
        created = unwrap(await self.api.post(f'/runs?method={method}', json={'file_id': self.file_id, 'params': PARAMS[method]}))
        return created['run_id']

    async def wait(self, run_id: str, timeout: float = 300) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = unwrap(await self.api.get(f'/runs/{run_id}/status'))
            if status['status'] in ('DONE', 'ERROR', 'CANCELLED'):
                return status
            await asyncio.sleep(0.3)
        raise AssertionError(f'run {run_id} did not finish: {status}')


async def mail_for(address: str) -> list[dict]:
    async with httpx.AsyncClient(base_url=MAIL, timeout=10, trust_env=False) as mail:
        messages = (await mail.get('/messages')).json()['messages']
    return [m for m in messages if address in m['recipients']]


async def wait_for_mail(address: str, count: int = 1, timeout: float = 30) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        messages = await mail_for(address)
        if len(messages) >= count:
            return messages
        await asyncio.sleep(0.3)
    raise AssertionError(f'expected {count} email(s) for {address}, found {len(await mail_for(address))}')


async def set_mail_mode(mode: str) -> None:
    async with httpx.AsyncClient(base_url=MAIL, timeout=10, trust_env=False) as mail:
        (await mail.post('/mode', json={'mode': mode})).raise_for_status()


@pytest.fixture
async def api():
    async with httpx.AsyncClient(base_url=API, timeout=60, trust_env=False) as client:
        yield client


async def test_a_finished_run_sends_its_owner_exactly_one_email(api):
    user = await Account(api).register()
    run_id = await user.start('clonaltree')
    assert (await user.wait(run_id))['status'] == 'DONE'
    (message,) = await wait_for_mail(user.email)
    assert message['subject'] == 'Your ClonalTree (B-DIVE) run has finished'
    assert message['from'] == 'Phylo Runner <phylo@tests.example>'
    assert f'http://127.0.0.1:53000/dashboard?runId={run_id}' in message['text']
    assert SAMPLE.name in message['text'] and run_id in message['html']
    await asyncio.sleep(4)                                   # several delivery cycles later: still one
    assert len(await mail_for(user.email)) == 1


async def test_a_failed_run_sends_one_email_with_the_reason(api):
    user = await Account(api).register(content=b'this is not a table of sequences\n', filename='broken.tsv')
    run_id = await user.start('dowser')
    status = await user.wait(run_id)
    assert status['status'] == 'ERROR', status
    (message,) = await wait_for_mail(user.email)
    assert message['subject'] == 'Your Dowser run failed'
    assert 'Reason:' in message['text'] and 'broken.tsv' in message['text']
    await asyncio.sleep(3)
    assert len(await mail_for(user.email)) == 1


async def test_a_cancelled_run_sends_no_email(api):
    user = await Account(api).register()
    run_id = await user.start('dowser')
    await asyncio.sleep(1.5)                                 # let it start, then cancel it
    unwrap(await api.post(f'/runs/{run_id}/cancel'))
    status = await user.wait(run_id)
    if status['status'] != 'CANCELLED':
        pytest.skip(f"the run finished before the cancel landed ({status['status']})")
    await asyncio.sleep(5)                                   # ample time for any email to be sent
    assert await mail_for(user.email) == []


async def test_a_mail_outage_does_not_touch_the_run_and_the_email_follows_later(api):
    """SMTP down while the run finishes: the run is DONE regardless; the email
    arrives, once, after the server is back."""
    user = await Account(api).register()
    await set_mail_mode('refuse')
    try:
        run_id = await user.start('clonaltree')
        status = await user.wait(run_id)
        assert status['status'] == 'DONE', status          # unaffected by the mail server
        trees = unwrap(await api.get(f'/runs/{run_id}/trees'))
        assert (trees['trees'] if isinstance(trees, dict) else trees)
        await asyncio.sleep(3)                               # at least one failed delivery attempt
        assert await mail_for(user.email) == []
    finally:
        await set_mail_mode('ok')
    (message,) = await wait_for_mail(user.email, timeout=40)
    assert message['subject'].endswith('run has finished')
    assert unwrap(await api.get(f'/runs/{run_id}/status'))['status'] == 'DONE'
    await asyncio.sleep(5)
    assert len(await mail_for(user.email)) == 1              # retried, not duplicated
