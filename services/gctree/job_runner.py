"""Child-process entrypoint for a single method job.

Runs the existing /run pipeline (unchanged) in a dedicated process via
app.run_job_sync, writing stage-based status.json and result.json atomically.
Spawned by job_manager.JobManager.submit. Killing this process group cancels
the job and any nested tool subprocesses.
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from job_manager import atomic_write_json, now_iso, read_json  # noqa: E402
from app import run_job_sync  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--state-dir", required=True)
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    status_path = state_dir / "status.json"
    result_path = state_dir / "result.json"

    req = read_json(state_dir / "request.json") or {}
    file_path = req.get("file_path")
    params = req.get("params") or {}
    run_id = req.get("run_id")

    status = read_json(status_path) or {}
    status.update(
        {
            "ok": True,
            "job_id": args.job_id,
            "status": "RUNNING",
            "stage": "RUNNING_METHOD",
            "message": "Running method",
            "progress": 45,
            "pid": os.getpid(),
            "run_id": run_id,
            "started_at": now_iso(),
            "finished_at": None,
            "error": None,
        }
    )
    atomic_write_json(status_path, status)

    try:
        status_code, payload = run_job_sync(file_path, params)
        ok_flag = (status_code < 400) and not (
            isinstance(payload, dict) and payload.get("ok") is False
        )
        if ok_flag:
            atomic_write_json(result_path, payload)
            status.update(
                {
                    "status": "DONE",
                    "stage": "COMPLETED",
                    "message": "Completed",
                    "progress": 100,
                    "finished_at": now_iso(),
                    "ok": True,
                }
            )
            atomic_write_json(status_path, status)
        else:
            err_msg = None
            if isinstance(payload, dict) and isinstance(payload.get("error"), str):
                err_msg = payload["error"]
            err_msg = err_msg or f"Method returned HTTP {status_code}"
            # Preserve the full method payload (logs/warnings) for the worker.
            atomic_write_json(result_path, payload)
            status.update(
                {
                    "status": "ERROR",
                    "stage": "ERROR",
                    "message": err_msg,
                    "error": payload if isinstance(payload, dict) else err_msg,
                    "progress": 100,
                    "finished_at": now_iso(),
                    "ok": False,
                }
            )
            atomic_write_json(status_path, status)
    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc()
        status.update(
            {
                "status": "ERROR",
                "stage": "ERROR",
                "message": str(exc),
                "error": {
                    "ok": False,
                    "error": str(exc),
                    "logs": [{"step": "method.job.unhandled", "ok": False, "out": tb}],
                },
                "progress": 100,
                "finished_at": now_iso(),
                "ok": False,
            }
        )
        atomic_write_json(status_path, status)


if __name__ == "__main__":
    main()
