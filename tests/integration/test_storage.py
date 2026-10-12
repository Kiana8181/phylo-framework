"""The same behavioral contract for disk, boto3 S3, and the MinIO SDK."""
from io import BytesIO
from uuid import uuid4
import pytest
from apps.api.storage.local_storage import LocalStorage
from apps.api.storage.s3_storage import S3Storage
from apps.api.storage.minio_storage import MinIOStorage


@pytest.fixture(params=['local', 's3', 'minio'])
def backend(request, tmp_path):
    if request.param == 'local':
        return LocalStorage(str(tmp_path / 'objects'))
    bucket = 'phylo-tests'
    s3 = S3Storage(bucket, access_key_id='phylo_test', secret_access_key='phylo_test_secret',
                   endpoint_url='http://127.0.0.1:59000', force_path_style=True)
    if not s3.s3_client.list_buckets()['Buckets']:
        s3.s3_client.create_bucket(Bucket=bucket)
    if request.param == 's3':
        return s3
    return MinIOStorage('127.0.0.1:59000', 'phylo_test', 'phylo_test_secret', bucket, secure=False)


@pytest.mark.integration
async def test_storage_contract(backend, tmp_path):
    key = f'{uuid4()}/input.fa'
    moved = key + '.moved'
    file_key = key + '.disk'
    try:
        assert await backend.upload(b'ACGT\nACGA', key, 'text/plain') == key
        assert await backend.exists(key)
        assert (await backend.stat(key)).size_bytes == 9
        assert await backend.stat(key + '.absent') is None
        assert await backend.download(key) == b'ACGT\nACGA'
        chunks = [c async for c in backend.stream_download(key, chunk_size=3)]
        assert chunks == [b'ACG', b'T\nA', b'CGA']
        assert await backend.move(key, moved) == moved
        assert not await backend.exists(key)
        assert await backend.download(moved) == b'ACGT\nACGA'
        local = tmp_path / 'source'
        local.write_bytes(b'from-disk')
        await backend.upload_file(str(local), file_key, 'text/plain')
        assert await backend.download(file_key) == b'from-disk'
        assert await backend.get_url(file_key)
        if backend.get_storage_type() != 'local':
            import httpx
            url = await backend.get_url(file_key, expires_in=60)
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.get(url)
            assert response.status_code == 200
            assert response.content == b'from-disk'
        assert await backend.delete(moved)
        assert not await backend.exists(moved)
        with pytest.raises(FileNotFoundError):
            await backend.download(moved)
        with pytest.raises(FileNotFoundError):
            _ = [c async for c in backend.stream_download(moved)]
    finally:
        for path in (key, moved, file_key):
            await backend.delete(path)


async def test_local_binary_stream_upload(tmp_path):
    storage = LocalStorage(str(tmp_path / 'objects'))
    stream = BytesIO(b'ACGT')
    await storage.upload(stream, 'a.fa')
    assert await storage.download('a.fa') == b'ACGT'
    assert stream.tell() == 0


@pytest.mark.parametrize('key', ['../escape', 'nested/../../escape'])
async def test_local_storage_rejects_path_escape(tmp_path, key):
    storage = LocalStorage(str(tmp_path / 'objects'))
    with pytest.raises(ValueError):
        await storage.upload(b'bad', key)
    assert not (tmp_path / 'escape').exists()
