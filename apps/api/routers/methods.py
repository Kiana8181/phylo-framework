from __future__ import annotations
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from apps.api.contracts.loader import (
    list_methods_from_contracts,
    load_spec_from_contracts,
    get_param_schema,
)
from apps.api.clients.method_client import fetch_remote_spec

router = APIRouter()

def ok(data, message: str | None = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"status": "success", "message": message, "data": data})

@router.get("/methods")
async def list_methods():
    return ok(list_methods_from_contracts())

@router.get("/methods/{method_id}/spec")
async def get_spec(method_id: str):
    # Try remote spec first (if METHOD_<ID>_URL is set), then fill/override from contracts
    remote = await fetch_remote_spec(method_id)  # may be None if no URL configured
    local = load_spec_from_contracts(method_id)

    if remote:
        # If a local param.schema.json exists, prefer it (source of truth)
        param_schema = get_param_schema(method_id)
        merged = {**remote}
        if param_schema:
            merged["paramSchema"] = param_schema
        # Ensure basic fields from local if remote misses them
        for k in ("id", "name", "version", "accepts", "uiHints"):
            if k not in merged and k in local:
                merged[k] = local[k]
        return ok(merged)

    # No remote service—serve from contracts only
    return ok(local)
