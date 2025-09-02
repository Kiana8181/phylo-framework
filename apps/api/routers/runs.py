from __future__ import annotations
import uuid
import asyncio
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse
from typing import Any, Dict

from apps.api.contracts.loader import get_result_schema, load_spec_from_contracts
from apps.api.clients.method_client import submit_run
from apps.api.services.validate import validate_json, ValidationError
from apps.api.services.progress import soft_progress
from apps.api.services.storage import RUNS, RESULTS

router = APIRouter()

def ok(data, message: str | None = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"status": "success", "message": message, "data": data})

@router.post("/runs")
async def create_run(
    method: str = Query(...),
    params: str = Form("{}"),
    file: UploadFile | None = File(None),
):
    run_id = str(uuid.uuid4())
    RUNS[run_id] = {"status": "RUNNING", "progress": 5, "message": f"Dispatching {method}"}

    # Load spec so we can know if file is required from contracts/ui.json
    spec = load_spec_from_contracts(method)
    requires_file: bool = bool(spec.get("uiHints", {}).get("requiresFile", True))

    if requires_file and file is None:
        RUNS[run_id] = {"status": "ERROR", "message": f"File is required for {method}"}
        raise HTTPException(status_code=400, detail=f"File is required for {method}")

    file_bytes = await file.read() if file else None
    filename = file.filename if file else None
    content_type = file.content_type if (file and file.content_type) else "application/octet-stream"

    async def worker():
        try:
            RUNS[run_id] = {"status": "RUNNING", "progress": 10, "message": f"Submitting to {method}"}
            data = {"params": params}
            files_payload: Dict[str, Any] = {}
            if file_bytes is not None:
                files_payload["file"] = (filename, file_bytes, content_type)

            r = await submit_run(method, data=data, files=files_payload)

            # parse response body
            content_type_resp = r.headers.get("content-type", "")
            if "application/json" in content_type_resp:
                body = r.json()
            else:
                body = {"ok": r.status_code < 400, "raw": r.text}

            if r.status_code >= 400 or not body.get("ok", False):
                msg = body.get("error") or body.get("raw") or f"{method} error (HTTP {r.status_code})"
                RUNS[run_id] = {"status": "ERROR", "progress": 100, "message": msg}
                return

            # Validate result against contracts result.schema.json (if present)
            result_schema = get_result_schema(method)
            if result_schema:
                try:
                    validate_json(body, result_schema)
                except ValidationError as e:
                    msg = f"Invalid {method} result: {e.message}"
                    RUNS[run_id] = {"status": "ERROR", "progress": 100, "message": msg}
                    raise HTTPException(status_code=502, detail=msg)

            RESULTS[run_id] = body
            RUNS[run_id] = {"status": "DONE", "progress": 100, "message": "Finished"}

        except Exception as e:
            RUNS[run_id] = {"status": "ERROR", "progress": 100, "message": f"Internal error: {e}"}

    asyncio.create_task(worker())
    asyncio.create_task(soft_progress(RUNS, run_id))

    return ok({"run_id": run_id})

@router.get("/runs/{run_id}/status")
def run_status(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    # Keep legacy behavior (not wrapped) to avoid breaking the web
    return RUNS[run_id]

@router.get("/runs/{run_id}/result")
def run_result(run_id: str):
    if run_id not in RESULTS:
        raise HTTPException(status_code=404, detail="Result not ready")
    # Keep legacy behavior (not wrapped) to avoid breaking the web
    return RESULTS[run_id]
