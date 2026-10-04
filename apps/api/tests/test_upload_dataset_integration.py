"""Upload -> disk -> metadata -> run reference -> deletion lifecycle and isolation."""
import hashlib
from uuid import UUID, uuid4
import pytest
from apps.api.repositories.file_repository import FileRepository
from apps.api.routers import uploads

pytestmark = pytest.mark.integration
DATA = b'>root\nACGT\n>leaf\nACGA\n'


async def upload(client, content=DATA):
    response = await client.post('/uploads/init', json={'original_filename': 'sample.fasta', 'expected_size': len(content)})
    assert response.status_code == 200, response.text
    init = response.json()
    response = await client.put(init['content_url'], content=content)
    return init, response


async def test_upload_download_checksum_and_soft_delete(client, account, session):
    init, response = await upload(client)
    assert response.status_code == 200, response.text
    data = response.json()
    record = await FileRepository(session).get_by_id(UUID(data['file_id']))
    assert record.file_size == len(DATA)
    assert record.checksum_sha256 == hashlib.sha256(DATA).hexdigest()
    assert await uploads.storage().exists(record.storage_path)
    downloaded = await client.get(f'/datasets/{record.id}/download')
    assert downloaded.content == DATA
    assert 'sample.fasta' in downloaded.headers['content-disposition']
    assert (await client.get(f'/datasets/{record.id}/fasta-id-style')).json()['headers_checked'] == 2
    assert (await client.put(init['content_url'], content=DATA)).status_code == 409
    assert (await client.delete(f'/datasets/{record.id}')).json()['status'] == 'deleted'
    assert not await uploads.storage().exists(record.storage_path)
    assert (await client.delete(f'/datasets/{record.id}')).json()['status'] == 'already_deleted'
    assert (await client.get(f'/datasets/{record.id}/download')).status_code == 410
    assert await FileRepository(session).get_by_id(record.id) is not None
    rerun = await client.post('/runs?method=gctree', json={'file_id': str(record.id)})
    assert rerun.status_code == 409
    assert rerun.json()['data']['code'] == 'DATASET_DELETED'


async def test_other_user_cannot_read_delete_or_run_dataset(client, account):
    init, uploaded = await upload(client)
    file_id = uploaded.json()['file_id']
    other = await client.post('/auth/register', json={'email': 'other@example.org', 'username': 'other', 'password': 'password'})
    client.headers['Authorization'] = f"Bearer {other.json()['access_token']}"
    for path in [f'/datasets/{file_id}/download', f'/datasets/{file_id}/fasta-id-style']:
        assert (await client.get(path)).status_code == 404
    assert (await client.delete(f'/datasets/{file_id}')).status_code == 404
    assert (await client.post('/runs?method=gctree', json={'file_id': file_id})).status_code == 404
    assert (await client.put(init['content_url'], content=DATA)).status_code == 404
    assert (await client.delete(f"/uploads/{init['upload_id']}")).status_code == 204
    client.headers['Authorization'] = f"Bearer {account['access_token']}"
    assert (await client.get(f'/datasets/{file_id}/download')).content == DATA


async def test_active_run_blocks_deletion_then_cancel_frees_dataset(client, account):
    init, uploaded = await upload(client)
    file_id = uploaded.json()['file_id']
    created = await client.post('/runs?method=gctree', json={'file_id': file_id})
    assert created.status_code == 200, created.text
    run_id = created.json()['run_id']
    assert (await client.delete(f'/datasets/{file_id}')).status_code == 409
    assert (await client.delete(f"/uploads/{init['upload_id']}")).status_code == 409
    assert (await client.post(f'/runs/{run_id}/cancel')).status_code == 200
    assert (await client.delete(f'/datasets/{file_id}')).status_code == 200
    assert (await client.get(f'/runs/{run_id}/status')).status_code == 200


@pytest.mark.parametrize('completed', [False, True])
async def test_cancel_upload_idempotent_and_removes_blob(client, account, completed):
    if completed:
        init, response = await upload(client)
        file_id = response.json()['file_id']
    else:
        init = (await client.post('/uploads/init', json={'original_filename': 'a.fa'})).json()
    for _ in range(2):
        assert (await client.delete(f"/uploads/{init['upload_id']}")).status_code == 204
    assert (await client.put(init['content_url'], content=DATA)).status_code == 409
    if completed:
        assert (await client.get(f'/datasets/{file_id}/download')).status_code == 404


async def test_empty_upload_and_actual_stream_quota(client, account, monkeypatch):
    _, empty = await upload(client, b'')
    assert empty.status_code == 400
    monkeypatch.setattr(uploads, 'STORAGE_QUOTA_PER_USER_BYTES', 10)
    too_large = await client.post('/uploads/init', json={'original_filename': 'x', 'expected_size': 11})
    assert too_large.status_code == 413
    init = (await client.post('/uploads/init', json={'original_filename': 'x', 'expected_size': 1})).json()
    assert (await client.put(init['content_url'], content=DATA)).status_code == 413
    assert not list(uploads.storage().base_path.rglob('*.part'))


@pytest.mark.parametrize('path', ['/files', '/uploads/init', '/auth/me'])
async def test_protected_endpoints_require_auth(client, path):
    response = await (client.post(path, json={'original_filename': 'a'}) if path == '/uploads/init' else client.get(path))
    assert response.status_code == 401
