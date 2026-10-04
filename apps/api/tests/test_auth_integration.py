"""HTTP authentication against real PostgreSQL, without mocking auth dependencies."""
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from apps.api.auth.jwt_handler import create_access_token, create_refresh_token
from apps.api.repositories.user_repository import UserRepository

pytestmark = pytest.mark.integration


async def test_register_login_refresh_me(client, account):
    assert (await client.get('/auth/me')).json()['id'] == account['user']['id']
    login = await client.post('/auth/login', json={'email': 'owner@example.org', 'password': 'test-password-123'})
    assert login.status_code == 200
    refreshed = await client.post('/auth/refresh', json={'refresh_token': login.json()['refresh_token']})
    assert refreshed.status_code == 200
    assert refreshed.json()['user'] == account['user']
    assert (await client.post('/auth/logout')).status_code == 200


@pytest.mark.parametrize('field,value', [('email', 'owner@example.org'), ('username', 'owner')])
async def test_duplicate_identity(client, account, field, value):
    body = {'email': 'other@example.org', 'username': 'other', 'password': 'secret'}
    body[field] = value
    assert (await client.post('/auth/register', json=body)).status_code == 400


@pytest.mark.parametrize('token', ['garbage', 'expired', 'refresh', 'missing-sub', 'bad-sub'])
async def test_invalid_access_credentials(client, account, token):
    tokens = {
        'garbage': 'garbage',
        'expired': create_access_token({'sub': account['user']['id']}, timedelta(seconds=-60)),
        'refresh': account['refresh_token'],
        'missing-sub': create_access_token({}),
        'bad-sub': create_access_token({'sub': 'not-a-uuid'}),
    }
    response = await client.get('/auth/me', headers={'Authorization': f'Bearer {tokens[token]}'})
    assert response.status_code == 401
    assert response.headers['www-authenticate'] == 'Bearer'
    assert response.json()['status'] == 'error'


async def test_bad_password_and_inactive_user(client, account, session):
    body = {'email': 'owner@example.org', 'password': 'wrong'}
    assert (await client.post('/auth/login', json=body)).status_code == 401
    await UserRepository(session).update(UUID(account['user']['id']), is_active=False)
    body['password'] = 'test-password-123'
    assert (await client.post('/auth/login', json=body)).status_code == 403
    assert (await client.get('/auth/me')).status_code == 401
    assert (await client.post('/auth/refresh', json={'refresh_token': account['refresh_token']})).status_code == 401


@pytest.mark.parametrize('kind', ['access', 'bad-sub', 'missing-sub', 'invalid'])
async def test_invalid_refresh_rejected_without_500(client, account, kind):
    token = {'access': account['access_token'], 'bad-sub': create_refresh_token({'sub': 'bad'}),
             'missing-sub': create_refresh_token({}), 'invalid': 'broken'}[kind]
    assert (await client.post('/auth/refresh', json={'refresh_token': token})).status_code == 401


async def test_password_reset_single_use_and_no_enumeration(client, account, session, monkeypatch):
    from apps.api.auth import routers
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(routers, 'send_email', send)
    existing = await client.post('/auth/forgot-password', json={'email': 'owner@example.org'})
    absent = await client.post('/auth/forgot-password', json={'email': 'absent@example.org'})
    assert existing.json() == absent.json()
    send.assert_awaited_once()
    user = await UserRepository(session).get_by_email('owner@example.org')
    body = {'token': user.password_reset_token, 'new_password': 'changed-password'}
    assert (await client.post('/auth/reset-password', json=body)).status_code == 200
    assert (await client.post('/auth/reset-password', json=body)).status_code == 400
    assert (await client.post('/auth/login', json={'email': user.email, 'password': 'changed-password'})).status_code == 200
    assert (await client.post('/auth/login', json={'email': user.email, 'password': 'test-password-123'})).status_code == 401


async def test_validation_error_envelope(client):
    response = await client.post('/auth/register', json={'email': 'invalid', 'username': 'x', 'password': 'x'})
    assert response.status_code == 422
    assert response.json()['status'] == 'error'
    assert response.json()['data']
