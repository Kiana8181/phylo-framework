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
    body = {'email': 'other@example.org', 'username': 'other', 'password': 'another-password-1'}
    body[field] = value
    response = await client.post('/auth/register', json=body)
    assert response.status_code == 400
    assert 'already' in response.json()['message']


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


# --------------------------------------------------------------------------- #
# Passwordless (Google) accounts and the password policy
# --------------------------------------------------------------------------- #
import os
import subprocess
import sys
from pathlib import Path

from apps.api.auth.password import (
    PASSWORD_MAX_LENGTH,
    UNUSABLE_PASSWORD_HASH,
    hash_password,
    unusable_password_hash,
    verify_password,
)

GOOGLE_IDENTITY = {'email': 'google-user@example.org', 'name': 'G User', 'google_id': '42', 'picture': None}


@pytest.mark.parametrize('stored_hash', ['legacy-empty', 'unusable'])
async def test_empty_password_never_logs_in_to_a_passwordless_account(client, session, stored_hash):
    """Regression: Google-created rows used to hold bcrypt("") and accepted an
    empty password. Neither that legacy row nor the new marker may log in."""
    password_hash = hash_password('') if stored_hash == 'legacy-empty' else unusable_password_hash()
    await UserRepository(session).create_user(
        email='google-user@example.org', username='guser', password_hash=password_hash)
    await session.commit()
    for attempt in ['', ' ', 'guess', UNUSABLE_PASSWORD_HASH]:
        response = await client.post('/auth/login', json={'email': 'google-user@example.org', 'password': attempt})
        assert response.status_code == 401, (attempt, response.text)
        assert response.json()['message'] == 'Incorrect email or password'


async def test_empty_and_overlong_passwords_fail_for_ordinary_accounts(client, account):
    for attempt in ['', 'x' * (PASSWORD_MAX_LENGTH + 1)]:
        response = await client.post('/auth/login', json={'email': 'owner@example.org', 'password': attempt})
        assert response.status_code == 401


def test_verify_password_treats_bad_input_as_a_failed_match():
    assert verify_password('', hash_password('')) is False
    assert verify_password('anything', UNUSABLE_PASSWORD_HASH) is False
    assert verify_password('anything', 'not-a-bcrypt-hash') is False
    assert verify_password('anything', '') is False
    assert verify_password('right-password', hash_password('right-password')) is True


async def test_google_sign_in_creates_an_account_without_a_usable_password(client, session, monkeypatch):
    from apps.api.auth import routers
    monkeypatch.setattr(routers, 'exchange_google_code', AsyncMock(return_value=GOOGLE_IDENTITY))
    response = await client.post('/auth/google', json={'code': 'auth-code'})
    assert response.status_code == 200, response.text
    user = await UserRepository(session).get_by_email('google-user@example.org')
    assert user.password_hash == UNUSABLE_PASSWORD_HASH
    login = await client.post('/auth/login', json={'email': user.email, 'password': ''})
    assert login.status_code == 401
    # Signing in with Google again still works and reuses the same account.
    again = await client.post('/auth/google', json={'code': 'auth-code'})
    assert again.json()['user']['id'] == response.json()['user']['id']


async def test_google_account_can_set_a_password_through_reset(client, session, monkeypatch):
    from apps.api.auth import routers
    monkeypatch.setattr(routers, 'exchange_google_code', AsyncMock(return_value=GOOGLE_IDENTITY))
    monkeypatch.setattr(routers, 'send_email', AsyncMock(return_value=True))
    await client.post('/auth/google', json={'code': 'auth-code'})
    await client.post('/auth/forgot-password', json={'email': GOOGLE_IDENTITY['email']})
    user = await UserRepository(session).get_by_email(GOOGLE_IDENTITY['email'])
    body = {'token': user.password_reset_token, 'new_password': 'chosen-password-1'}
    assert (await client.post('/auth/reset-password', json=body)).status_code == 200
    login = await client.post('/auth/login', json={'email': user.email, 'password': 'chosen-password-1'})
    assert login.status_code == 200


