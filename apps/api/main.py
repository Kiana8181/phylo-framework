# main.py
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from typing import List, Optional
import uuid, os, json
import httpx
import asyncio

DOWSER_URL = os.getenv("DOWSER_URL", "http://localhost:8001")

app = FastAPI(title="Phylo Orchestrator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# --------------------------
# ApiEnvelope helpers
# --------------------------
def ok(data, message: Optional[str] = None, status_code: int = 200):
    return JSONResponse(
        status_code=status_code,
        content={"status": "success", "message": message, "data": jsonable_encoder(data)},
    )

def err(message: str, status_code: int = 400, data=None):
    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "message": message, "data": jsonable_encoder(data)},
    )

# Normalize ALL FastAPI errors into ApiEnvelope
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    # FastAPI often uses {"detail": "..."} or list for validation errors; keep it readable
    if isinstance(detail, list):
        # try to surface first message if present
        msg = detail[0].get("msg") if detail and isinstance(detail[0], dict) else str(detail)
    elif isinstance(detail, dict):
        msg = detail.get("message") or detail.get("detail") or str(detail)
    else:
        msg = str(detail)
    return err(msg, status_code=exc.status_code)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return err("Validation error", status_code=422, data=exc.errors())

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Keep message terse for clients; details should go to logs if needed
    return err("Internal server error", status_code=500)

# add this helper near your globals
async def _soft_progress(run_id: str, floor: int = 10, ceiling: int = 95, step: int = 5, interval: float = 2.0):
    """
    Optimistic progress ticker. While RUNNING, nudge progress toward `ceiling`.
    Stops automatically once status != RUNNING.
    """
    try:
        while True:
            info = RUNS.get(run_id)
            if not info:
                return
            if info.get("status") != "RUNNING":
                return

            cur = int(info.get("progress") or floor)
            if cur < ceiling:
                RUNS[run_id] = {**info, "progress": min(cur + step, ceiling), "message": info.get("message") or "Processing..."}
            await asyncio.sleep(interval)
    except Exception:
        # never crash the server because of the ticker
        return

# --------------------------
# Models (unchanged semantics)
# --------------------------
class MethodInfo(BaseModel):
    id: str
    name: str
    version: str

class MethodSpec(BaseModel):
    id: str
    name: str
    version: str
    accepts: List[str]
    paramSchema: dict
    uiHints: Optional[dict] = None

METHODS = [
    MethodInfo(id="dowser",     name="Dowser",     version="1.1.0"),
    MethodInfo(id="gctree",     name="GCtree",     version="0.0.0"),
    MethodInfo(id="clonaltree", name="ClonalTree", version="0.0.0"),
    MethodInfo(id="brepphylo",  name="BrepPhylo",  version="0.0.0"),
]

# --------------------------
# Endpoints (same logic; envelope responses)
# --------------------------
@app.get("/methods")
def list_methods():
    return ok(METHODS)

@app.get("/methods/{method_id}/spec")
async def get_spec(method_id: str):
    if method_id == "dowser":
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{DOWSER_URL}/spec")
            r.raise_for_status()
            spec = r.json()
        spec.setdefault("uiHints", {})
        spec["uiHints"]["requiresFile"] = True
        spec["uiHints"]["maxFiles"] = 1
        return ok(MethodSpec(**spec))

    mi = next((m for m in METHODS if m.id == method_id), None)
    if not mi:
        raise HTTPException(status_code=404, detail="Unknown method")
    return ok(
        MethodSpec(
            id=mi.id, name=mi.name, version=mi.version,
            accepts=[
                "text/csv",
                "text/tab-separated-values",
                "application/x-rds",
                "application/x-rda",
                "text/fasta",
            ],
            paramSchema={"type": "object", "properties": {}, "required": []},
            uiHints={"requiresFile": True, "maxFiles": 1},
        )
    )

RUNS: dict[str, dict] = {}
RESULTS: dict[str, dict] = {}

@app.post("/runs")
async def create_run(
    method: str = Query(...),
    params: str = Form("{}"),
    file: UploadFile | None = File(None),
):
    run_id = str(uuid.uuid4())
    RUNS[run_id] = {"status": "RUNNING", "progress": 5, "message": f"Dispatching {method}"}

    # unsupported method → keep existing behavior
    if method != "dowser":
        RUNS[run_id] = {"status": "ERROR", "message": "Unsupported method"}
        return ok({"run_id": run_id})

    if file is None:
        RUNS[run_id] = {"status": "ERROR", "message": "File is required for dowser"}
        raise HTTPException(status_code=400, detail="File is required for dowser")

    # read file now (request ends after return)
    file_bytes = await file.read()
    filename = file.filename
    content_type = file.content_type or "application/octet-stream"
    params_str = params  # keep raw string

    async def worker():
        try:
            # small kick before ticker starts
            RUNS[run_id] = {"status": "RUNNING", "progress": 10, "message": "Submitting to Dowser"}

            data = {"params": params_str}
            files_payload = {"file": (filename, file_bytes, content_type)}

            async with httpx.AsyncClient(timeout=600) as client:
                r = await client.post(f"{DOWSER_URL}/run", data=data, files=files_payload)

            content_type_resp = r.headers.get("content-type", "")
            if "application/json" in content_type_resp:
                body = r.json()
            else:
                body = {"ok": r.status_code < 400, "raw": r.text}

            if r.status_code >= 400 or not body.get("ok", False):
                msg = body.get("error") or body.get("raw") or f"Dowser error (HTTP {r.status_code})"
                RUNS[run_id] = {"status": "ERROR", "progress": 100, "message": msg}
                return

            RESULTS[run_id] = body
            # jump to complete
            RUNS[run_id] = {"status": "DONE", "progress": 100, "message": "Finished"}

        except httpx.HTTPError as e:
            RUNS[run_id] = {"status": "ERROR", "progress": 100, "message": f"Backend error: {e}"}
        except Exception as e:
            RUNS[run_id] = {"status": "ERROR", "progress": 100, "message": f"Internal error: {e}"}

    # start both the long job and the soft progress ticker
    asyncio.create_task(worker())
    asyncio.create_task(_soft_progress(run_id))

    # return immediately
    return ok({"run_id": run_id})

@app.get("/runs/{run_id}/status")
def run_status(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    return RUNS[run_id]

@app.get("/runs/{run_id}/result")
def run_result(run_id: str):
    if run_id not in RESULTS:
        raise HTTPException(status_code=404, detail="Result not ready")
    return RESULTS[run_id]
