# main.py (only the create_run endpoint changed)
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import uuid, os, json
import httpx

DOWSER_URL = os.getenv("DOWSER_URL", "http://localhost:8001")

app = FastAPI(title="Phylo Orchestrator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

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
    MethodInfo(id="dowser",     name="Dowser",     version="dynamic"),
    MethodInfo(id="gctree",     name="GCtree",     version="0.1.0"),
    MethodInfo(id="clonaltree", name="ClonalTree", version="0.1.0"),
    MethodInfo(id="brepphylo",  name="BrepPhylo",  version="0.1.0"),
]

@app.get("/methods", response_model=List[MethodInfo])
def list_methods():
    return METHODS

@app.get("/methods/{method_id}/spec", response_model=MethodSpec)
async def get_spec(method_id: str):
    if method_id == "dowser":
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{DOWSER_URL}/spec")
            r.raise_for_status()
            spec = r.json()
        spec.setdefault("uiHints", {})
        spec["uiHints"]["requiresFile"] = True
        spec["uiHints"]["maxFiles"] = 1
        return MethodSpec(**spec)

    mi = next((m for m in METHODS if m.id == method_id), None)
    if not mi:
        raise HTTPException(status_code=404, detail="Unknown method")
    return MethodSpec(
        id=mi.id, name=mi.name, version=mi.version,
        accepts=["text/csv","text/tab-separated-values","application/x-rds","application/x-rda","text/fasta"],
        paramSchema={"type":"object","properties":{},"required":[]},
        uiHints={"requiresFile": True, "maxFiles": 1},
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

    try:
        if method != "dowser":
            RUNS[run_id] = {"status": "ERROR", "message": "Unsupported method"}
            return {"run_id": run_id}

        if file is None:
            RUNS[run_id] = {"status": "ERROR", "message": "File is required for dowser"}
            raise HTTPException(status_code=400, detail="File is required for dowser")

        data = {"params": params}
        files_payload = {
            "file": (file.filename, await file.read(), file.content_type or "application/octet-stream")
        }

        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(f"{DOWSER_URL}/run", data=data, files=files_payload)

        # Do NOT raise_for_status; try to parse body either way
        content_type = r.headers.get("content-type", "")
        body = None
        if "application/json" in content_type:
            body = r.json()
        else:
            body = {"ok": r.status_code < 400, "raw": r.text}

        if r.status_code >= 400 or not body.get("ok", False):
            msg = body.get("error") or body.get("raw") or f"Dowser error (HTTP {r.status_code})"
            RUNS[run_id] = {"status": "ERROR", "progress": 100, "message": msg}
            raise HTTPException(status_code=502, detail=msg)

        RESULTS[run_id] = body
        RUNS[run_id] = {"status": "DONE", "progress": 100, "message": "Finished"}
        return {"run_id": run_id}

    except httpx.HTTPError as e:
        RUNS[run_id] = {"status": "ERROR", "message": f"Backend error: {e}"}
        raise HTTPException(status_code=502, detail=str(e)) from e

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
