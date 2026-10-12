"""Lifecycle tests for the per-job child-process JobManager.

These use a lightweight stub runner (no scientific deps) injected via
runner_path, so they exercise submit/status/result/cancel end to end with real
child processes and disk state.

Run from services/gctree:
    python -m pytest tests/test_job_manager.py
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importlib.util

def _load_service_module(service: str, filename: str, alias: str, monkeypatch):
    """Load one service's own file. job_manager.py does `import resource_limits`;
    make that resolve to the same service's copy, as it does in its container."""
    root = Path(__file__).resolve().parents[2] / service
    if filename == "job_manager.py":
        limits = _load_service_module(service, "resource_limits.py", f"{service}_resource_limits", monkeypatch)
        monkeypatch.setitem(sys.modules, "resource_limits", limits)
    spec = importlib.util.spec_from_file_location(alias, root / filename)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, alias, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=["gctree", "clonaltree"])
def manager_class(request, monkeypatch):
    return _load_service_module(request.param, "job_manager.py", f"{request.param}_manager", monkeypatch).JobManager


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


# --------------------------------------------------------------------------- #
# Admission control and per-job CPU budget
# --------------------------------------------------------------------------- #
MIB = 1024 * 1024


@pytest.fixture(params=["gctree", "clonaltree"])
def manager_module(request, monkeypatch):
    return _load_service_module(request.param, "job_manager.py", f"{request.param}_manager_mod", monkeypatch)


def _fake_cgroup(tmp_path, monkeypatch, *, cpus, memory_mb, in_use_mb, **tunables):
    root = tmp_path / "cgroup"
    root.mkdir(exist_ok=True)
    (root / "cpu.max").write_text(f"{int(cpus * 100000)} 100000\n")
    (root / "memory.max").write_text(f"{memory_mb * MIB}\n")
    (root / "memory.current").write_text(f"{in_use_mb * MIB}\n")
    (root / "memory.stat").write_text("inactive_file 0\n")
    monkeypatch.setenv("PHYLO_CGROUP_ROOT", str(root))
    for name in ("METHOD_MAX_CONCURRENT_JOBS", "METHOD_THREADS_PER_JOB", "METHOD_JOB_MEMORY_MB",
                 "METHOD_BASELINE_MEMORY_MB", "METHOD_MEMORY_HEADROOM_PERCENT", "METHOD_CPU_LIMIT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in tunables.items():
        monkeypatch.setenv(name, str(value))
    return root


def _manager(manager_module, tmp_path, runner_body):
    runner = _write_runner(tmp_path, runner_body)
    return manager_module.JobManager("gctree", jobs_dir=str(tmp_path / "jobs"), runner_path=runner)


ENV_RUNNER = _RUNNER_PRELUDE + """
names = ["PHYLO_JOB_THREADS", "OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "OPENBLAS_NUM_THREADS", "MC_CORES"]
write("result.json", {"ok": True, "env": {n: os.environ.get(n) for n in names}})
st.update({"status": "DONE", "stage": "COMPLETED", "progress": 100, "ok": True})
write("status.json", st)
"""


@pytest.mark.skipif(os.name != "posix", reason="process-group cancel is POSIX-only")
def test_a_full_service_refuses_the_next_job_and_accepts_it_once_a_slot_frees(
    tmp_path, manager_module, monkeypatch
):
    """One job slot: the second submit must not start a second process."""
    _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=200)
    mgr = _manager(manager_module, tmp_path, LONG_RUNNER)
    assert mgr.capacity.job_slots == 1

    first = mgr.submit(file_path=None, params={}, run_id="run-a")
    with pytest.raises(manager_module.JobRejected) as rejected:
        mgr.submit(file_path=None, params={}, run_id="run-b")
    assert rejected.value.admission.code == "METHOD_BUSY"
    assert "job slot" in rejected.value.admission.reason
    # Nothing was created for the refused job.
    assert sorted(p.name for p in (tmp_path / "jobs" / "gctree").iterdir()) == [first]

    report = mgr.capacity_report()
    assert (report["running_jobs"], report["free_slots"], report["accepting"]) == (1, 0, False)

    _wait_for_status(mgr, first, {"RUNNING"})
    mgr.cancel(first)
    deadline = time.time() + 15
    while mgr.running_jobs() and time.time() < deadline:
        time.sleep(0.1)
    assert mgr.running_jobs() == 0
    assert mgr.capacity_report()["accepting"] is True
    second = mgr.submit(file_path=None, params={}, run_id="run-b")
    assert second != first
    mgr.cancel(second)


