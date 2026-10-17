"""Exercise each Python service's own manifest/object-storage implementation."""
import hashlib
import importlib.util
from pathlib import Path
import sys
from unittest.mock import Mock
from uuid import uuid4
import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=['gctree', 'clonaltree'])
def modules(request, monkeypatch):
    def load(name):
        spec = importlib.util.spec_from_file_location(f'{request.param}_{name}', ROOT / 'services' / request.param / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    storage = load('object_storage')
    monkeypatch.setitem(sys.modules, 'object_storage', storage)
    manifest = load('artifact_manifest')
    return storage, manifest


@pytest.mark.integration
def test_method_artifact_upload_metadata_matches_stored_bytes(modules, tmp_path, monkeypatch):
    storage, manifest = modules
    for key, value in {'S3_ENDPOINT_URL': 'http://127.0.0.1:59000', 'S3_ACCESS_KEY_ID': 'phylo_test',
                       'S3_SECRET_ACCESS_KEY': 'phylo_test_secret', 'S3_BUCKET_ARTIFACTS': 'phylo-tests'}.items():
        monkeypatch.setenv(key, value)
    source = tmp_path / 'tree.nwk'
    source.write_bytes(b'(a:1,b:2);')
    run_id, job_id = str(uuid4()), str(uuid4())
    result = manifest.materialize_artifacts({'ok': True, 'figures': 'old', 'extra_b64': 'old', 'artifact_files': [
        {'path': str(source), 'filename': 'unsafe/name.nwk', 'tree_index': '0', 'kind': 'newick', 'content_type': 'text/plain'},
        None, {}, {'path': 'missing-file'},
    ]}, run_id=run_id, job_id=job_id)
    assert result['manifest_version'] == 1
    assert len(result['artifacts']) == 1
    # A declared file that is not on disk is reported, not silently left out;
    # malformed entries (no path at all) are ignored as before.
    assert result['artifact_upload_failures'] == [
        {'filename': 'missing-file', 'error': 'the file the method declared does not exist'}]
    assert 'missing-file' in manifest.storage_failure(result)
    artifact = result['artifacts'][0]
    assert artifact['tree_index'] == 0
    assert artifact['size_bytes'] == len(source.read_bytes())
    assert artifact['checksum_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert 'figures' not in result and 'extra_b64' not in result and 'artifact_files' not in result
    client, bucket = storage._build_client()
    key = artifact['object_key']
    try:
        assert client.get_object(Bucket=bucket, Key=key)['Body'].read() == source.read_bytes()
        assert key.startswith(f'artifacts/{run_id}/{job_id}/')
    finally:
        client.delete_object(Bucket=bucket, Key=key)


def test_manifest_error_paths_and_passthrough(modules, tmp_path, monkeypatch):
    storage, manifest = modules
    assert manifest.materialize_artifacts(None, run_id='r', job_id='j') is None
    with pytest.raises(ValueError):
        manifest.materialize_artifacts({}, run_id='', job_id='j')
    with pytest.raises(FileNotFoundError):
        storage.upload_artifact(tmp_path / 'missing', run_id='r', job_id='j')
    for key in ['S3_ENDPOINT_URL', 'S3_ACCESS_KEY_ID', 'S3_SECRET_ACCESS_KEY', 'S3_BUCKET_ARTIFACTS']:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError, match='incomplete'):
        storage._build_client()
    source = tmp_path / 'a.nwk'
    source.write_text('(a,b);')
    monkeypatch.setattr(manifest, 'upload_artifact', Mock(side_effect=RuntimeError('offline')))
    result = manifest.materialize_artifacts({'artifact_files': [{'path': str(source)}]}, run_id='r', job_id='j')
    assert result['artifacts'] == []
    assert result['manifest_version'] == 1
    # The failed upload is not dropped silently: it is named, and it is the
    # reason the job does not count as finished.
    assert result['artifact_upload_failures'] == [{'filename': 'a.nwk', 'error': 'RuntimeError: offline'}]
    message = manifest.storage_failure(result)
    assert '1 result file(s) could not be saved' in message and 'a.nwk' in message
    failed = manifest.mark_storage_failure(result, message)
    assert failed['ok'] is False and failed['error'] == message
    assert failed['error_code'] == 'ARTIFACT_UPLOAD_FAILED' and failed['manifest_version'] == 1


def test_a_fully_stored_result_reports_no_storage_failure(modules, tmp_path, monkeypatch):
    storage, manifest = modules
    source = tmp_path / 'a.nwk'
    source.write_text('(a,b);')
    monkeypatch.setattr(manifest, 'upload_artifact', Mock(return_value={
        'object_key': 'artifacts/r/j/a.nwk', 'size_bytes': 6, 'checksum_sha256': 'x'}))
    result = manifest.materialize_artifacts({'ok': True, 'artifact_files': [{'path': str(source)}]}, run_id='r', job_id='j')
    assert 'artifact_upload_failures' not in result
    assert manifest.storage_failure(result) is None
    assert manifest.storage_failure(None) is None
    # materialize_artifacts itself blowing up is also a storage failure.
    assert 'could not be saved' in manifest.storage_failure(result, 'ValueError: run_id + job_id are required')
    many = {'artifact_upload_failures': [{'filename': f'f{i}.png'} for i in range(8)]}
    assert 'and 3 more' in manifest.storage_failure(many)


@pytest.mark.integration
async def test_worker_verification_agrees_with_what_the_method_really_stored(modules, tmp_path, monkeypatch):
    """Method upload -> manifest -> worker rows -> check against the real store."""
    import uuid
    from apps.api.services.artifact_service import ArtifactService
    from apps.api.services.artifact_verification import verify_artifacts
    from apps.api.storage.minio_storage import MinIOStorage
    from apps.api.storage.s3_storage import S3Storage

    storage, manifest = modules
    for key, value in {'S3_ENDPOINT_URL': 'http://127.0.0.1:59000', 'S3_ACCESS_KEY_ID': 'phylo_test',
                       'S3_SECRET_ACCESS_KEY': 'phylo_test_secret', 'S3_BUCKET_ARTIFACTS': 'phylo-tests'}.items():
        monkeypatch.setenv(key, value)
    tree = tmp_path / 'tree.nwk'
    tree.write_bytes(b'(a:1,b:2);')
    plot = tmp_path / 'plot.png'
    plot.write_bytes(b'\x89PNG' + b'0' * 2048)
    run_id, job_id = uuid4(), str(uuid4())
    result = manifest.materialize_artifacts({'ok': True, 'artifact_files': [
        {'path': str(tree), 'kind': 'newick'}, {'path': str(plot), 'kind': 'image'}]},
        run_id=str(run_id), job_id=job_id)
    assert manifest.storage_failure(result) is None
    rows = ArtifactService(bucket='phylo-tests').ingest(
        run_id=run_id, method_id='gctree', manifest_artifacts=result['artifacts'])
    stores = [MinIOStorage('127.0.0.1:59000', 'phylo_test', 'phylo_test_secret', 'phylo-tests', secure=False),
              S3Storage('phylo-tests', access_key_id='phylo_test', secret_access_key='phylo_test_secret',
                        endpoint_url='http://127.0.0.1:59000', force_path_style=True)]
    client, bucket = storage._build_client()
    try:
        for store in stores:
            stat = await store.stat(rows[0]['object_key'])
            # The uploader's checksum is recorded on the object itself.
            assert stat.size_bytes == 10 and stat.sha256 == hashlib.sha256(b'(a:1,b:2);').hexdigest()
            report = await verify_artifacts(rows, store, attempts=1, retry_seconds=0)
            assert report.ok and report.checked == 2

        # One object disappears (lost upload, wiped bucket): verification notices.
        client.delete_object(Bucket=bucket, Key=rows[1]['object_key'])
        for store in stores:
            report = await verify_artifacts(rows, store, attempts=1, retry_seconds=0)
            assert [p['filename'] for p in report.problems] == ['plot.png']
            assert report.verified_keys == {rows[0]['object_key']}

        # A manifest that declares a different checksum than the stored object's.
        tampered = [dict(rows[0], checksum_sha256='0' * 64)]
        report = await verify_artifacts(tampered, stores[0], attempts=1, retry_seconds=0)
        assert report.problems[0]['problem'] == 'checksum differs'
    finally:
        for row in rows:
            client.delete_object(Bucket=bucket, Key=row['object_key'])


@pytest.mark.integration
async def test_an_unreachable_store_is_an_error_not_a_missing_file():
    from apps.api.services.artifact_verification import ArtifactStoreUnavailable, verify_artifacts
    import boto3
    from apps.api.storage.s3_storage import S3Storage
    from botocore.config import Config

    down = S3Storage('phylo-tests', access_key_id='x', secret_access_key='y',
                     endpoint_url='http://127.0.0.1:1', force_path_style=True)
    # Same dead endpoint, but give up quickly instead of after the default retries.
    down.s3_client = boto3.client(
        's3', endpoint_url='http://127.0.0.1:1', aws_access_key_id='x', aws_secret_access_key='y',
        region_name='us-east-1',
        config=Config(connect_timeout=1, read_timeout=1, retries={'max_attempts': 1}))
    rows = [{'object_key': 'artifacts/r/j/a.nwk', 'filename': 'a.nwk', 'size_bytes': 1}]
    with pytest.raises(ArtifactStoreUnavailable):
        await verify_artifacts(rows, down, attempts=2, retry_seconds=0)
