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


class MethodServiceUnavailable(Exception):
    """No URL configured for the method service."""


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
) -> str:
    """Submit a job and return its job_id. Returns quickly."""
    base = _base_or_raise(method_id)
    routes = get_service_routes(method_id)
    url = f"{base}{routes['jobs']}"
    payload: dict[str, Any] = {"file_path": file_path, "params": params or {}}
    if run_id is not None:
        payload["run_id"] = run_id

    async with httpx.AsyncClient(timeout=JOB_SUBMIT_TIMEOUT, trust_env=False) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    job_id = data.get("job_id")
    if not job_id:
        raise RuntimeError(f"Method service '{method_id}' did not return a job_id: {data!r}")
    return str(job_id)


async def get_job_status(method_id: str, job_id: str) -> JobStatus:
    base = _base_or_raise(method_id)
    routes = get_service_routes(method_id)
    url = _job_url(base, routes["jobStatus"], job_id)

    async with httpx.AsyncClient(timeout=JOB_STATUS_TIMEOUT, trust_env=False) as client:
        resp = await client.get(url)
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