def test_a_finished_job_frees_its_slot_without_a_cancel(tmp_path, manager_module, monkeypatch):
    _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=200)
    mgr = _manager(manager_module, tmp_path, DONE_RUNNER)
    for index in range(3):  # three jobs through one slot, one after the other
        job_id = mgr.submit(file_path=None, params={}, run_id=f"run-{index}")
        assert _wait_for_status(mgr, job_id, {"DONE"})["status"] == "DONE"
        deadline = time.time() + 10
        while mgr.running_jobs() and time.time() < deadline:
            time.sleep(0.05)
        assert mgr.running_jobs() == 0


def test_a_job_is_not_started_when_its_memory_does_not_fit(tmp_path, manager_module, monkeypatch):
    """A free slot is not enough: memory does not degrade gracefully."""
    # 1024 MiB limit, 10% headroom -> 921 MiB budget; 700 in use + 256 per job > 921.
    _fake_cgroup(tmp_path, monkeypatch, cpus=4, memory_mb=1024, in_use_mb=700)
    mgr = _manager(manager_module, tmp_path, DONE_RUNNER)
    assert mgr.capacity.job_slots >= 1
    with pytest.raises(manager_module.JobRejected) as rejected:
        mgr.submit(file_path=None, params={}, run_id="run-m")
    assert rejected.value.admission.code == "METHOD_BUSY"
    assert "Not enough free memory" in rejected.value.admission.reason
    assert not (tmp_path / "jobs" / "gctree").exists() or not list((tmp_path / "jobs" / "gctree").iterdir())

    # Memory is released (another job finished): the same submit now succeeds.
    (tmp_path / "cgroup" / "memory.current").write_text(f"{300 * MIB}\n")
    job_id = mgr.submit(file_path=None, params={}, run_id="run-m")
    assert _wait_for_status(mgr, job_id, {"DONE"})["status"] == "DONE"


def test_a_container_too_small_for_any_job_reports_a_configuration_error(
    tmp_path, manager_module, monkeypatch
):
    _fake_cgroup(tmp_path, monkeypatch, cpus=2, memory_mb=300, in_use_mb=50)
    mgr = _manager(manager_module, tmp_path, DONE_RUNNER)
    assert mgr.capacity.job_slots == 0
    with pytest.raises(manager_module.JobRejected) as rejected:
        mgr.submit(file_path=None, params={}, run_id="run-x")
    assert rejected.value.admission.code == "INSUFFICIENT_CAPACITY"
    report = mgr.capacity_report()
    assert report["accepting"] is False and report["code"] == "INSUFFICIENT_CAPACITY"


@pytest.mark.parametrize("cpus,max_jobs,threads", [(4, 1, "4"), (4, 2, "2"), (4, 4, "1"), (0.6, 1, "1")])
def test_each_job_inherits_its_cpu_budget(tmp_path, manager_module, monkeypatch, cpus, max_jobs, threads):
    _fake_cgroup(tmp_path, monkeypatch, cpus=cpus, memory_mb=8192, in_use_mb=100,
                 METHOD_MAX_CONCURRENT_JOBS=max_jobs)
    mgr = _manager(manager_module, tmp_path, ENV_RUNNER)
    assert (mgr.capacity.job_slots, str(mgr.capacity.threads_per_job)) == (max_jobs, threads)
    job_id = mgr.submit(file_path=None, params={}, run_id="run-env")
    assert _wait_for_status(mgr, job_id, {"DONE"})["status"] == "DONE"
    payload, code = mgr.result(job_id)
    assert code == 200
    assert payload["env"] == {
        "PHYLO_JOB_THREADS": threads, "OMP_NUM_THREADS": threads, "OMP_THREAD_LIMIT": threads,
        "OPENBLAS_NUM_THREADS": threads, "MC_CORES": threads,
    }
    assert mgr.status(job_id)["threads"] == int(threads)


