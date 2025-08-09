from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import uuid

app = FastAPI(title="Phylo Orchestrator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
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
    MethodInfo(id="dowser", name="Dowser", version="1.0.0"),
    MethodInfo(id="gctree", name="GCtree", version="0.1.0"),
    MethodInfo(id="clonaltree", name="ClonalTree", version="0.1.0"),
    MethodInfo(id="brepphylo", name="BrepPhylo", version="0.1.0"),
]

DOWSER_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "clone_field": {"type": "string", "title": "Clone field", "default": "clone_id"},
        "germline_db": {"type": "string", "title": "Germline DB", "description": "Path or preset key"},
        "max_depth": {"type": "integer", "title": "Max depth", "default": 100},
        "test_isotype_switch": {"type": "boolean", "title": "Test isotype switching", "default": True},
        "tree_model": {"enum": ["ml", "mp", "nj"], "title": "Tree model", "default": "ml"},
    },
    "required": ["clone_field", "tree_model"]
}
UI_HINTS = {
    "order": ["clone_field", "tree_model", "max_depth", "test_isotype_switch", "germline_db"]
}

@app.get("/methods", response_model=List[MethodInfo])
def list_methods():
    return METHODS

@app.get("/methods/{method_id}/spec", response_model=MethodSpec)
def get_spec(method_id: str):
    if method_id == "dowser":
        return MethodSpec(
            id="dowser",
            name="Dowser",
            version="1.0.0",
            accepts=["text/csv","text/tab-separated-values","application/x-rds","application/x-rda","text/fasta"],
            paramSchema=DOWSER_SCHEMA,
            uiHints=UI_HINTS
        )
    mi = next((m for m in METHODS if m.id == method_id), None)
    if not mi:
        raise HTTPException(status_code=404, detail="Unknown method")
    return MethodSpec(
        id=mi.id, name=mi.name, version=mi.version,
        accepts=["text/csv","text/tab-separated-values","text/fasta"],
        paramSchema={"type": "object", "properties": {}, "required": []},
    )

RUNS = {}

@app.post("/runs")
async def create_run(method: str, params: str = Form(...), files: List[UploadFile] = File(default=[])):
    run_id = str(uuid.uuid4())
    RUNS[run_id] = {"status": "RUNNING", "progress": 5, "message": f"Queued for {method}"}
    return {"run_id": run_id}

@app.get("/runs/{run_id}/status")
def run_status(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    r = RUNS[run_id]
    if r["status"] == "RUNNING" and r.get("progress", 0) < 100:
        r["progress"] += 30
        if r["progress"] >= 100:
            r["status"] = "DONE"
            r["message"] = "Finished"
    return r
