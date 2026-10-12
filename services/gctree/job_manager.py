"""Per-job child-process manager for the async /jobs contract.

The shared method container stays running; each job runs in its own child
process (job_runner.py). Job state lives on disk under
METHOD_JOBS_DIR/<method_id>/<job_id>/ so status/result survive across requests
and process restarts. Cancellation terminates the job's process group only.

Admission control: a job is only started while a job slot is free and its
estimated memory still fits inside the container's limit (see
resource_limits.py). Otherwise submit() raises JobRejected and the caller keeps
the job queued. Each job's process tree gets a thread budget through its
environment, so jobs x threads stays inside the container's CPU allowance.

No job stays "running" for ever:
  - a job may carry a time limit (sent by the worker, or METHOD_JOB_TIMEOUT_SECONDS);
    the manager stops it when the limit passes, even if the worker is away;
  - a job whose process ended without reporting a result (killed, out of
    memory, crashed) is reported as failed the next time anyone asks;
  - jobs left over from before a restart of this service are reported as
    failed at start-up (recover_interrupted_jobs).
Submitting the same run_id again while its job is active returns that job
instead of starting a second one.

Disk use returns to where it was after every job:
  - each job gets its own temporary directory (<job>/tmp, exported as TMPDIR
    to the job's whole process tree), so everything the method and its tools
    write as scratch data is in one known place; it is removed as soon as the
    job is over, however it ended;
  - the small job record that remains (status, result, log) is removed when
    the worker confirms it has taken the result (delete()), or by itself after
    METHOD_JOB_RETENTION_HOURS if no confirmation ever comes;
  - the job's log is offered and uploaded in bounded form (at most
    METHOD_JOB_LOG_MAX_MB, keeping its beginning and its end).
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import resource_limits

DEFAULT_JOBS_DIR = os.environ.get("METHOD_JOBS_DIR", "/runtime/method-jobs")
CANCEL_GRACE_SECONDS = float(os.environ.get("JOB_CANCEL_GRACE_SECONDS", "5"))
TERMINAL = {"DONE", "ERROR", "CANCELLED"}
LOG_TAIL_BYTES = 4000
DEFAULT_LOG_MAX_MB = 5.0
DEFAULT_JOB_RETENTION_HOURS = 24.0


def _positive_number(name: str, default: float) -> float:
    try:
        value = float((os.environ.get(name) or "").strip() or default)
    except ValueError:
        return default
    return value if value > 0 else default


def log_max_bytes() -> int:
    """Largest log offered for download or uploaded (METHOD_JOB_LOG_MAX_MB)."""
    return int(_positive_number("METHOD_JOB_LOG_MAX_MB", DEFAULT_LOG_MAX_MB) * 1024 * 1024)


def job_retention_seconds() -> float:
    """How long a finished job's record is kept when nobody collects it."""
    return _positive_number("METHOD_JOB_RETENTION_HOURS", DEFAULT_JOB_RETENTION_HOURS) * 3600


