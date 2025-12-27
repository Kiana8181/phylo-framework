from apps.api.contracts.loader import get_service_routes
from apps.api.config import method_service_url, HTTP_CLIENT_TIMEOUT, SPEC_TIMEOUT
import httpx

async def fetch_remote_spec(method_id: str):
    base = method_service_url(method_id)
    if not base:
        return None
    routes = get_service_routes(method_id)
    url = f"{base.rstrip('/')}{routes['spec']}"
    async with httpx.AsyncClient(timeout=SPEC_TIMEOUT, trust_env=False) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()

async def submit_run(method_id: str, data, files):
    base = method_service_url(method_id)
    if not base:
        raise RuntimeError(f"No service URL configured for method '{method_id}'. Set METHOD_{method_id.upper()}_URL")
    routes = get_service_routes(method_id)
    url = f"{base.rstrip('/')}{routes['run']}"
    async with httpx.AsyncClient(timeout=HTTP_CLIENT_TIMEOUT, trust_env=False) as client:
        return await client.post(url, data=data, files=files)
