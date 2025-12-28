from __future__ import annotations

import os
import json
import uuid
import traceback
import threading
import time
from typing import Dict, Any
from datetime import datetime

import aiofiles
import httpx
from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form, Query, HTTPException

from apps.api.contracts.loader import get_service_routes
from apps.api.config import method_service_url

router = APIRouter(prefix="/runs", tags=["runs"])

DEFAULT_RUNS_DIR = os.path.join(os.getcwd(), "runtime", "runs")
RUNS_DIR = os.environ.get("RUNS_DIR", DEFAULT_RUNS_DIR)
RUNS_DIR_SERVICE = os.environ.get("RUNS_DIR_SERVICE")  # optional override for method-facing path

def _ensure_dir(path: str) -> str:
  try:
    os.makedirs(path, exist_ok=True); return path
  except PermissionError:
    fb = DEFAULT_RUNS_DIR; os.makedirs(fb, exist_ok=True); return fb

RUNS_DIR = _ensure_dir(RUNS_DIR)
RUNS: Dict[str, Dict[str, Any]] = {}

STAT_PENDING = "PENDING"; STAT_RUNNING = "RUNNING"; STAT_DONE = "DONE"; STAT_ERROR = "ERROR"

def _now() -> str: return datetime.utcnow().isoformat() + "Z"

def _public_status(rec: Dict[str, Any]) -> Dict[str, Any]:
  return {"status": rec.get("status", STAT_PENDING),
          "progress": rec.get("progress", 0),
          "message": rec.get("message")}

def _service_file_path(host_path: str | None) -> str | None:
  """Map a host run path to the path expected by the method service.

  When the API runs on the host but methods run in containers, the shared
  volume may be mounted at a different location (e.g., host
  `/home/.../runtime/runs` → container `/runtime/runs`). Set RUNS_DIR_SERVICE
  to the container mount point so the service receives a valid path.
  """
  if not host_path:
    return None
  if not RUNS_DIR_SERVICE:
    return host_path
  try:
    host_root = os.path.realpath(RUNS_DIR)
    host_path_real = os.path.realpath(host_path)
    if os.path.commonpath([host_root, host_path_real]) == host_root:
      rel = os.path.relpath(host_path_real, host_root)
      return os.path.join(RUNS_DIR_SERVICE, rel)
  except Exception:
    return host_path
  return host_path

def _soft_progress_worker(run_id: str, floor: int = 10, ceiling: int = 95, step: int = 3, interval: float = 2.0):
  """Increase progress gradually while RUNNING so the UI doesn't stick at 5%."""
  try:
    while True:
      rec = RUNS.get(run_id)
      if not rec or rec.get("status") != STAT_RUNNING: return
      cur = int(rec.get("progress") or floor)
      if cur < ceiling:
        rec["progress"] = min(cur + step, ceiling)
        rec.setdefault("message", "Processing…")
      time.sleep(interval)
  except Exception:
    return

@router.post("")
async def create_run(
  background: BackgroundTasks,
  method: str = Query(..., description="Method ID (e.g., 'dowser')"),
  params: str = Form("{}", description="JSON string of parameters"),
  file: UploadFile | None = File(None),
):
  base = method_service_url(method)
  if not base:
    raise HTTPException(400, f"No service URL configured for method '{method}'. Set METHOD_{method.upper()}_URL.")

  try:
    p = json.loads(params or "{}")
    if not isinstance(p, dict):
      raise ValueError("params must be a JSON object")
  except Exception as e:
    raise HTTPException(400, f"Invalid params JSON: {e}")

  run_id = str(uuid.uuid4())
  run_dir = os.path.join(RUNS_DIR, run_id)
  os.makedirs(run_dir, exist_ok=True)

  rec = {
    "id": run_id, "method_id": method, "status": STAT_PENDING, "progress": 0,
    "message": "Queued", "created_at": _now(), "started_at": None, "finished_at": None,
    "file_path": None, "result": None, "error": None,
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
          chunk = await file.read(1024 * 1024)  # 1MB
          if not chunk: break
          await out.write(chunk)
      rec["file_path"] = dst
    except Exception as e:
      raise HTTPException(500, f"Failed to save upload: {e}")

  background.add_task(_execute_method_sync, run_id, p)
  threading.Thread(target=_soft_progress_worker, args=(run_id,), daemon=True).start()

  return {"run_id": run_id}

@router.get("/{run_id}/status")
async def run_status(run_id: str):
  rec = RUNS.get(run_id)
  if not rec: raise HTTPException(404, "Run not found")
  return _public_status(rec)

@router.get("/{run_id}/result")
async def run_result(run_id: str):
  rec = RUNS.get(run_id)
  if not rec: raise HTTPException(404, "Run not found")
  if rec.get("status") != STAT_DONE: raise HTTPException(409, "Run not finished")
  return rec.get("result") or {"ok": False}

# -------- background worker --------
def _execute_method_sync(run_id: str, params: dict):
    rec = RUNS.get(run_id)
    if not rec: return
    method_id = rec["method_id"]
    base = method_service_url(method_id)
    if not base:
        msg = f"No service URL configured for method '{method_id}'. Set METHOD_{method_id.upper()}_URL."
        rec.update({"status": STAT_ERROR, "progress": 100, "message": msg,
                    "error": msg, "finished_at": _now()})
        return

    routes = get_service_routes(method_id) or {"run": "/run"}
    url = f"{base.rstrip('/')}{routes.get('run', '/run')}"

    # mark running
    rec["status"] = STAT_RUNNING
    rec["started_at"] = _now()
    rec["message"] = f"Submitting to {method_id}"
    rec["progress"] = max(int(rec.get("progress") or 0), 5)

    payload = {"file_path": _service_file_path(rec.get("file_path")), "params": params or {}}

    try:
        with httpx.Client(timeout=None, trust_env=False) as client:
            r = client.post(url, json=payload)
            if r.status_code >= 400:
                err_msg = None
                try:
                    j = r.json()
                    if isinstance(j, dict):
                        err_msg = j.get("error") or j.get("message")
                except Exception:
                    pass
                err_msg = err_msg or r.text or f"{r.status_code} {r.reason_phrase}"
                rec.update({"status": STAT_ERROR, "progress": 100, "message": err_msg,
                            "error": err_msg, "finished_at": _now()})
                return
            result = r.json()

        with open(os.path.join(RUNS_DIR, run_id, "result.json"), "w") as f:
            json.dump(result, f)

        rec.update({"result": result, "status": STAT_DONE, "progress": 100,
                    "message": "Completed", "finished_at": _now()})

    except Exception as e:
        msg = str(e)
        rec.update({"status": STAT_ERROR, "progress": 100, "message": msg,
                    "error": f"{msg}\n{traceback.format_exc()}", "finished_at": _now()})
