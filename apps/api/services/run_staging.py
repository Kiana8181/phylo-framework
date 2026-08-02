"""Staging, preprocessing and path-mapping helpers for run execution.

Extracted from routers/runs.py so routers stay thin and the worker can reuse
the exact same logic. Converts a stored input file into a method-service-visible
container path, applying preprocessing/column-mapping when required.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from apps.api.config import ROOT_DIR
from apps.api.preprocess.method_capabilities import extension_from_path, is_native_accept
from apps.api.preprocess.prepare_input import (
    TABULAR_EXTENSIONS,
    PreprocessError,
    prepare_input_for_method,
    should_apply_column_mapping,
    _preprocess_log,
)

METHOD_SERVICE_FILE_PREFIX = "METHOD_SERVICE_FILE_PREFIX"
HOST_RUNTIME_SHARED_ROOT = "HOST_RUNTIME_SHARED_ROOT"
STORAGE_LOCAL_PATH = "STORAGE_LOCAL_PATH"
DEFAULT_CONTAINER_RUNTIME_ROOT = Path("/runtime/storage")


# --------------------------------------------------------------------------- #
# Path resolution
# --------------------------------------------------------------------------- #
def storage_local_root_host() -> Path:
    raw = (os.getenv(STORAGE_LOCAL_PATH) or "runtime/storage").strip()
    root = Path(raw)
    if not root.is_absolute():
        root = ROOT_DIR / root
    return root.resolve()


def runtime_shared_root_host() -> Path:
    raw = (os.getenv(HOST_RUNTIME_SHARED_ROOT) or "").strip()
    if not raw:
        return storage_local_root_host()

    root = Path(raw)
    if not root.is_absolute():
        root = ROOT_DIR / root
        return root.resolve()

    # Guard against a common local-dev misconfiguration where a container-only
    # mount path is copied into host config.
    if root == DEFAULT_CONTAINER_RUNTIME_ROOT or DEFAULT_CONTAINER_RUNTIME_ROOT in root.parents:
        return storage_local_root_host()
    return root.resolve()


def runtime_shared_root_container() -> Path:
    raw = (os.getenv(METHOD_SERVICE_FILE_PREFIX) or "/runtime/storage").strip()
    root = Path(raw)
    if not root.is_absolute():
        root = Path("/") / raw.lstrip("/")
    return root


def to_container_path(host_path: Path) -> str:
    shared = runtime_shared_root_host().resolve()
    rel = host_path.resolve().relative_to(shared)
    return (runtime_shared_root_container() / rel).as_posix()


def resolve_storage_path_under_shared_mount(storage_path: str, storage: Any) -> Path | None:
    shared = runtime_shared_root_host().resolve()
    raw_path = Path(storage_path)
    candidates: list[Path] = []

    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.append(shared / raw_path)
        base_path = getattr(storage, "base_path", None)
        if isinstance(base_path, Path):
            candidates.append(base_path / raw_path)

    seen: set[str] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if not resolved.exists():
            continue
        try:
            resolved.relative_to(shared)
            return resolved
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# Sync IO helpers (call via asyncio.to_thread to avoid blocking the loop)
# --------------------------------------------------------------------------- #
def _run_work_dir_sync(run_id: UUID) -> Path:
    path = runtime_shared_root_host() / "runs" / str(run_id) / "work" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


async def run_work_dir(run_id: UUID) -> Path:
    return await asyncio.to_thread(_run_work_dir_sync, run_id)


def _path_is_file(p: Path) -> bool:
    return p.is_file()


def _path_exists(p: Path) -> bool:
    return p.exists()


def _write_bytes_to_path(path: Path, data: bytes) -> None:
    path.write_bytes(data)


async def stage_storage_path_to_workspace(storage_path: str, workspace: Path, storage: Any) -> Path:
    source = Path(storage_path)
    suffix = source.suffix.lower()
    staged = workspace / f"00_staged_input{suffix}"
    file_bytes = await storage.download(storage_path)
    await asyncio.to_thread(_write_bytes_to_path, staged, file_bytes)
    return staged


def cleanup_workspace(workspace: Path | None, run_id: UUID) -> None:
    if workspace is None:
        return
    if not workspace.exists():
        return

    allowed_root = (runtime_shared_root_host() / "runs" / str(run_id) / "work").resolve()
    try:
        workspace.resolve().relative_to(allowed_root)
    except ValueError:
        return

    shutil.rmtree(workspace, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Error payloads
# --------------------------------------------------------------------------- #
def structured_error_payload(*, code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message, "details": details}}


def _extract_error_message(value: Any) -> str | None:
    if isinstance(value, str):
        txt = value.strip()
        return txt or None
    if isinstance(value, dict):
        msg = value.get("message")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()
        code = value.get("code")
        if isinstance(code, str) and code.strip():
            return code.strip()
    return None


def normalize_failed_result_payload(
    raw_payload: Any,
    *,
    status_code: int | None = None,
    fallback_message: str | None = None,
) -> tuple[dict[str, Any], str]:
    payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
    payload["ok"] = False

    error_message = _extract_error_message(payload.get("error"))
    if not error_message:
        error_message = _extract_error_message(payload.get("message"))
    if not error_message and fallback_message:
        cleaned = fallback_message.strip()
        if cleaned:
            error_message = cleaned
    if not error_message and status_code is not None:
        error_message = f"Method service returned HTTP {status_code}."
    if not error_message:
        error_message = "Method service execution failed."

    payload.setdefault("error", error_message)
    if not isinstance(payload.get("logs"), list):
        payload["logs"] = []
    return payload, error_message


class StagingError(Exception):
    """Raised when staging/preprocessing fails; carries a structured payload."""

    def __init__(self, *, code: str, message: str, details: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        self.error_payload = structured_error_payload(code=code, message=message, details=self.details)
        # Populated by prepare_method_input so callers can clean up partial work.
        self.workspace: Optional[Path] = None
        super().__init__(message)


@dataclass
class StagedInput:
    container_path: str
    host_path: Path
    workspace: Optional[Path]
    # RunLogEntry-shaped records describing the preprocessing steps that ran.
    # The worker persists these into the run's `logs` so the transformations
    # applied to a run remain visible with its results.
    log_entries: list[dict[str, Any]] = field(default_factory=list)


async def prepare_method_input(
    *,
    run_id: UUID,
    method_id: str,
    original_storage_path: str,
    params: dict[str, Any],
    storage: Any,
) -> StagedInput:
    """Stage + (optionally) preprocess an input file into a container-visible path.

    Returns a StagedInput. Raises StagingError on any failure (with .workspace set
    for cleanup). The caller owns workspace cleanup (see cleanup_workspace)
    regardless of success/failure.
    """
    params = params or {}
    input_ext = extension_from_path(Path(original_storage_path))

    native_ok = False
    try:
        native_ok = is_native_accept(method_id, input_ext)  # type: ignore[arg-type]
    except Exception:
        native_ok = False

    force_preprocess = should_apply_column_mapping(method_id, input_ext, params)

    # Always route tabular uploads through the preprocess pipeline, even when
    # the method natively accepts the extension. The pipeline strips a UTF-8
    # BOM, drops fully-blank padding rows (Excel-style trailing
    # `;;;;;;...` lines), and rewrites with the canonical separator —
    # cleanups that downstream R / Python readers cannot all do on their own
    # and that the native-accept fast path would otherwise skip.
    if (
        not force_preprocess
        and native_ok
        and isinstance(input_ext, str)
        and input_ext in TABULAR_EXTENSIONS
    ):
        force_preprocess = True

    workspace: Path | None = None
    method_input_host_path: Path | None = None
    log_entries: list[dict[str, Any]] = []

    def _err(*, code: str, message: str, details: dict[str, Any]) -> StagingError:
        e = StagingError(code=code, message=message, details=details)
        e.workspace = workspace
        return e

    try:
        if native_ok and not force_preprocess:
            # The method consumes this extension as-is and no column mapping was
            # requested, so the preprocessing chain never runs. Record that
            # explicitly rather than leaving the run with no preprocessing trace.
            log_entries.append(
                _preprocess_log(
                    "skipped",
                    f"method={method_id}; input=.{input_ext} accepted natively; "
                    "no preprocessing applied",
                )
            )
            existing_shared = await asyncio.to_thread(
                resolve_storage_path_under_shared_mount, original_storage_path, storage
            )
            if existing_shared is not None and await asyncio.to_thread(_path_is_file, existing_shared):
                method_input_host_path = existing_shared
            else:
                workspace = await run_work_dir(run_id)
                try:
                    method_input_host_path = await stage_storage_path_to_workspace(
                        original_storage_path, workspace, storage
                    )
                except Exception as exc:
                    raise _err(
                        code="INVALID_FILE",
                        message="Failed to read uploaded file for method execution.",
                        details={
                            "method_id": method_id,
                            "storage_path": original_storage_path,
                            "next_actions": [
                                "Re-upload the input file and retry.",
                                "If the file came from file history, verify it still exists.",
                            ],
                            "technical_error": str(exc),
                        },
                    ) from exc
        else:
            workspace = await run_work_dir(run_id)
            try:
                staged_original = await stage_storage_path_to_workspace(
                    original_storage_path, workspace, storage
                )
            except Exception as exc:
                raise _err(
                    code="INVALID_FILE",
                    message="Failed to read uploaded file for preprocessing.",
                    details={
                        "method_id": method_id,
                        "storage_path": original_storage_path,
                        "next_actions": [
                            "Re-upload the input file and retry.",
                            "If the file came from file history, verify it still exists.",
                        ],
                        "technical_error": str(exc),
                    },
                ) from exc

            try:
                prepared = await asyncio.to_thread(
                    prepare_input_for_method,
                    method_id,  # type: ignore[arg-type]
                    staged_original,
                    params=params,
                    work_dir=workspace,
                )
                method_input_host_path = prepared.final_path
                log_entries.extend(prepared.log_entries)
            except PreprocessError as exc:
                pe = _err(code=exc.code, message=exc.message, details=exc.details)
                raise pe from exc

        path_exists = (
            await asyncio.to_thread(_path_exists, method_input_host_path)
            if method_input_host_path is not None
            else False
        )
        if method_input_host_path is None or not path_exists:
            raise _err(
                code="INVALID_FILE",
                message="Prepared input file is missing on the API server.",
                details={
                    "method_id": method_id,
                    "storage_path": original_storage_path,
                    "next_actions": [
                        "Retry the run.",
                        "Re-upload the input file if the issue persists.",
                    ],
                },
            )

        try:
            container_path = await asyncio.to_thread(to_container_path, method_input_host_path)
        except Exception as exc:
            raise _err(
                code="INTERNAL_PATH_ERROR",
                message="Prepared input is outside the shared runtime mount.",
                details={
                    "method_id": method_id,
                    "host_path": str(method_input_host_path),
                    "shared_root": str(runtime_shared_root_host()),
                    "next_actions": ["Contact support and include this run ID."],
                    "technical_error": str(exc),
                },
            ) from exc

        container_root = runtime_shared_root_container().as_posix().rstrip("/")
        if container_path != container_root and not container_path.startswith(f"{container_root}/"):
            raise _err(
                code="INTERNAL_PATH_ERROR",
                message="Method input path is not under the shared container runtime root.",
                details={
                    "method_id": method_id,
                    "file_path": container_path,
                    "container_root": container_root,
                    "next_actions": ["Contact support and include this run ID."],
                },
            )
    except StagingError as err:
        if err.workspace is None:
            err.workspace = workspace
        raise

    return StagedInput(
        container_path=container_path,
        host_path=method_input_host_path,
        workspace=workspace,
        log_entries=log_entries,
    )
