"""Lifecycle tests for the per-job child-process JobManager.

These use a lightweight stub runner (no scientific deps) injected via
runner_path, so they exercise submit/status/result/cancel end to end with real
child processes and disk state.

Run from services/gctree:
    python -m pytest tests/test_job_manager.py
"""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importlib.util

@pytest.fixture(params=["gctree", "clonaltree"])
def manager_class(request):
    module_path = Path(__file__).resolve().parents[2] / request.param / "job_manager.py"
    spec = importlib.util.spec_from_file_location(f"{request.param}_manager", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.JobManager


def _write_runner(tmp_path: Path, body: str) -> str:
    runner = tmp_path / "stub_runner.py"
    runner.write_text(body, encoding="utf-8")
    return str(runner)


def _wait_for_status(mgr, job_id: str, statuses, timeout=10.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        st = mgr.status(job_id)
        last = st
        if st and st.get("status") in statuses:
            return st
        time.sleep(0.1)
    return last


# Stubs mirror the real job_runner contract: read existing status, set the
# child's own pid, then write status atomically (so cancel can find the pid).
_RUNNER_PRELUDE = """
import argparse, json, os, time
p = argparse.ArgumentParser()
p.add_argument("--job-id")
p.add_argument("--state-dir")
a = p.parse_args()
sd = a.state_dir
sp = os.path.join(sd, "status.json")
def read():
    try:
        with open(sp) as f:
            return json.load(f)
    except Exception:
        return {}
def write(name, data):
    tmp = os.path.join(sd, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, os.path.join(sd, name))
st = read()
st.update({"job_id": a.job_id, "status": "RUNNING", "stage": "BUILDING_TREES", "progress": 50, "pid": os.getpid()})
write("status.json", st)
"""

DONE_RUNNER = _RUNNER_PRELUDE + """
time.sleep(0.3)
write("result.json", {"ok": True, "trees": ["(a,b);"]})
st.update({"status": "DONE", "stage": "COMPLETED", "progress": 100, "ok": True})
write("status.json", st)
"""

LONG_RUNNER = _RUNNER_PRELUDE + """
time.sleep(60)
"""


def test_submit_returns_quickly_and_reaches_done(tmp_path, manager_class):
    runner = _write_runner(tmp_path, DONE_RUNNER)
    mgr = manager_class("gctree", jobs_dir=str(tmp_path / "jobs"), runner_path=runner)

    t0 = time.time()
    job_id = mgr.submit(file_path="/tmp/in.fasta", params={"k": 1}, run_id="run-1")
    elapsed = time.time() - t0

    # POST /jobs must return quickly (does not block on the computation).
    assert elapsed < 2.0
    assert job_id

    # Result is not available until DONE.
    payload, code = mgr.result(job_id)
    assert code in (404, 409)

    st = _wait_for_status(mgr, job_id, {"DONE"})
    assert st and st["status"] == "DONE"

    payload, code = mgr.result(job_id)
    assert code == 200
    assert payload["ok"] is True
    assert payload["trees"] == ["(a,b);"]


@pytest.mark.skipif(os.name != "posix", reason="process-group cancel is POSIX-only")
def test_cancel_terminates_long_running_job(tmp_path, manager_class):
    runner = _write_runner(tmp_path, LONG_RUNNER)
    mgr = manager_class("gctree", jobs_dir=str(tmp_path / "jobs"), runner_path=runner)

    job_id = mgr.submit(file_path=None, params={}, run_id="run-2")
    running = _wait_for_status(mgr, job_id, {"RUNNING"})
    assert running and running["status"] == "RUNNING"
    pid = running.get("pid")
    assert pid

    final = mgr.cancel(job_id)
    assert final and final["status"] == "CANCELLED"

    # Cancel is idempotent: a second call returns the terminal state.
    again = mgr.cancel(job_id)
    assert again["status"] == "CANCELLED"

    # The child must actually terminate (SIGTERM, then SIGKILL after grace).
    # Reap it to confirm exit; a SIGKILLed child otherwise lingers as a zombie.
    deadline = time.time() + 12
    terminated = False
    while time.time() < deadline:
        try:
            wpid, _ = os.waitpid(int(pid), os.WNOHANG)
            if wpid == int(pid):
                terminated = True
                break
        except ChildProcessError:
            terminated = True
            break
        time.sleep(0.2)
    assert terminated, "cancelled job child process did not terminate"


def test_unknown_job_and_incomplete_result(tmp_path, manager_class):
    mgr = manager_class("test", jobs_dir=str(tmp_path))
    assert mgr.status("missing") is None
    assert mgr.result("missing") == (None, 404)
    assert mgr.cancel("missing") is None


def test_terminal_states_survive_manager_restart(tmp_path, manager_class):
    import json
    mgr = manager_class("test", jobs_dir=str(tmp_path))
    state = mgr.jobs_root / "job"
    state.mkdir()
    (state / "status.json").write_text(json.dumps({"status": "DONE"}))
    (state / "result.json").write_text(json.dumps({"trees": ["(a,b);"]}))
    restarted = manager_class("test", jobs_dir=str(tmp_path))
    assert restarted.result("job") == ({"trees": ["(a,b);"]}, 200)
    assert restarted.cancel("job")["status"] == "DONE"
    (state / "result.json").write_text("broken JSON")
    assert restarted.result("job") == (None, 409)