def test_capacity_report_describes_the_container(tmp_path, manager_module, monkeypatch):
    _fake_cgroup(tmp_path, monkeypatch, cpus=2.5, memory_mb=2048, in_use_mb=300)
    report = _manager(manager_module, tmp_path, DONE_RUNNER).capacity_report()
    assert report["ok"] is True and report["method_id"] == "gctree"
    assert report["cpus"] == 2.5 and report["memory_limit_mb"] == 2048
    assert report["memory_in_use_mb"] == 300
    assert (report["job_slots"], report["threads_per_job"], report["running_jobs"], report["free_slots"]) == (2, 1, 0, 2)
    assert report["accepting"] is True and report["code"] == "ACCEPT"


# --------------------------------------------------------------------------- #
# No job stays "running" for ever: time limit, lost process, restart
# --------------------------------------------------------------------------- #
CRASH_RUNNER = _RUNNER_PRELUDE + """
os._exit(3)
"""

KILLED_RUNNER = _RUNNER_PRELUDE + """
import signal
os.kill(os.getpid(), signal.SIGKILL)
"""

# Simulates the kernel's out-of-memory killer: the counter goes up, the job dies.
OOM_RUNNER = _RUNNER_PRELUDE + """
import signal
events = os.path.join(os.environ["PHYLO_CGROUP_ROOT"], "memory.events")
with open(events, "w") as f:
    f.write("low 0\\nhigh 0\\nmax 3\\noom 1\\noom_kill 1\\n")
os.kill(os.getpid(), signal.SIGKILL)
"""

CHATTY_LONG_RUNNER = _RUNNER_PRELUDE + """
with open(os.path.join(sd, "job.log"), "w") as f:
    f.write("step 1 done\\nstep 2 started\\n")
time.sleep(60)
"""

CHILD_ENV_RUNNER = _RUNNER_PRELUDE + """
write("result.json", {"ok": True, "child": os.environ.get("PHYLO_JOB_CHILD"),
                      "oom_baseline": os.environ.get("PHYLO_JOB_OOM_BASELINE")})
st.update({"status": "DONE", "stage": "COMPLETED", "progress": 100, "ok": True})
write("status.json", st)
"""


def _wait_idle(mgr, timeout: float = 10.0) -> int:
    """Wait for finished job processes to exit. A job writes its final status
    first and exits a moment later, so "DONE" can be visible while the process
    is still on its way out."""
    deadline = time.time() + timeout
    while mgr.running_jobs() and time.time() < deadline:
        time.sleep(0.05)
    return mgr.running_jobs()


def _pid_gone(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        time.sleep(0.1)
    return False


@pytest.mark.skipif(os.name != "posix", reason="process-group termination is POSIX-only")
def test_a_job_past_its_time_limit_is_stopped_and_reported_as_timeout(tmp_path, manager_module, monkeypatch):
    _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=100)
    monkeypatch.setattr(manager_module, "CANCEL_GRACE_SECONDS", 0.5)
    mgr = _manager(manager_module, tmp_path, CHATTY_LONG_RUNNER)
    job_id = mgr.submit(file_path=None, params={}, run_id="run-slow", timeout_seconds=1)
    running = _wait_for_status(mgr, job_id, {"RUNNING"})
    assert running["timeout_seconds"] == 1
    pid = running["pid"]

    final = _wait_for_status(mgr, job_id, {"ERROR"}, timeout=15)
    assert final["status"] == "ERROR" and final["error_code"] == "TIMEOUT"
    assert "time limit of 1 second" in final["message"]
    assert final["error"]["error_code"] == "TIMEOUT" and final["error"]["manifest_version"] == 1
    # The job's own last output is kept with the failure.
    tail = [e["out"] for e in final["error"]["logs"] if e["step"] == "method.job.log_tail"]
    assert tail and "step 2 started" in tail[0]
    assert _pid_gone(pid)                                   # really stopped
    assert mgr.running_jobs() == 0                          # and its slot is free again
    assert mgr.capacity_report()["accepting"] is True
    assert mgr.result(job_id) == (None, 409)                # an ERROR job has no result to fetch


@pytest.mark.skipif(os.name != "posix", reason="process-group termination is POSIX-only")
def test_a_job_that_finishes_in_time_is_not_touched_by_its_time_limit(tmp_path, manager_module, monkeypatch):
    _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=100)
    mgr = _manager(manager_module, tmp_path, DONE_RUNNER)
    job_id = mgr.submit(file_path=None, params={}, run_id="run-fast", timeout_seconds=30)
    assert _wait_for_status(mgr, job_id, {"DONE"})["status"] == "DONE"
    assert _wait_idle(mgr) == 0
    assert job_id not in mgr._timers                        # the timer is cancelled with the job


