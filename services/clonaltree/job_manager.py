"""Per-job child-process manager for the async /jobs contract.

The shared method container stays running; each job runs in its own child
process (job_runner.py). Job state lives on disk under
METHOD_JOBS_DIR/<method_id>/<job_id>/ so status/result survive across requests
and process restarts. Cancellation terminates the job's process group only.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_JOBS_DIR = os.environ.get("METHOD_JOBS_DIR", "/runtime/method-jobs")
CANCEL_GRACE_SECONDS = float(os.environ.get("JOB_CANCEL_GRACE_SECONDS", "5"))
TERMINAL = {"DONE", "ERROR", "CANCELLED"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically (temp file + rename) so readers never see partial files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


class JobManager:
    def __init__(self, method_id: str, jobs_dir: Optional[str] = None, runner_path: Optional[str] = None):
        self.method_id = method_id
        self.jobs_root = Path(jobs_dir or DEFAULT_JOBS_DIR) / method_id
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        # Runner is overridable (env or arg) so the lifecycle can be tested with
        # a lightweight stub instead of the full scientific entrypoint.
        self.runner_path = runner_path or os.environ.get(
            "JOB_RUNNER_PATH", str(Path(__file__).resolve().parent / "job_runner.py")
        )

    def _state_dir(self, job_id: str) -> Path:
        return self.jobs_root / job_id

    def _status_path(self, job_id: str) -> Path:
        return self._state_dir(job_id) / "status.json"

    def _result_path(self, job_id: str) -> Path:
        return self._state_dir(job_id) / "result.json"

    def _request_path(self, job_id: str) -> Path:
        return self._state_dir(job_id) / "request.json"

    def submit(self, *, file_path: Optional[str], params: dict, run_id: Optional[str] = None) -> str:
        job_id = uuid.uuid4().hex
        state_dir = self._state_dir(job_id)
        state_dir.mkdir(parents=True, exist_ok=True)

        atomic_write_json(
            self._request_path(job_id),
            {"file_path": file_path, "params": params or {}, "run_id": run_id},
        )
        status = {
            "ok": True,
            "job_id": job_id,
            "status": "QUEUED",
            "stage": "QUEUED",
            "message": "Queued",
            "progress": 0,
            "pid": None,
            "run_id": run_id,
            "started_at": None,
            "finished_at": None,
            "error": None,
        }
        atomic_write_json(self._status_path(job_id), status)

        popen_kwargs: dict[str, Any] = {}
        if os.name == "posix":
            # New session/process group so cancellation can kill nested children.
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(
            [sys.executable, "-u", self.runner_path, "--job-id", job_id, "--state-dir", str(state_dir)],
            cwd=str(Path(self.runner_path).parent),
            **popen_kwargs,
        )
        status["pid"] = proc.pid
        atomic_write_json(self._status_path(job_id), status)
        return job_id

    def status(self, job_id: str) -> Optional[dict]:
        return read_json(self._status_path(job_id))

    def result(self, job_id: str) -> tuple[Optional[dict], int]:
        st = read_json(self._status_path(job_id))
        if st is None:
            return None, 404
        if st.get("status") != "DONE":
            return None, 409
        payload = read_json(self._result_path(job_id))
        if payload is None:
            return None, 409
        return payload, 200

    def cancel(self, job_id: str) -> Optional[dict]:
        st = read_json(self._status_path(job_id))
        if st is None:
            return None
        if st.get("status") in TERMINAL:
            return st

        pid = st.get("pid")
        st["status"] = "CANCELLING"
        st["stage"] = "CANCELLING"
        st["message"] = "Cancelling..."
        atomic_write_json(self._status_path(job_id), st)

        if pid:
            self._terminate(int(pid))

        fin = read_json(self._status_path(job_id)) or st
        # If the child already finished cleanly between our read and kill, respect it.
        if fin.get("status") in ("DONE", "ERROR"):
            return fin
        fin["status"] = "CANCELLED"
        fin["stage"] = "CANCELLED"
        fin["message"] = "Cancelled"
        fin["finished_at"] = now_iso()
        fin["ok"] = False
        atomic_write_json(self._status_path(job_id), fin)
        return fin

    @staticmethod
    def _terminate(pid: int) -> None:
        def _delayed_kill(target_killpg: bool, ident: int) -> None:
            time.sleep(CANCEL_GRACE_SECONDS)
            try:
                if target_killpg:
                    os.killpg(ident, signal.SIGKILL)
                else:
                    os.kill(ident, signal.SIGKILL)
            except Exception:
                pass

        try:
            if os.name == "posix":
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGTERM)
                threading.Thread(target=_delayed_kill, args=(True, pgid), daemon=True).start()
            else:
                os.kill(pid, signal.SIGTERM)
                threading.Thread(target=_delayed_kill, args=(False, pid), daemon=True).start()
        except ProcessLookupError:
            pass
        except Exception:
            pass
