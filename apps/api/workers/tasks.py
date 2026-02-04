from __future__ import annotations

import os
import json
import traceback
import asyncio
from datetime import datetime
from typing import Dict, Any
import httpx
import uuid

from apps.api.database.database import AsyncSessionLocal
from apps.api.database.models.run import Run, RunStatus
from apps.api.database.models.result import Result
from apps.api.contracts.loader import get_service_routes
from apps.api.config import method_service_url, HTTP_CLIENT_TIMEOUT, RUNS_DIR_SERVICE

DEFAULT_RUNS_DIR = os.path.join(os.getcwd(), "runtime", "runs")
RUNS_DIR = os.environ.get("RUNS_DIR", DEFAULT_RUNS_DIR)


def _service_file_path(host_path: str | None) -> str | None:
    """Map a host run path to the path expected by the method service."""
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


async def _execute_method_task_async(run_id: str) -> None:
    """Execute a method run task (async implementation)."""
    async with AsyncSessionLocal() as session:
        try:
            # Get run from database
            from sqlalchemy import select
            result = await session.execute(select(Run).where(Run.id == uuid.UUID(run_id)))
            run = result.scalar_one_or_none()
            
            if not run:
                return
            
            method_id = run.method_id
            base = method_service_url(method_id)
            if not base:
                msg = f"No service URL configured for method '{method_id}'. Set METHOD_{method_id.upper()}_URL."
                run.status = RunStatus.ERROR
                run.progress = 100
                run.message = msg
                run.error = msg
                run.finished_at = datetime.utcnow()
                await session.commit()
                return
            
            routes = get_service_routes(method_id) or {"run": "/run"}
            url = f"{base.rstrip('/')}{routes.get('run', '/run')}"
            
            # Mark as running
            run.status = RunStatus.RUNNING
            run.started_at = datetime.utcnow()
            run.message = f"Submitting to {method_id}"
            run.progress = max(run.progress or 0, 5)
            await session.commit()
            
            # Prepare payload
            payload = {
                "file_path": _service_file_path(run.file_path),
                "params": run.params or {}
            }
            
            # Call method service
            with httpx.Client(timeout=HTTP_CLIENT_TIMEOUT, trust_env=False) as client:
                response = client.post(url, json=payload)
                
                if response.status_code >= 400:
                    err_msg = None
                    try:
                        j = response.json()
                        if isinstance(j, dict):
                            err_msg = j.get("error") or j.get("message")
                    except Exception:
                        pass
                    err_msg = err_msg or response.text or f"{response.status_code} {response.reason_phrase}"
                    
                    run.status = RunStatus.ERROR
                    run.progress = 100
                    run.message = err_msg
                    run.error = err_msg
                    run.finished_at = datetime.utcnow()
                    await session.commit()
                    return
                
                result_data = response.json()
            
            # Save result to file (backward compatibility)
            result_file = os.path.join(RUNS_DIR, str(run_id), "result.json")
            os.makedirs(os.path.dirname(result_file), exist_ok=True)
            with open(result_file, "w") as f:
                json.dump(result_data, f)
            
            # Save result to database
            result = Result(run_id=uuid.UUID(run_id), result_data=result_data)
            session.add(result)
            
            # Update run status
            run.status = RunStatus.DONE
            run.progress = 100
            run.message = "Completed"
            run.finished_at = datetime.utcnow()
            
            await session.commit()
            
        except Exception as e:
            msg = str(e)
            if 'run' in locals():
                run.status = RunStatus.ERROR
                run.progress = 100
                run.message = msg
                run.error = f"{msg}\n{traceback.format_exc()}"
                run.finished_at = datetime.utcnow()
                await session.commit()


def execute_method_task(run_id: str) -> None:
    """Execute a method run task - sync wrapper for RQ."""
    # RQ workers are sync, so we need to run async code in an event loop
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    loop.run_until_complete(_execute_method_task_async(run_id))