def test_the_service_default_time_limit_applies_when_the_caller_sends_none(tmp_path, manager_module, monkeypatch):
    _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=100)
    monkeypatch.setenv("METHOD_JOB_TIMEOUT_SECONDS", "900")
    mgr = _manager(manager_module, tmp_path, DONE_RUNNER)
    def limit_of(jid):
        return json.loads((mgr.jobs_root / jid / "meta.json").read_text())["timeout_seconds"]

    job_id = mgr.submit(file_path=None, params={}, run_id="run-default")
    assert limit_of(job_id) == 900
    assert _wait_for_status(mgr, job_id, {"DONE"})["timeout_seconds"] == 900
    monkeypatch.setenv("METHOD_JOB_TIMEOUT_SECONDS", "junk")     # a typo means "no limit", not a crash
    assert _wait_idle(mgr) == 0
    other = mgr.submit(file_path=None, params={}, run_id="run-junk")
    assert limit_of(other) is None
    assert "timeout_seconds" not in _wait_for_status(mgr, other, {"DONE"})


@pytest.mark.parametrize("runner,how", [(CRASH_RUNNER, "exit code 3"), (KILLED_RUNNER, "signal 9")])
@pytest.mark.skipif(os.name != "posix", reason="POSIX signals")
def test_a_job_whose_process_dies_without_a_result_is_reported_as_failed(
    tmp_path, manager_module, monkeypatch, runner, how
):
    """Before: its status said RUNNING for ever and the run never ended."""
    _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=100)
    mgr = _manager(manager_module, tmp_path, runner)
    job_id = mgr.submit(file_path=None, params={}, run_id="run-dies")
    final = _wait_for_status(mgr, job_id, {"ERROR"})
    assert final["status"] == "ERROR" and final["error_code"] == "JOB_PROCESS_LOST"
    assert how in final["message"]
    assert mgr.running_jobs() == 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX signals")
def test_an_out_of_memory_kill_is_named_as_such_and_frees_the_slot(tmp_path, manager_module, monkeypatch):
    root = _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=512, in_use_mb=100,
                        METHOD_JOB_MEMORY_MB=64, METHOD_BASELINE_MEMORY_MB=64)
    (root / "memory.events").write_text("low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n")
    mgr = _manager(manager_module, tmp_path, OOM_RUNNER)
    assert mgr.capacity.job_slots == 1
    job_id = mgr.submit(file_path=None, params={}, run_id="run-oom")
    final = _wait_for_status(mgr, job_id, {"ERROR"})
    assert final["error_code"] == "OUT_OF_MEMORY"
    assert "ran out of memory (limit 512 MiB)" in final["message"]
    assert "raise the memory limit" in final["message"]
    # The slot is free: the next job is accepted.
    assert mgr.capacity_report()["free_slots"] == 1
    assert mgr.submit(file_path=None, params={}, run_id="run-after-oom")


def test_reaping_a_dead_job_also_records_its_failure(tmp_path, manager_module, monkeypatch):
    """The capacity check reaps finished processes; it must not lose the fact
    that one of them never reported a result."""
    _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=100)
    mgr = _manager(manager_module, tmp_path, CRASH_RUNNER)
    job_id = mgr.submit(file_path=None, params={}, run_id="run-reaped")
    mgr._procs[job_id].wait(timeout=10)
    assert mgr.capacity_report()["running_jobs"] == 0       # reaps
    st = mgr.status(job_id)
    assert st["status"] == "ERROR" and st["error_code"] == "JOB_PROCESS_LOST"


