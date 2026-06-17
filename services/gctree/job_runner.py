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
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from job_manager import atomic_write_json, now_iso, read_json  # noqa: E402
from app import run_job_sync  # noqa: E402
from artifact_manifest import materialize_artifacts  # noqa: E402
from object_storage import upload_artifact  # noqa: E402


def _redirect_stdio_to_log(log_path: Path) -> None:
    """Tee child stdout/stderr into job.log via os.dup2 so we capture every
    line emitted by run_job_sync and its tool subprocesses. Original handles
    are closed; the parent process inherits its own console via the
    subprocess.Popen launcher (job_manager) which does not capture them.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.dup2(fd, 1)
        os.dup2(fd, 2)
    finally:
        os.close(fd)
    # Re-open Python-level streams pointing at the dup'd fds.
    sys.stdout = os.fdopen(1, "w", buffering=1)
    sys.stderr = os.fdopen(2, "w", buffering=1)


def _append_log_artifact(payload: Any, run_id: str, job_id: str, log_path: Path) -> Any:
    """Upload state_dir/job.log to MinIO and append a descriptor to
    payload["artifacts"]. Robust to NULL payload / missing log / failed
    upload — never raises.
    """
    if not isinstance(payload, dict):
        return payload
    payload.setdefault("manifest_version", 1)
    payload.setdefault("artifacts", [])
    if not log_path.is_file():
        return payload
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    try:
        uploaded = upload_artifact(
            log_path,
            run_id=run_id,
            job_id=job_id,
            filename="job.log",
            content_type="text/plain",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[job_runner] job.log upload failed: {exc}", flush=True)
        return payload
    payload["artifacts"].append(
        {
            "object_key": uploaded["object_key"],
            "size_bytes": uploaded["size_bytes"],
            "checksum_sha256": uploaded["checksum_sha256"],
            "filename": "job.log",
            "kind": "log",
            "role": "log",
            "content_type": "text/plain",
            "previewable": True,
        }
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--state-dir", required=True)
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    status_path = state_dir / "status.json"
    result_path = state_dir / "result.json"
    log_path = state_dir / "job.log"

    # Capture child stdout/stderr into job.log before doing anything else, so
    # import-time logs and unhandled exceptions are preserved.
    _redirect_stdio_to_log(log_path)

    req = read_json(state_dir / "request.json") or {}
    file_path = req.get("file_path")
    params = req.get("params") or {}
    run_id = req.get("run_id") or ""

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
        # Upload artifact files directly to MinIO and replace the source-side
        # artifact_files list with a {object_key, size_bytes, checksum_sha256,
        # ...} manifest. Nothing crosses the service -> API boundary via a
        # shared volume.
        try:
            payload = materialize_artifacts(payload, run_id=run_id, job_id=args.job_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[gctree.job_runner] materialize_artifacts failed: {exc}", flush=True)
        payload = _append_log_artifact(payload, run_id, args.job_id, log_path)
        atomic_write_json(result_path, payload)
        if ok_flag:
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
        err_payload = {
            "ok": False,
            "error": str(exc),
            "logs": [{"step": "method.job.unhandled", "ok": False, "out": tb}],
        }
        err_payload = _append_log_artifact(err_payload, run_id, args.job_id, log_path)
        atomic_write_json(result_path, err_payload)
        status.update(
            {
                "status": "ERROR",
                "stage": "ERROR",
                "message": str(exc),
                "error": err_payload,
                "progress": 100,
                "finished_at": now_iso(),
                "ok": False,
            }
        )
        atomic_write_json(status_path, status)


if __name__ == "__main__":
    main()
