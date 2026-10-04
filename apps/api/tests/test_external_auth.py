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
    assert result == {'google_id': '123', 'email': 'test@example.org', 'name': 'Test', 'picture': None}
    assert requests[1].headers['Authorization'] == 'Bearer external-access'


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