def test_jobs_interrupted_by_a_service_restart_are_closed_at_start_up(tmp_path, manager_module, monkeypatch):
    _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=100)
    jobs_dir = tmp_path / "jobs"
    for job_id, status in (("interrupted", "RUNNING"), ("queued", "QUEUED"), ("finished", "DONE"),
                           ("failed", "ERROR"), ("cancelled", "CANCELLED")):
        state = jobs_dir / "gctree" / job_id
        state.mkdir(parents=True)
        # pid 1 is alive in every container: recovery must not trust a stale pid.
        (state / "status.json").write_text(json.dumps({"job_id": job_id, "status": status, "pid": 1}))
    restarted = manager_module.JobManager("gctree", jobs_dir=str(jobs_dir), runner_path=_write_runner(tmp_path, DONE_RUNNER))

    assert restarted.recover_interrupted_jobs() == 2
    for job_id in ("interrupted", "queued"):
        st = restarted.status(job_id)
        assert st["status"] == "ERROR" and st["error_code"] == "METHOD_RESTARTED"
        assert "restarted" in st["message"] and "submit it again" in st["message"]
    assert restarted.status("finished")["status"] == "DONE"
    assert restarted.status("failed")["status"] == "ERROR" and "error_code" not in restarted.status("failed")
    assert restarted.status("cancelled")["status"] == "CANCELLED"
    assert restarted.recover_interrupted_jobs() == 0        # nothing left to close


def test_recovery_leaves_this_services_own_running_jobs_alone(tmp_path, manager_module, monkeypatch):
    _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=100)
    mgr = _manager(manager_module, tmp_path, LONG_RUNNER)
    job_id = mgr.submit(file_path=None, params={}, run_id="run-mine")
    _wait_for_status(mgr, job_id, {"RUNNING"})
    assert mgr.recover_interrupted_jobs() == 0
    assert mgr.status(job_id)["status"] == "RUNNING"
    assert mgr.cancel(job_id)["status"] == "CANCELLED"


def test_an_unknown_running_job_is_reported_as_interrupted_even_without_start_up_recovery(
    tmp_path, manager_module, monkeypatch
):
    _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=100)
    state = tmp_path / "jobs" / "gctree" / "old"
    state.mkdir(parents=True)
    (state / "status.json").write_text(json.dumps({"job_id": "old", "status": "RUNNING", "pid": os.getpid()}))
    mgr = _manager(manager_module, tmp_path, DONE_RUNNER)
    assert mgr.status("old")["error_code"] == "METHOD_RESTARTED"


@pytest.mark.skipif(os.name != "posix", reason="process-group cancel is POSIX-only")
def test_submitting_the_same_run_again_returns_its_running_job(tmp_path, manager_module, monkeypatch):
    """A worker that lost the answer to its submit must not start a second job."""
    _fake_cgroup(tmp_path, monkeypatch, cpus=4, memory_mb=8192, in_use_mb=100, METHOD_MAX_CONCURRENT_JOBS=4)
    mgr = _manager(manager_module, tmp_path, LONG_RUNNER)
    first = mgr.submit(file_path=None, params={}, run_id="run-same")
    assert mgr.submit(file_path=None, params={}, run_id="run-same") == first
    assert mgr.running_jobs() == 1
    other = mgr.submit(file_path=None, params={}, run_id="run-other")
    assert other != first and mgr.running_jobs() == 2
    mgr.cancel(first)
    _pid_gone(mgr._procs[first].pid if first in mgr._procs else 0)
    again = mgr.submit(file_path=None, params={}, run_id="run-same")     # the old job is over: a new one may start
    assert again != first
    for jid in (other, again):
        mgr.cancel(jid)


@pytest.mark.skipif(os.name != "posix", reason="process-group cancel is POSIX-only")
def test_cancel_keeps_the_end_of_the_jobs_output(tmp_path, manager_module, monkeypatch):
    _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=100)
    mgr = _manager(manager_module, tmp_path, CHATTY_LONG_RUNNER)
    job_id = mgr.submit(file_path=None, params={}, run_id="run-cancel")
    _wait_for_status(mgr, job_id, {"RUNNING"})
    time.sleep(0.3)
    final = mgr.cancel(job_id)
    assert final["status"] == "CANCELLED" and "step 2 started" in final["log_tail"]
    assert mgr.status(job_id)["status"] == "CANCELLED"      # a later status request does not change it


def test_the_job_process_is_marked_as_a_job_and_knows_the_memory_kill_count(tmp_path, manager_module, monkeypatch):
    root = _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=100)
    (root / "memory.events").write_text("oom 4\noom_kill 4\n")
    mgr = _manager(manager_module, tmp_path, CHILD_ENV_RUNNER)
    job_id = mgr.submit(file_path=None, params={}, run_id="run-child")
    _wait_for_status(mgr, job_id, {"DONE"})
    payload, _ = mgr.result(job_id)
    assert payload == {"ok": True, "child": "1", "oom_baseline": "4"}


