from __future__ import annotations

import os
import json
import uuid
import traceback
from typing import Dict, Any, Optional
from datetime import datetime

import aiofiles
import httpx
from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form, Query, HTTPException

from apps.api.contracts.loader import get_service_routes
from apps.api.config import method_service_url

router = APIRouter(prefix="/runs", tags=["runs"])

DEFAULT_RUNS_DIR = os.path.join(os.getcwd(), "runtime", "runs")
RUNS_DIR = os.environ.get("RUNS_DIR", DEFAULT_RUNS_DIR)

def _ensure_dir(path: str) -> str:
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except PermissionError:
        fallback = DEFAULT_RUNS_DIR
        os.makedirs(fallback, exist_ok=True)
        return fallback

RUNS_DIR = _ensure_dir(RUNS_DIR)

RUNS: Dict[str, Dict[str, Any]] = {}

STAT_PENDING = "PENDING"
STAT_RUNNING = "RUNNING"
STAT_DONE    = "DONE"
STAT_ERROR   = "ERROR"

def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"

def _public_status(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": rec.get("status", STAT_PENDING),
        "progress": rec.get("progress", 0),
        "message": rec.get("message"),
    }

# -------------------------
# Routes
# -------------------------

@router.post("")
async def create_run(
    background: BackgroundTasks,
    method: str = Query(..., description="Method ID (e.g., 'dowser')"),
    params: str = Form("{}", description="JSON string of parameters"),
    file: UploadFile | None = File(None),
):
    base = method_service_url(method)
    if not base:
        raise HTTPException(
            status_code=400,
            detail=f"No service URL configured for method '{method}'. Set METHOD_{method.upper()}_URL."
        )

    try:
        p = json.loads(params or "{}")
        if not isinstance(p, dict):
            raise ValueError("params must be a JSON object")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid params JSON: {e}")

    run_id = str(uuid.uuid4())
    run_dir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)

    rec = {
        "id": run_id,
        "method_id": method,
        "status": STAT_PENDING,
        "progress": 0,
        "message": "Queued",
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
        "file_path": None,
        "result": None,
        "error": None,
    }
    RUNS[run_id] = rec

    if file is not None:
        rec["status"] = STAT_RUNNING
        rec["message"] = f"Uploading {file.filename}…"
        rec["progress"] = 1
        dst = os.path.join(run_dir, file.filename)
        try:
            async with aiofiles.open(dst, "wb") as out:
                while True:
                    chunk = await file.read(1024 * 1024)  # 1 MB
                    if not chunk:
                        break
                    await out.write(chunk)
            rec["file_path"] = dst
        except Exception as e:
            rec["status"] = STAT_ERROR
            rec["message"] = "Failed to save upload"
            rec["finished_at"] = _now()
            rec["error"] = f"{e}"
            raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    background.add_task(_execute_method_sync, run_id, p)
    return {"run_id": run_id}


@router.get("/{run_id}/status")
async def run_status(run_id: str):
    rec = RUNS.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Run not found")
    return _public_status(rec)


@router.get("/{run_id}/result")
async def run_result(run_id: str):
    rec = RUNS.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Run not found")
    if rec.get("status") != STAT_DONE:
        raise HTTPException(status_code=409, detail="Run not finished")
    return rec.get("result") or {"ok": False}


# -------------------------
# Background worker
# -------------------------
def _execute_method_sync(run_id: str, params: dict):
    rec = RUNS.get(run_id)
    if not rec:
        return

    method_id = rec["method_id"]
    base = method_service_url(method_id)
    routes = get_service_routes(method_id) or {"run": "/run"}
    url = f"{base.rstrip('/')}{routes.get('run', '/run')}"

    rec["status"] = STAT_RUNNING
    rec["started_at"] = _now()
    rec["message"] = "Submitting to"+" "+ method_id
    rec["progress"] = max(rec.get("progress", 0), 5)

    payload = {
        "file_path": rec.get("file_path"),
        "params": params or {},
    }

    try:
        with httpx.Client(timeout=None) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            result = r.json()

        run_dir = os.path.join(RUNS_DIR, run_id)
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "result.json"), "w") as f:
            json.dump(result, f)

        rec["result"] = result
        rec["status"] = STAT_DONE
        rec["progress"] = 100
        rec["message"] = "Completed"
        rec["finished_at"] = _now()

    except Exception as e:
        rec["status"] = STAT_ERROR
        rec["progress"] = 100
        rec["message"] = "Failed"
        rec["error"] = f"{e}\n{traceback.format_exc()}"
        rec["finished_at"] = _now()
