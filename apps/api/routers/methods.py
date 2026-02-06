from __future__ import annotations
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from apps.api.contracts.loader import (
    list_methods_from_contracts,
    load_spec_from_contracts,
)
from apps.api.config import CONTRACTS_DIR

router = APIRouter()

def ok(data, message: str | None = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"status": "success", "message": message, "data": data})

@router.get("/methods")
async def list_methods():
    """List all available methods from contracts."""
    return ok(list_methods_from_contracts())

@router.get("/methods/{method_id}/spec")
async def get_spec(method_id: str):
    """
    Get method spec from contracts only (no remote service calls).
    All spec information should be stored in packages/contracts/methods/{method_id}/
    """
    # Check if method exists in contracts
    method_dir = CONTRACTS_DIR / "methods" / method_id
    if not method_dir.exists() or not method_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Method '{method_id}' not found in contracts"
        )
    
    # Load spec from contracts
    spec = load_spec_from_contracts(method_id)
    
    if not spec:
        raise HTTPException(
            status_code=404,
            detail=f"Spec for method '{method_id}' could not be loaded"
        )
    
    return ok(spec)
