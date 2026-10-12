"""Async client for the method-service /jobs contract.

The worker submits a job, polls status, fetches the result and cancels jobs.
No request is ever held open for the duration of a model run.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from apps.api.config import method_service_url
from apps.api.contracts.loader import get_service_routes

# Short timeouts for control-plane calls; result download can be larger.
JOB_SUBMIT_TIMEOUT = int(os.getenv("JOB_SUBMIT_TIMEOUT", "30"))
JOB_STATUS_TIMEOUT = int(os.getenv("JOB_STATUS_TIMEOUT", "30"))
JOB_CANCEL_TIMEOUT = int(os.getenv("JOB_CANCEL_TIMEOUT", "30"))
JOB_RESULT_TIMEOUT = int(os.getenv("JOB_RESULT_TIMEOUT", "300"))
CAPACITY_TIMEOUT = int(os.getenv("METHOD_CAPACITY_TIMEOUT", "5"))


class MethodServiceUnavailable(Exception):
    """No URL configured for the method service."""


class MethodBusy(Exception):
    """The method service did not start the job because it has no free capacity
    right now (HTTP 429). The run should stay queued and be offered again."""

    def __init__(self, reason: str, retry_after_seconds: int = 10):
        super().__init__(reason)
        self.reason = reason
        self.retry_after_seconds = max(1, int(retry_after_seconds or 10))


class MethodJobNotFound(Exception):
    """The method service answered, but does not know this job (HTTP 404). Its
    job records are gone, typically because the container was recreated, so the
    job can no longer be followed."""


class MethodCapacityError(Exception):
    """The method service can never run this job with its current limits (HTTP
    507). Waiting will not help; the run fails with this explanation."""


@dataclass
class MethodCapacity:
    """What a method service reports on GET /capacity."""

    method_id: str
    job_slots: int
    running_jobs: int
    free_slots: int
    threads_per_job: int
    accepting: bool
    code: str = "ACCEPT"
    reason: str = ""
    cpus: Optional[float] = None
    memory_limit_mb: Optional[int] = None
    raw: Optional[dict[str, Any]] = None


@dataclass
class JobStatus:
    ok: bool
    job_id: Optional[str]
    status: str  # QUEUED | RUNNING | DONE | ERROR | CANCELLED
    stage: Optional[str] = None
    message: Optional[str] = None
    progress: Optional[int] = None
    error: Optional[Any] = None
    raw: Optional[dict[str, Any]] = None


def _base_or_raise(method_id: str) -> str:
    base = method_service_url(method_id)
    if not base:
        raise MethodServiceUnavailable(
            f"No service URL configured for method '{method_id}'. "
            f"Set METHOD_{method_id.upper()}_URL."
        )
    return base.rstrip("/")


def _job_url(base: str, route_template: str, job_id: str) -> str:
    path = route_template.replace("{job_id}", job_id)
    return f"{base}{path}"


async def submit_job(
    method_id: str,
    *,
    file_path: Optional[str],
    params: dict[str, Any],
    run_id: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
) -> str:
    """Submit a job and return its job_id. Returns quickly.

    ``timeout_seconds`` asks the service to stop the job itself after that long,
    as a backstop for when the worker is not there to do it. Submitting the same
    ``run_id`` again while its job is still active returns that job's id rather
    than starting a second one.
    """
    base = _base_or_raise(method_id)
    routes = get_service_routes(method_id)
    url = f"{base}{routes['jobs']}"
    payload: dict[str, Any] = {"file_path": file_path, "params": params or {}}
    if run_id is not None:
        payload["run_id"] = run_id
    if timeout_seconds is not None and timeout_seconds > 0:
        payload["timeout_seconds"] = int(timeout_seconds)

    async with httpx.AsyncClient(timeout=JOB_SUBMIT_TIMEOUT, trust_env=False) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code in (429, 507):
            reason, retry_after = _rejection_details(resp, method_id)
            if resp.status_code == 429:
                raise MethodBusy(reason, retry_after)
            raise MethodCapacityError(reason)
        resp.raise_for_status()
        data = resp.json()
    job_id = data.get("job_id")
    if not job_id:
        raise RuntimeError(f"Method service '{method_id}' did not return a job_id: {data!r}")
    return str(job_id)


def _rejection_details(resp: httpx.Response, method_id: str) -> tuple[str, int]:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    reason = str(body.get("error") or body.get("reason") or f"The {method_id} service has no free capacity.")
    retry_raw = body.get("retry_after_seconds") or resp.headers.get("Retry-After") or 10
    try:
        retry_after = int(float(retry_raw))
    except (TypeError, ValueError):
        retry_after = 10
    return reason, retry_after


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def get_capacity(method_id: str) -> Optional[MethodCapacity]:
    """Ask a method service how much it can run right now.

    Returns None when the service has no capacity endpoint (an older build): the
    caller then falls back to offering jobs and honouring a busy answer. Network
    errors propagate, so an unreachable service is not mistaken for a free one.
    """
    base = _base_or_raise(method_id)
    routes = get_service_routes(method_id)
    async with httpx.AsyncClient(timeout=CAPACITY_TIMEOUT, trust_env=False) as client:
        resp = await client.get(f"{base}{routes['capacity']}")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or "job_slots" not in data:
        return None
    slots = max(0, _as_int(data.get("job_slots")))
    running = max(0, _as_int(data.get("running_jobs")))
    return MethodCapacity(
        method_id=method_id,
        job_slots=slots,
        running_jobs=running,
        free_slots=max(0, _as_int(data.get("free_slots"), slots - running)),
        threads_per_job=max(1, _as_int(data.get("threads_per_job"), 1)),
        accepting=bool(data.get("accepting", True)),
        code=str(data.get("code") or "ACCEPT"),
        reason=str(data.get("reason") or ""),
        cpus=data.get("cpus") if isinstance(data.get("cpus"), (int, float)) else None,
        memory_limit_mb=data.get("memory_limit_mb") if isinstance(data.get("memory_limit_mb"), int) else None,
        raw=data,
    )


async def get_job_status(method_id: str, job_id: str) -> JobStatus:
    base = _base_or_raise(method_id)
    routes = get_service_routes(method_id)
    url = _job_url(base, routes["jobStatus"], job_id)

    async with httpx.AsyncClient(timeout=JOB_STATUS_TIMEOUT, trust_env=False) as client:
        resp = await client.get(url)
        if resp.status_code == 404:
            raise MethodJobNotFound(f"The {method_id} service does not know job {job_id}.")
        resp.raise_for_status()
        data = resp.json()

    progress = data.get("progress")
    try:
        progress = int(progress) if progress is not None else None
    except (TypeError, ValueError):
        progress = None

    return JobStatus(
        ok=bool(data.get("ok", True)),
        job_id=data.get("job_id", job_id),
        status=str(data.get("status", "RUNNING")).upper(),
        stage=data.get("stage"),
        message=data.get("message"),
        progress=progress,
        error=data.get("error"),
        raw=data,
    )


async def get_job_result(method_id: str, job_id: str) -> dict[str, Any]:
    base = _base_or_raise(method_id)
    routes = get_service_routes(method_id)
    url = _job_url(base, routes["jobResult"], job_id)

    async with httpx.AsyncClient(timeout=JOB_RESULT_TIMEOUT, trust_env=False) as client:
        resp = await client.get(url)
        if resp.status_code == 404:
            raise MethodJobNotFound(f"The {method_id} service does not know job {job_id}.")
        resp.raise_for_status()
        return resp.json()


async def cancel_job(method_id: str, job_id: str) -> bool:
    """Idempotently request cancellation of a method job. Best-effort."""
    base = _base_or_raise(method_id)
    routes = get_service_routes(method_id)
    url = _job_url(base, routes["jobCancel"], job_id)

    async with httpx.AsyncClient(timeout=JOB_CANCEL_TIMEOUT, trust_env=False) as client:
        # Contract allows POST or DELETE; we use POST.
        resp = await client.post(url)
        # A terminal job may return 200 or 409; both are acceptable for idempotency.
        return resp.status_code < 500


async def get_job_log(method_id: str, job_id: str) -> Optional[str]:
    """The job's log as the service offers it (already cut to its size limit).
    None when the service has no such job or no log route (an older build)."""
    base = _base_or_raise(method_id)
    routes = get_service_routes(method_id)
    url = _job_url(base, routes["jobLog"], job_id)
    async with httpx.AsyncClient(timeout=JOB_RESULT_TIMEOUT, trust_env=False) as client:
        resp = await client.get(url)
    if resp.status_code in (404, 405):
        return None
    resp.raise_for_status()
    return resp.text


async def delete_job(method_id: str, job_id: str) -> bool:
    """Tell the service it may forget a finished job (its record, log and any
    leftover scratch data). True when it did or had nothing to forget."""
    base = _base_or_raise(method_id)
    routes = get_service_routes(method_id)
    url = _job_url(base, routes["job"], job_id)
    async with httpx.AsyncClient(timeout=JOB_CANCEL_TIMEOUT, trust_env=False) as client:
        resp = await client.delete(url)
    return resp.status_code in (200, 204, 404)
