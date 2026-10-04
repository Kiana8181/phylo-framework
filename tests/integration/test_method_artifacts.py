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
