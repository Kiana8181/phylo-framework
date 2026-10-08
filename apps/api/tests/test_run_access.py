"""Every run and artifact route requires a signed-in owner (or an administrator).

Covers the rule that a run's UUID alone grants nothing: no token is 401, another
user's token is 403, and a run without an owner is visible to administrators only.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from apps.api.repositories.artifact_repository import ArtifactRepository
from apps.api.repositories.run_repository import RunRepository
from apps.api.repositories.user_repository import UserRepository
from apps.api.routers import artifacts
from apps.api.routers import runs as runs_router

pytestmark = pytest.mark.integration


async def _run_with_artifact(session, user_id):
    run = await RunRepository(session).create_run(method_id="gctree", params={}, user_id=user_id)
    key = f"runs/{run.id}/job.log"
    await artifacts.storage().upload(b"log", key)
    rows = await ArtifactRepository(session).replace_for_run(run.id, [{
        "object_key": key, "filename": "job.log", "storage_backend": "local",
        "size_bytes": 3, "artifact_kind": "log", "is_previewable": True,
    }])
    await session.commit()
    return str(run.id), str(rows[0].id)


def _get_paths(run_id: str, artifact_id: str) -> list[str]:
    return [
        f"/runs/{run_id}/status",
        f"/runs/{run_id}/result",
        f"/runs/{run_id}/trees",
        f"/runs/{run_id}/trees/{uuid4()}",
        f"/runs/{run_id}/same-dataset",
        f"/runs/{run_id}/artifacts",
        f"/artifacts/{artifact_id}/download",
        f"/artifacts/{artifact_id}/preview",
    ]


def _post_paths(run_id: str) -> list[str]:
    return [f"/runs/{run_id}/cancel", f"/runs/{run_id}/cancel-queued"]


async def _login_as_other(client, *, admin: bool, session) -> None:
    other = await client.post("/auth/register", json={
        "email": "other@example.org", "username": "other", "password": "other-password-1",
    })
    assert other.status_code == 201, other.text
    if admin:
        await UserRepository(session).update(UUID(other.json()["user"]["id"]), is_admin=True)
        await session.commit()
    client.headers["Authorization"] = f"Bearer {other.json()['access_token']}"


async def test_every_run_route_requires_a_token(client, account, session):
    run_id, artifact_id = await _run_with_artifact(session, UUID(account["user"]["id"]))
    client.headers.pop("Authorization")
    for path in _get_paths(run_id, artifact_id) + ["/runs", "/runs/current", "/runs/dashboard"]:
        response = await client.get(path)
        assert response.status_code == 401, (path, response.text)
        assert response.headers["www-authenticate"] == "Bearer"
    for path in _post_paths(run_id):
        assert (await client.post(path)).status_code == 401, path


async def test_create_run_requires_a_token(client, session, monkeypatch):
    # A file-less method with a configured service URL: before this rule, such a
    # request created an ownerless run that no quota applied to.
    monkeypatch.setattr(runs_router, "method_service_url", lambda method: "http://method.test")
    monkeypatch.setattr(runs_router, "get_ui_hints", lambda method: {"requiresFile": False})
    response = await client.post("/runs", params={"method": "gctree"}, json={"params": {}})
    assert response.status_code == 401
    assert await RunRepository(session).get_by_method("gctree") == []


async def test_created_run_belongs_to_the_caller(client, account, session, monkeypatch):
    monkeypatch.setattr(runs_router, "method_service_url", lambda method: "http://method.test")
    monkeypatch.setattr(runs_router, "get_ui_hints", lambda method: {"requiresFile": False})
    response = await client.post("/runs", params={"method": "gctree"}, json={"params": {}})
    assert response.status_code == 200, response.text
    run = await RunRepository(session).get_by_id(UUID(response.json()["run_id"]))
    assert str(run.user_id) == account["user"]["id"]


async def test_other_user_is_denied_everywhere(client, account, session):
    run_id, artifact_id = await _run_with_artifact(session, UUID(account["user"]["id"]))
    await _login_as_other(client, admin=False, session=session)
    for path in _get_paths(run_id, artifact_id):
        assert (await client.get(path)).status_code == 403, path
    for path in _post_paths(run_id):
        assert (await client.post(path)).status_code == 403, path


async def test_admin_can_read_another_users_run(client, account, session):
    run_id, artifact_id = await _run_with_artifact(session, UUID(account["user"]["id"]))
    await _login_as_other(client, admin=True, session=session)
    assert (await client.get(f"/runs/{run_id}/status")).status_code == 200
    assert (await client.get(f"/runs/{run_id}/artifacts")).status_code == 200
    assert (await client.get(f"/artifacts/{artifact_id}/download")).content == b"log"


async def test_ownerless_run_is_admin_only(client, account, session):
    run_id, artifact_id = await _run_with_artifact(session, None)

    # A signed-in ordinary user who knows the UUID.
    for path in _get_paths(run_id, artifact_id):
        assert (await client.get(path)).status_code == 403, path
    assert (await client.post(f"/runs/{run_id}/cancel")).status_code == 403

    # Nobody signed in.
    token = client.headers.pop("Authorization")
    for path in (f"/runs/{run_id}/status", f"/artifacts/{artifact_id}/download"):
        assert (await client.get(path)).status_code == 401, path

    # An administrator.
    client.headers["Authorization"] = token
    await UserRepository(session).update(UUID(account["user"]["id"]), is_admin=True)
    await session.commit()
    assert (await client.get(f"/runs/{run_id}/status")).status_code == 200
    assert (await client.get(f"/artifacts/{artifact_id}/download")).status_code == 200


async def test_unknown_run_is_404_for_a_signed_in_user(client, account):
    assert (await client.get(f"/runs/{uuid4()}/status")).status_code == 404
    assert (await client.get(f"/artifacts/{uuid4()}/download")).status_code == 404
