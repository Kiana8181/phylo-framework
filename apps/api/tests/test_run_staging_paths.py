from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
from apps.api.services import run_staging as staging
from apps.api.storage.local_storage import LocalStorage


@pytest.fixture
def shared(tmp_path, monkeypatch):
    monkeypatch.setenv('HOST_RUNTIME_SHARED_ROOT', str(tmp_path))
    monkeypatch.setenv('STORAGE_LOCAL_PATH', str(tmp_path))
    monkeypatch.setenv('METHOD_SERVICE_FILE_PREFIX', '/runtime/storage')
    return tmp_path


async def test_workspace_cleanup_only_removes_owned_workspace(shared):
    run_id = uuid4()
    work = await staging.run_work_dir(run_id)
    (work / 'result').write_text('temporary')
    staging.cleanup_workspace(work, uuid4())
    assert work.exists()
    staging.cleanup_workspace(shared, run_id)
    assert shared.exists()
    staging.cleanup_workspace(work, run_id)
    assert not work.exists()
    staging.cleanup_workspace(work, run_id)
    staging.cleanup_workspace(None, run_id)


def test_shared_paths_cannot_escape_mount(shared, tmp_path):
    source = shared / 'input.tsv'
    source.write_text('data')
    storage = LocalStorage(str(shared))
    assert staging.resolve_storage_path_under_shared_mount('input.tsv', storage) == source
    assert staging.to_container_path(source) == '/runtime/storage/input.tsv'
    outside = shared.parent / f'{uuid4()}.tsv'
    try:
        outside.write_text('private')
        assert staging.resolve_storage_path_under_shared_mount(str(outside), storage) is None
        with pytest.raises(ValueError):
            staging.to_container_path(outside)
    finally:
        outside.unlink()
    assert staging.resolve_storage_path_under_shared_mount('missing.tsv', storage) is None


async def test_remote_object_staged_as_bytes_with_suffix(shared):
    storage = AsyncMock()
    storage.download.return_value = b'\x00sequence\xff'
    work = await staging.run_work_dir(uuid4())
    path = await staging.stage_storage_path_to_workspace('datasets/input.TSV', work, storage)
    assert path.parent == work
    assert path.suffix == '.tsv'
    assert path.read_bytes() == b'\x00sequence\xff'
    storage.download.assert_awaited_once_with('datasets/input.TSV')