# --------------------------------------------------------------------------- #
# Disk use returns to where it was: scratch data, job records, bounded logs
# --------------------------------------------------------------------------- #
SCRATCH_RUNNER = _RUNNER_PRELUDE + """
import tempfile
work = tempfile.mkdtemp(prefix="method_")            # what the methods do
with open(os.path.join(work, "big.tmp"), "wb") as f:
    f.write(b"x" * 100000)
write("result.json", {"ok": True, "tmpdir": os.environ.get("TMPDIR"), "work": work})
if a.job_id and os.environ.get("STAY") == "1":
    time.sleep(60)
st.update({"status": "DONE", "stage": "COMPLETED", "progress": 100, "ok": True})
write("status.json", st)
"""

SCRATCH_LONG_RUNNER = _RUNNER_PRELUDE + """
import tempfile
work = tempfile.mkdtemp(prefix="method_")
with open(os.path.join(work, "big.tmp"), "wb") as f:
    f.write(b"x" * 100000)
with open(os.path.join(sd, "job.log"), "w") as f:
    f.write("started\\n")
time.sleep(60)
"""


def _job_dir(mgr, job_id) -> Path:
    return mgr.jobs_root / job_id


def test_each_job_gets_its_own_scratch_directory_which_is_removed_when_it_ends(tmp_path, manager_module, monkeypatch):
    _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=100)
    mgr = _manager(manager_module, tmp_path, SCRATCH_RUNNER)
    job_id = mgr.submit(file_path=None, params={}, run_id="run-scratch")
    assert _wait_for_status(mgr, job_id, {"DONE"})["status"] == "DONE"
    payload, _ = mgr.result(job_id)
    scratch = _job_dir(mgr, job_id) / "tmp"
    assert payload["tmpdir"] == str(scratch)                          # TMPDIR pointed into the job's own directory
    assert Path(payload["work"]).parent == scratch                    # so the method's temp files landed there
    assert _wait_idle(mgr) == 0
    assert not scratch.exists()                                       # gone as soon as the job is over
    assert (_job_dir(mgr, job_id) / "result.json").exists()           # the small record stays until collected


@pytest.mark.skipif(os.name != "posix", reason="process-group termination is POSIX-only")
@pytest.mark.parametrize("ending", ["cancel", "timeout"])
def test_scratch_data_is_removed_however_the_job_ends(tmp_path, manager_module, monkeypatch, ending):
    _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=100)
    monkeypatch.setattr(manager_module, "CANCEL_GRACE_SECONDS", 0.5)
    mgr = _manager(manager_module, tmp_path, SCRATCH_LONG_RUNNER)
    job_id = mgr.submit(file_path=None, params={}, run_id="run-x", timeout_seconds=1 if ending == "timeout" else None)
    scratch = _job_dir(mgr, job_id) / "tmp"
    deadline = time.time() + 10
    while not any(scratch.glob("*/big.tmp")) and time.time() < deadline:
        time.sleep(0.05)
    assert any(scratch.glob("*/big.tmp"))                             # 100 kB of scratch data exists
    if ending == "cancel":
        assert mgr.cancel(job_id)["status"] == "CANCELLED"
    else:
        assert _wait_for_status(mgr, job_id, {"ERROR"}, timeout=15)["error_code"] == "TIMEOUT"
    assert not scratch.exists()


def test_a_log_is_offered_whole_when_small_and_with_its_ends_when_large(tmp_path, manager_module):
    log = tmp_path / "job.log"
    log.write_bytes(b"line\n" * 10)
    assert manager_module.bounded_log(log, 1000) == (b"line\n" * 10, False)

    body = b"".join(f"{i:07d}\n".encode() for i in range(50_000))    # 400 kB
    log.write_bytes(body)
    content, was_cut = manager_module.bounded_log(log, 10_000)
    assert was_cut and len(content) < 10_000 + 400
    assert content.startswith(b"0000000\n0000001\n")                  # how it began
    assert content.endswith(b"0049998\n0049999\n")                    # how it ended
    assert b"390000 bytes of this log were left out" in content and b"400000 bytes long" in content
    assert manager_module.bounded_log(tmp_path / "missing.log", 10) == (b"", False)