async def test_google_endpoint_rejects_a_raw_token(client, session, monkeypatch):
    """A Google token proves nothing about which application it was issued to."""
    from apps.api.auth import google_oauth, routers
    exchange = AsyncMock(return_value=GOOGLE_IDENTITY)
    verify = AsyncMock(return_value=GOOGLE_IDENTITY)
    monkeypatch.setattr(routers, 'exchange_google_code', exchange)
    monkeypatch.setattr(google_oauth, 'verify_google_token', verify)
    response = await client.post('/auth/google', json={'token': 'token-issued-to-another-app'})
    assert response.status_code == 400
    exchange.assert_not_awaited()
    verify.assert_not_awaited()
    assert await UserRepository(session).get_by_email(GOOGLE_IDENTITY['email']) is None
    assert not hasattr(routers, 'verify_google_token')


@pytest.mark.parametrize('password', ['', 'short', '1234567'])
async def test_register_enforces_minimum_password_length(client, session, password):
    response = await client.post('/auth/register', json={
        'email': 'new@example.org', 'username': 'newuser', 'password': password})
    assert response.status_code == 400
    assert 'at least 8 characters' in response.json()['message']
    assert await UserRepository(session).get_by_email('new@example.org') is None


async def test_register_rejects_overlong_password(client):
    response = await client.post('/auth/register', json={
        'email': 'new@example.org', 'username': 'newuser', 'password': 'x' * (PASSWORD_MAX_LENGTH + 1)})
    assert response.status_code == 400


async def test_reset_enforces_minimum_length_and_keeps_the_token_valid(client, account, session, monkeypatch):
    from apps.api.auth import routers
    monkeypatch.setattr(routers, 'send_email', AsyncMock(return_value=True))
    await client.post('/auth/forgot-password', json={'email': 'owner@example.org'})
    user = await UserRepository(session).get_by_email('owner@example.org')
    token = user.password_reset_token
    weak = await client.post('/auth/reset-password', json={'token': token, 'new_password': 'short'})
    assert weak.status_code == 400
    assert 'at least 8 characters' in weak.json()['message']
    # The old password still works and the token was not consumed.
    assert (await client.post('/auth/login', json={'email': user.email, 'password': 'test-password-123'})).status_code == 200
    strong = await client.post('/auth/reset-password', json={'token': token, 'new_password': 'a-longer-password'})
    assert strong.status_code == 200


async def test_existing_short_password_can_still_log_in(client, session):
    """The minimum applies to choosing a password, not to accounts that predate it."""
    await UserRepository(session).create_user(
        email='legacy@example.org', username='legacy', password_hash=hash_password('abc12'))
    await session.commit()
    response = await client.post('/auth/login', json={'email': 'legacy@example.org', 'password': 'abc12'})
    assert response.status_code == 200


async def test_migration_neutralizes_only_empty_password_hashes(session):
    repo = UserRepository(session)
    normal_hash = hash_password('a-real-password')
    await repo.create_user(email='g@example.org', username='g', password_hash=hash_password(''))
    await repo.create_user(email='n@example.org', username='n', password_hash=normal_hash)
    await repo.create_user(email='u@example.org', username='u', password_hash=UNUSABLE_PASSWORD_HASH)
    await session.commit()

    root = Path(__file__).resolve().parents[3]
    env = {**os.environ, 'DATABASE_URL': session.get_bind().url.render_as_string(hide_password=False)}
    # 011's downgrade is a no-op, so stepping down and up re-runs its upgrade
    # against the rows above; twice, to prove it is idempotent.
    for _ in range(2):
        for command in (['downgrade', '010_display_newick'], ['upgrade', 'head']):
            subprocess.run([sys.executable, '-m', 'alembic', *command], cwd=root, env=env, check=True,
                           capture_output=True)

    session.expire_all()
    assert (await repo.get_by_email('g@example.org')).password_hash == UNUSABLE_PASSWORD_HASH
    assert (await repo.get_by_email('n@example.org')).password_hash == normal_hash
    assert (await repo.get_by_email('u@example.org')).password_hash == UNUSABLE_PASSWORD_HASH