def bounded_log(path: Path, max_bytes: Optional[int] = None) -> tuple[bytes, bool]:
    """The log at ``path``, cut to ``max_bytes`` when it is larger: its first
    and last parts are kept (how it started, how it ended) and a line in the
    middle says how much was left out. Returns (content, was_cut)."""
    limit = log_max_bytes() if max_bytes is None else max_bytes
    try:
        size = path.stat().st_size
    except OSError:
        return b"", False
    with path.open("rb") as f:
        if size <= limit:
            return f.read(), False
        half = max(1, limit // 2)
        head = f.read(half)
        f.seek(size - half)
        tail = f.read(half)
    note = (
        f"\n\n[... {size - 2 * half} bytes of this log were left out: it is {size} bytes long and "
        f"logs are kept up to {limit} bytes. The beginning and the end are shown. ...]\n\n"
    ).encode("utf-8")
    return head + note + tail, True

# Failure codes this manager reports in status["error_code"].
CODE_TIMEOUT = "TIMEOUT"
CODE_OUT_OF_MEMORY = "OUT_OF_MEMORY"
CODE_PROCESS_LOST = "JOB_PROCESS_LOST"
CODE_RESTARTED = "METHOD_RESTARTED"


def default_job_timeout_seconds() -> float:
    """Time limit for jobs submitted without one (0 = none)."""
    try:
        return max(0.0, float(os.environ.get("METHOD_JOB_TIMEOUT_SECONDS", "") or 0))
    except ValueError:
        return 0.0


def describe_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds >= 7200:
        hours = seconds / 3600
        return f"{int(hours)} hours" if seconds % 3600 == 0 else f"{hours:.1f} hours"
    if seconds >= 120:
        return f"{round(seconds / 60)} minutes"
    return f"{seconds} second" + ("" if seconds == 1 else "s")


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


def _is_job_id(value: str) -> bool:
    """Job ids are generated here (32 hex characters); anything else, such as a
    path, is not a job."""
    return isinstance(value, str) and 0 < len(value) <= 64 and value.isalnum()


class JobRejected(Exception):
    """A job was not started. ``admission.code`` says whether waiting can help
    (METHOD_BUSY) or not (INSUFFICIENT_CAPACITY)."""

    def __init__(self, admission: "resource_limits.Admission"):
        super().__init__(admission.reason)
        self.admission = admission


class JobManager:
    def __init__(self, method_id: str, jobs_dir: Optional[str] = None, runner_path: Optional[str] = None):
        self.method_id = method_id
        # Limits are fixed for the lifetime of the container, so plan once.
        self.capacity = resource_limits.plan_capacity(method_id)
        # Re-entrant: submit() holds it while it asks for admission, which
        # reaps finished jobs under the same lock.
        self._lock = threading.RLock()
        # Jobs started by this process. Keeping the Popen handles lets us ask
        # the kernel whether a job is still running and reaps finished ones.
        self._procs: dict[str, subprocess.Popen] = {}
        # What this process knows about its jobs: run id, deadline, memory
        # kills seen at start. Mirrored in <job>/meta.json.
        self._meta: dict[str, dict[str, Any]] = {}
        self._timers: dict[str, threading.Timer] = {}
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

    def _meta_path(self, job_id: str) -> Path:
        return self._state_dir(job_id) / "meta.json"

    def _work_dir(self, job_id: str) -> Path:
        """The job's own temporary directory (its TMPDIR)."""
        return self._state_dir(job_id) / "tmp"

    def _remove_work_dir(self, job_id: str) -> None:
        shutil.rmtree(self._work_dir(job_id), ignore_errors=True)

    def log(self, job_id: str) -> Optional[tuple[bytes, bool]]:
        """The job's log in bounded form, or None for an unknown job."""
        if not self._status_path(job_id).exists():
            return None
        return bounded_log(self._state_dir(job_id) / "job.log")

    def delete(self, job_id: str) -> int:
        """Remove everything kept for a finished job. HTTP-style result: 200
        removed, 404 unknown, 409 still running (nothing is removed)."""
        if not _is_job_id(job_id):
            return 404
        with self._lock:
            st = self._settle(job_id)
            if st is None:
                return 404 if not self._state_dir(job_id).is_dir() else self._purge(job_id)
            if st.get("status") not in TERMINAL:
                return 409
            return self._purge(job_id)

    def _purge(self, job_id: str) -> int:
        self._forget(job_id)
        shutil.rmtree(self._state_dir(job_id), ignore_errors=True)
        return 200

    def purge_expired(self, now: Optional[float] = None) -> int:
        """Remove the records of finished jobs nobody collected in time, and
        the scratch data of any finished job. Returns how many records went."""
        now = time.time() if now is None else now
        keep_for = job_retention_seconds()
        removed = 0
        with self._lock:
            for state_dir in sorted(p for p in self.jobs_root.iterdir() if p.is_dir()):
                job_id = state_dir.name
                proc = self._procs.get(job_id)
                if proc is not None and proc.poll() is None:
                    continue                                   # running
                st = read_json(state_dir / "status.json")
                if st is not None and st.get("status") not in TERMINAL:
                    continue                                   # not settled yet; recovery handles it
                # Age first: removing the scratch data touches the directory.
                try:
                    age = now - max(p.stat().st_mtime for p in (state_dir, *state_dir.iterdir()))
                except (OSError, ValueError):
                    age = 0.0
                self._remove_work_dir(job_id)
                if age > keep_for:
                    self._purge(job_id)
                    removed += 1
        return removed

    def running_jobs(self) -> int:
        """Jobs whose process is still alive. Finished ones are reaped here; one
        that ended without reporting a result is recorded as failed first."""
        with self._lock:
            for job_id in [j for j, proc in self._procs.items() if proc.poll() is not None]:
                self._settle(job_id)
                self._forget(job_id)
            return len(self._procs)

    def _forget(self, job_id: str) -> None:
        # The job is over: its scratch data is no longer needed by anyone.
        self._remove_work_dir(job_id)
        self._procs.pop(job_id, None)
        self._meta.pop(job_id, None)
        timer = self._timers.pop(job_id, None)
        if timer is not None:
            timer.cancel()

    def _active_job_for_run(self, run_id: str) -> Optional[str]:
        for job_id, proc in self._procs.items():
            if proc.poll() is None and (self._meta.get(job_id) or {}).get("run_id") == run_id:
                return job_id
        return None

    def _log_tail(self, job_id: str) -> str:
        """The end of the job's own output, for the failure report."""
        try:
            with (self._state_dir(job_id) / "job.log").open("rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - LOG_TAIL_BYTES))
                return f.read().decode("utf-8", errors="replace").strip()
        except OSError:
            return ""

    def _write_failure(self, job_id: str, st: dict, code: str, message: str) -> dict:
        """Record that a job failed for a reason its own process could not report."""
        logs = [{"step": "method.job.manager", "ok": False, "out": message}]
        tail = self._log_tail(job_id)
        if tail:
            logs.append({"step": "method.job.log_tail", "ok": False, "out": tail})
        payload = {
            "ok": False,
            "error": message,
            "error_code": code,
            "logs": logs,
            "manifest_version": 1,
            "artifacts": [],
        }
        atomic_write_json(self._result_path(job_id), payload)
        st = dict(st)
        st.update(
            {
                "status": "ERROR",
                "stage": "ERROR",
                "message": message,
                "error": payload,
                "error_code": code,
                "progress": 100,
                "finished_at": now_iso(),
                "ok": False,
            }
        )
        atomic_write_json(self._status_path(job_id), st)
        self._remove_work_dir(job_id)
        print(f"[job_manager] job {job_id} failed: {code}: {message}", flush=True)
        return st

    def _write_cancelled(self, job_id: str, st: dict) -> dict:
        st = dict(st)
        st.update(
            {
                "status": "CANCELLED",
                "stage": "CANCELLED",
                "message": "Cancelled",
                "finished_at": now_iso(),
                "ok": False,
            }
        )
        tail = self._log_tail(job_id)
        if tail:
            st["log_tail"] = tail
        atomic_write_json(self._status_path(job_id), st)
        self._remove_work_dir(job_id)
        return st

    def _exit_failure(self, job_id: str, returncode: Optional[int]) -> tuple[str, str]:
        """Code and message for a job process that ended without a result."""
        meta = self._meta.get(job_id) or read_json(self._meta_path(job_id)) or {}
        # Stopped at its time limit: whoever notices first (the deadline timer,
        # or a status request arriving while the job is being stopped) must
        # give the same reason.
        deadline = meta.get("deadline_at")
        if meta.get("timed_out") or (isinstance(deadline, (int, float)) and time.time() >= deadline):
            return CODE_TIMEOUT, self._timeout_message(meta.get("timeout_seconds") or 0)
        before = meta.get("oom_kills_at_start")
        now_count = resource_limits.oom_kill_count()
        if isinstance(before, int) and now_count is not None and now_count > before:
            limit = self.capacity.memory_limit_mb
            within = f" (limit {limit} MiB)" if limit else ""
            return CODE_OUT_OF_MEMORY, (
                f"The job was stopped because the {self.method_id} service ran out of memory{within}. "
                "Try a smaller dataset, or ask the administrator to raise the memory limit of this method."
            )
        how = f"exit code {returncode}" if returncode is not None and returncode >= 0 else (
            f"signal {-returncode}" if returncode is not None else "unknown cause"
        )
        return CODE_PROCESS_LOST, (
            f"The job's process ended unexpectedly ({how}) without reporting a result. "
            "The run was not repeated automatically; please submit it again."
        )

    def _settle(self, job_id: str) -> Optional[dict]:
        """Bring a job's stored status in line with reality and return it.

        Call with the lock held. A job whose process is alive is left alone. One
        whose process is gone but whose status still says it is running gets a
        terminal status: nobody else will ever write one.
        """
        st = read_json(self._status_path(job_id))
        if st is None or st.get("status") in TERMINAL:
            return st
        proc = self._procs.get(job_id)
        if proc is not None and proc.poll() is None:
            return st
        if proc is None:
            # Not started by this process: it belongs to an earlier life of
            # the service, and its process died with it.
            return self._write_failure(
                job_id, st, CODE_RESTARTED,
                f"The {self.method_id} service was restarted while this job was running, so its "
                "work was lost. The run was not repeated automatically; please submit it again.",
            )
        # The process has ended. Its last act is an atomic status write, so read
        # once more before concluding that it reported nothing.
        st = read_json(self._status_path(job_id)) or st
        if st.get("status") in TERMINAL:
            return st
        if st.get("status") == "CANCELLING":
            return self._write_cancelled(job_id, st)
        code, message = self._exit_failure(job_id, proc.returncode)
        return self._write_failure(job_id, st, code, message)

    def recover_interrupted_jobs(self) -> int:
        """Fail every job left unfinished by an earlier life of this service.

        Call once when the service starts, never from a job's own process (the
        job runner imports this module too). Returns how many jobs were closed.
        """
        closed = 0
        with self._lock:
            for status_path in sorted(self.jobs_root.glob("*/status.json")):
                job_id = status_path.parent.name
                if job_id in self._procs:
                    continue
                st = read_json(status_path)
                if st is None or st.get("status") in TERMINAL:
                    continue
                self._settle(job_id)
                closed += 1
        self.purge_expired()
        return closed

    def admission(self) -> "resource_limits.Admission":
        return resource_limits.admit(
            self.capacity, self.running_jobs(), resource_limits.memory_in_use_bytes()
        )

    def capacity_report(self) -> dict[str, Any]:
        """Snapshot for GET /capacity: what the service may use and what is free."""
        with self._lock:
            running = self.running_jobs()
            decision = self.admission()
        in_use = resource_limits.memory_in_use_bytes()
        report = self.capacity.as_dict()
        report.update(
            {
                "ok": True,
                "running_jobs": running,
                "free_slots": max(0, self.capacity.job_slots - running),
                "memory_in_use_mb": None if in_use is None else int(in_use // (1024 * 1024)),
                "accepting": decision.accepted,
                "code": decision.code,
                "reason": decision.reason,
            }
        )
        return report

    def submit(
        self,
        *,
        file_path: Optional[str],
        params: dict,
        run_id: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> str:
        # One submit at a time: the admission check and the start of the job
        # must not interleave with another request.
        with self._lock:
            if run_id:
                # The caller may repeat a submit whose answer it never received.
                existing = self._active_job_for_run(str(run_id))
                if existing is not None:
                    return existing
            decision = self.admission()
            if not decision.accepted:
                raise JobRejected(decision)
            # A good moment to drop what earlier jobs left behind.
            self.purge_expired()
            return self._start(
                file_path=file_path, params=params, run_id=run_id, timeout_seconds=timeout_seconds
            )

    def _start(
        self,
        *,
        file_path: Optional[str],
        params: dict,
        run_id: Optional[str],
        timeout_seconds: Optional[float] = None,
    ) -> str:
        job_id = uuid.uuid4().hex
        state_dir = self._state_dir(job_id)
        state_dir.mkdir(parents=True, exist_ok=True)

        atomic_write_json(
            self._request_path(job_id),
            {"file_path": file_path, "params": params or {}, "run_id": run_id},
        )
        try:
            limit = float(timeout_seconds) if timeout_seconds is not None else default_job_timeout_seconds()
        except (TypeError, ValueError):
            limit = default_job_timeout_seconds()
        limit = limit if limit > 0 else 0.0
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
            "threads": self.capacity.threads_per_job,
        }
        if limit:
            status["timeout_seconds"] = limit
        atomic_write_json(self._status_path(job_id), status)

        popen_kwargs: dict[str, Any] = {}
        if os.name == "posix":
            # New session/process group so cancellation can kill nested children.
            popen_kwargs["start_new_session"] = True

        oom_kills = resource_limits.oom_kill_count()
        meta = {
            "run_id": str(run_id) if run_id else None,
            "submitted_at": time.time(),
            "timeout_seconds": limit or None,
            "deadline_at": (time.time() + limit) if limit else None,
            "oom_kills_at_start": oom_kills,
        }
        atomic_write_json(self._meta_path(job_id), meta)

        # The job's whole process tree inherits its CPU budget.
        env = os.environ.copy()
        env.update(resource_limits.job_environment(self.method_id, self.capacity.threads_per_job))
        # Marks the process tree as a job (not the service), and lets the job
        # tell an out-of-memory kill of one of its tools from another failure.
        env["PHYLO_JOB_CHILD"] = "1"
        # Everything the job writes as scratch data goes into its own
        # directory, which is removed when the job is over.
        work_dir = self._work_dir(job_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = env["TMP"] = env["TEMP"] = str(work_dir)
        if oom_kills is not None:
            env["PHYLO_JOB_OOM_BASELINE"] = str(oom_kills)

        proc = subprocess.Popen(
            [sys.executable, "-u", self.runner_path, "--job-id", job_id, "--state-dir", str(state_dir)],
            cwd=str(Path(self.runner_path).parent),
            env=env,
            **popen_kwargs,
        )
        self._procs[job_id] = proc
        self._meta[job_id] = meta
        # The runner records its own pid as soon as it is up; until then this
        # gives cancel something to signal. Never overwrite what it has written.
        current = read_json(self._status_path(job_id)) or status
        if current.get("status") == "QUEUED" and not current.get("pid"):
            current["pid"] = proc.pid
            atomic_write_json(self._status_path(job_id), current)
        if limit:
            timer = threading.Timer(limit, self._on_deadline, args=(job_id,))
            timer.daemon = True
            self._timers[job_id] = timer
            timer.start()
        return job_id

    def _on_deadline(self, job_id: str) -> None:
        """The job's time limit has passed: stop it and report a timeout."""
        with self._lock:
            proc = self._procs.get(job_id)
            st = read_json(self._status_path(job_id))
            if proc is None or st is None or st.get("status") in TERMINAL:
                return
            if proc.poll() is not None:
                self._settle(job_id)
                return
            meta = self._meta.setdefault(job_id, {})
            meta["timed_out"] = True
            limit = meta.get("timeout_seconds") or 0
            print(f"[job_manager] job {job_id} exceeded its time limit; stopping it", flush=True)
            self._terminate(proc.pid)
        # Wait outside the lock so status/submit requests are not held up.
        try:
            proc.wait(timeout=CANCEL_GRACE_SECONDS + 5)
        except subprocess.TimeoutExpired:
            pass
        with self._lock:
            st = read_json(self._status_path(job_id))
            if st is None or st.get("status") in TERMINAL:
                return  # it finished (or was cancelled) in the meantime
            self._write_failure(job_id, st, CODE_TIMEOUT, self._timeout_message(limit))

    def _timeout_message(self, limit: float) -> str:
        return (
            f"The job was stopped by the {self.method_id} service because it exceeded its "
            f"time limit of {describe_duration(limit)}."
        )

    def status(self, job_id: str) -> Optional[dict]:
        st = read_json(self._status_path(job_id))
        if st is None or st.get("status") in TERMINAL:
            return st
        with self._lock:
            return self._settle(job_id)

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
        # Under the lock, so a status request cannot mistake a job that is being
        # cancelled for one that died by itself.
        with self._lock:
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
            return self._write_cancelled(job_id, fin)

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
