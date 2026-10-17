"""Make ``os.cpu_count()`` report this job's CPU budget instead of the host's.

Python imports a module named ``sitecustomize`` at interpreter start-up when it
is on the import path. app.py puts this directory on PYTHONPATH for every
process the ClonalTree pipeline starts, so the patch reaches the pipeline's own
subprocesses without changing the pipeline (upstream code, kept unchanged in base-codes/).

Why it is needed: the pipeline sizes a ``multiprocessing.Pool`` with
``multiprocessing.cpu_count()``. Inside a container that returns the number of
cores of the HOST, not the container's CPU allowance, so on a 64-core server a
job limited to one CPU would start 64 worker processes. ``Pool.map`` returns
results in input order whatever the pool size, so capping it changes how fast
the clustering runs, not what it returns.

Active only when PHYLO_JOB_THREADS is set (the job manager and app.py set it).
"""
import os


def _apply() -> None:
    raw = (os.environ.get("PHYLO_JOB_THREADS") or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        return
    limit = int(raw)

    def _capped(real):
        def cpu_count():
            return max(1, min(real() or 1, limit))

        cpu_count.__doc__ = real.__doc__
        return cpu_count

    # multiprocessing.cpu_count() and Pool() look these up at call time.
    os.cpu_count = _capped(os.cpu_count)
    if hasattr(os, "process_cpu_count"):  # Python 3.13+
        os.process_cpu_count = _capped(os.process_cpu_count)


_apply()
