"""Private run outputs must stay private even when their UUID is known."""
from uuid import UUID
import pytest
from apps.api.repositories.run_repository import RunRepository
from apps.api.repositories.artifact_repository import ArtifactRepository
from apps.api.routers import artifacts

pytestmark = pytest.mark.integration


@pytest.fixture
async def private_output(client, account, session):
    run = await RunRepository(session).create_run(method_id='gctree', params={}, user_id=UUID(account['user']['id']))
    await artifacts.storage().upload(b'private log', 'runs/private/job.log')
    rows = await ArtifactRepository(session).replace_for_run(run.id, [{
        'object_key': 'runs/private/job.log', 'filename': 'job.log', 'storage_backend': 'local',
        'size_bytes': 11, 'artifact_kind': 'log', 'is_previewable': True,
    }])
    await session.commit()
    return str(run.id), str(rows[0].id)


async def test_owner_can_list_download_and_preview_roleless_artifact(client, private_output):
    run_id, artifact_id = private_output
    listing = await client.get(f'/runs/{run_id}/artifacts')
    assert listing.status_code == 200
    assert [a['id'] for a in listing.json()['artifacts']] == [artifact_id]
    assert 'object_key' not in listing.text
    for suffix in ['download', 'preview']:
        response = await client.get(f'/artifacts/{artifact_id}/{suffix}')
        assert response.status_code == 200
        assert response.content == b'private log'


@pytest.mark.parametrize('identity,expected', [('anonymous', 401), ('other', 403)])
async def test_private_runs_and_artifacts_deny_nonowners(client, private_output, identity, expected):
    run_id, artifact_id = private_output
    if identity == 'anonymous':
        client.headers.pop('Authorization')
    else:
        other = await client.post('/auth/register', json={'email': 'other@example.org', 'username': 'other', 'password': 'password'})
        client.headers['Authorization'] = f"Bearer {other.json()['access_token']}"
    for path in [f'/runs/{run_id}/status', f'/runs/{run_id}/result', f'/runs/{run_id}/trees',
                 f'/runs/{run_id}/artifacts', f'/artifacts/{artifact_id}/download', f'/artifacts/{artifact_id}/preview']:
        response = await client.get(path)
        assert response.status_code == expected, (path, response.text)
    assert (await client.post(f'/runs/{run_id}/cancel')).status_code == expected