def test_log_size_setting(manager_module, monkeypatch):
    monkeypatch.delenv("METHOD_JOB_LOG_MAX_MB", raising=False)
    assert manager_module.log_max_bytes() == 5 * 1024 * 1024
    monkeypatch.setenv("METHOD_JOB_LOG_MAX_MB", "0.5")
    assert manager_module.log_max_bytes() == 524288
    for junk in ("0", "-1", "big"):
        monkeypatch.setenv("METHOD_JOB_LOG_MAX_MB", junk)
        assert manager_module.log_max_bytes() == 5 * 1024 * 1024


@pytest.mark.skipif(os.name != "posix", reason="process-group cancel is POSIX-only")
def test_a_finished_job_can_be_collected_and_then_nothing_of_it_remains(tmp_path, manager_module, monkeypatch):
    _fake_cgroup(tmp_path, monkeypatch, cpus=2, memory_mb=8192, in_use_mb=100, METHOD_MAX_CONCURRENT_JOBS=2)
    monkeypatch.setenv("METHOD_JOB_LOG_MAX_MB", "0.001")              # about 1 kB
    mgr = _manager(manager_module, tmp_path, SCRATCH_LONG_RUNNER)
    running = mgr.submit(file_path=None, params={}, run_id="run-live")
    _wait_for_status(mgr, running, {"RUNNING"})
    assert mgr.delete(running) == 409 and _job_dir(mgr, running).is_dir()   # never while it runs

    (_job_dir(mgr, running) / "job.log").write_bytes(b"y" * 5000)
    content, was_cut = mgr.log(running)
    assert was_cut and len(content) < 1500                            # served in bounded form
    assert mgr.log("0" * 32) is None

    mgr.cancel(running)
    assert mgr.delete(running) == 200
    assert not _job_dir(mgr, running).exists()
    assert mgr.status(running) is None and mgr.delete(running) == 404
    assert mgr.running_jobs() == 0
    # Only real job ids are accepted: a path is not a job.
    for bad in ("../" + running, "..", ".", "a/b", "", "x" * 100):
        assert mgr.delete(bad) == 404
    assert mgr.jobs_root.is_dir()


def test_records_nobody_collected_are_removed_after_the_retention_time(tmp_path, manager_module, monkeypatch):
    _fake_cgroup(tmp_path, monkeypatch, cpus=1, memory_mb=4096, in_use_mb=100)
    monkeypatch.setenv("METHOD_JOB_RETENTION_HOURS", "24")
    mgr = _manager(manager_module, tmp_path, DONE_RUNNER)
    old_time = time.time() - 25 * 3600
    for job_id, status, aged in (("oldfinished", "DONE", True), ("oldfailed", "ERROR", True),
                                 ("recent", "DONE", False), ("interrupted", "RUNNING", True)):
        state = mgr.jobs_root / job_id
        (state / "tmp" / "leftover").mkdir(parents=True)
        (state / "status.json").write_text(json.dumps({"job_id": job_id, "status": status}))
        if aged:
            for path in (state / "status.json", state / "tmp" / "leftover", state / "tmp", state):
                os.utime(path, (old_time, old_time))
    assert mgr.purge_expired() == 2
    assert not (mgr.jobs_root / "oldfinished").exists() and not (mgr.jobs_root / "oldfailed").exists()
    assert (mgr.jobs_root / "recent" / "status.json").exists()        # kept: within the retention time
    assert not (mgr.jobs_root / "recent" / "tmp").exists()            # but its scratch data is not
    assert (mgr.jobs_root / "interrupted" / "tmp").exists()           # unsettled jobs are left to recovery
    # Start-up recovery closes the interrupted job and tidies up in the same pass.
    assert mgr.recover_interrupted_jobs() == 1
    assert not (mgr.jobs_root / "interrupted" / "tmp").exists()
    # Submitting a job tidies up as well.
    os.utime(mgr.jobs_root / "recent" / "status.json", (old_time, old_time))
    os.utime(mgr.jobs_root / "recent", (old_time, old_time))
    job_id = mgr.submit(file_path=None, params={}, run_id="run-new")
    assert not (mgr.jobs_root / "recent").exists()
    _wait_for_status(mgr, job_id, {"DONE"})
