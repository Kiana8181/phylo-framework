"""Google HTTP boundaries are simulated; no mail or identity provider is contacted."""
from urllib.parse import parse_qs, urlparse
import httpx
import pytest
from fastapi import HTTPException
from apps.api.auth import google_oauth as google


@pytest.fixture
def google_http(monkeypatch):
    monkeypatch.setattr(google, 'GOOGLE_CLIENT_ID', 'test-client')
    monkeypatch.setattr(google, 'GOOGLE_CLIENT_SECRET', 'test-secret')
    monkeypatch.setattr(google, 'GOOGLE_REDIRECT_URI', 'http://test/auth/callback')
    responses = []
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return httpx.Response(response[0], json=response[1])
    monkeypatch.setattr(google.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    return responses, requests


def test_oauth_url_contains_encoded_redirect_and_scope(google_http):
    url = urlparse(google.get_google_oauth_url())
    assert url.hostname == 'accounts.google.com'
    query = parse_qs(url.query)
    assert query['redirect_uri'] == ['http://test/auth/callback']
    assert query['scope'] == ['openid email profile']


async def test_exchange_uses_access_token_and_maps_identity(google_http):
    responses, requests = google_http
    responses.extend([(200, {'access_token': 'external-access'}), (200, {'sub': '123', 'email': 'test@example.org', 'name': 'Test'})])
    result = await google.exchange_google_code('code')
    # Google said nothing about the address being confirmed: it is not assumed.
    assert result == {'google_id': '123', 'email': 'test@example.org', 'name': 'Test', 'picture': None,
                      'email_verified': False}
    assert requests[1].headers['Authorization'] == 'Bearer external-access'


@pytest.mark.parametrize('reported,expected', [(True, True), ('true', True), (False, False), ('false', False), (None, False)])
async def test_google_identity_carries_whether_google_confirmed_the_address(google_http, reported, expected):
    responses, _ = google_http
    info = {'sub': '1', 'email': 'a@example.org'}
    if reported is not None:
        info['email_verified'] = reported
    responses.extend([(200, {'access_token': 't'}), (200, info)])
    assert (await google.exchange_google_code('code'))['email_verified'] is expected


def test_authorization_url_carries_the_state(monkeypatch):
    from urllib.parse import parse_qs, urlparse
    monkeypatch.setattr(google, 'GOOGLE_CLIENT_ID', 'client')
    query = parse_qs(urlparse(google.get_google_oauth_url('signed-state-value')).query)
    assert query['state'] == ['signed-state-value']
    assert 'state' not in parse_qs(urlparse(google.get_google_oauth_url()).query)


@pytest.mark.parametrize('response', [(400, {}), (200, {}), httpx.ConnectError('offline')])
async def test_failed_exchange_returns_no_identity(google_http, response):
    google_http[0].append(response)
    assert await google.exchange_google_code('bad') is None


@pytest.mark.parametrize('response', [(401, {}), httpx.ConnectError('offline')])
async def test_invalid_provider_token(google_http, response):
    google_http[0].append(response)
    assert await google.verify_google_token('bad') is None


async def test_unconfigured_provider_rejected(monkeypatch):
    monkeypatch.setattr(google, 'GOOGLE_CLIENT_ID', '')
    for operation in [google.verify_google_token, google.exchange_google_code]:
        with pytest.raises(HTTPException) as exc:
            await operation('token')
        assert exc.value.status_code == 500
    with pytest.raises(HTTPException):
        google.get_google_oauth_url()
