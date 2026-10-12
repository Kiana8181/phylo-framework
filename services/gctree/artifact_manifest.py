"""Convert a method result's artifact_files list into the persisted manifest.

Each input entry references a local file the handler wrote to its tempdir; this
helper uploads each file directly to the artifact bucket (no shared filesystem
with the worker) and replaces the list with a manifest of
``{object_key, size_bytes, checksum_sha256, ...}`` descriptors.

Run in the job child process via job_runner after the handler completes.
Never copies files into the run state dir — that whole shared-volume hop is
gone. No base64 anywhere in the pipeline.

A file that cannot be uploaded is never dropped silently: it is listed under
``artifact_upload_failures`` and :func:`storage_failure` turns that into the
reason the job did not complete. A result whose files are not stored is not a
finished result.

manifest_version: 1
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from object_storage import upload_artifact

MANIFEST_VERSION = 1
UPLOAD_FAILED_CODE = "ARTIFACT_UPLOAD_FAILED"

# Heavy / source-side keys removed from the payload before persisting.
_STRIP_KEYS = (
    "figures",
    "artifact_zip_b64",
    "artifact_name",
    "visualizations",
    "render",
    "artifact_files",
)


def _sanitize_name(name: str, default: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip()) or default
    return base


def materialize_artifacts(payload: Any, *, run_id: str, job_id: str) -> Any:
    """Upload each artifact_files entry to MinIO; return the worker-shaped manifest.

    Non-dict payloads (errors before the handler ran) pass through unchanged.
    Always stamps ``manifest_version`` so the worker accepts a successful result.
    """
    if not isinstance(payload, dict):
        return payload

    if not run_id or not job_id:
        raise ValueError("materialize_artifacts: run_id + job_id are required")

    artifacts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    af = payload.get("artifact_files")
    if isinstance(af, list):
        for entry in af:
            if not isinstance(entry, dict):
                continue
            src = entry.get("path")
            if not isinstance(src, str) or not src:
                continue
            src_path = Path(src)
            if not src_path.is_file():
                continue
            default_name = src_path.name
            filename = entry.get("filename") or default_name
            safe_name = _sanitize_name(str(filename), default_name)
            content_type = entry.get("content_type")
            try:
                uploaded = upload_artifact(
                    src_path,
                    run_id=run_id,
                    job_id=job_id,
                    filename=safe_name,
                    content_type=content_type if isinstance(content_type, str) else None,
                )
            except Exception as exc:  # noqa: BLE001
                # Keep uploading the rest, but remember the failure: the job
                # must not be reported as complete without this file.
                print(f"[artifact_manifest] upload failed for {safe_name}: {exc}", flush=True)
                failures.append({"filename": safe_name, "error": f"{type(exc).__name__}: {exc}"[:300]})
                continue
            desc: dict[str, Any] = {
                "object_key": uploaded["object_key"],
                "size_bytes": uploaded["size_bytes"],
                "checksum_sha256": uploaded["checksum_sha256"],
                "filename": safe_name,
                "kind": entry.get("kind") or "other",
                "role": entry.get("role"),
                "content_type": content_type,
                "previewable": bool(entry.get("previewable")),
            }
            if entry.get("tree_index") is not None:
                try:
                    desc["tree_index"] = int(entry["tree_index"])
                except (TypeError, ValueError):
                    pass
            artifacts.append(desc)

    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k in _STRIP_KEYS:
            continue
        if isinstance(k, str) and k.endswith("_b64"):
            continue
        out[k] = v
    out["manifest_version"] = MANIFEST_VERSION
    out["artifacts"] = artifacts
    if failures:
        out["artifact_upload_failures"] = failures
    return out


def storage_failure(payload: Any, materialize_error: Optional[str] = None) -> Optional[str]:
    """Why the job's result files are not all in storage, or None if they are.

    ``materialize_error`` is the message of an exception that stopped
    :func:`materialize_artifacts` altogether.
    """
    if materialize_error:
        return "The analysis finished, but its result files could not be saved to storage."
    failures = payload.get("artifact_upload_failures") if isinstance(payload, dict) else None
    if not isinstance(failures, list) or not failures:
        return None
    names = [str(f.get("filename") or "artifact") for f in failures if isinstance(f, dict)]
    shown = ", ".join(names[:5]) + (f", and {len(names) - 5} more" if len(names) > 5 else "")
    return (
        f"The analysis finished, but {len(failures)} result file(s) could not be saved "
        f"to storage ({shown})."
    )


def mark_storage_failure(payload: Any, message: str) -> dict[str, Any]:
    """The payload of a job that computed a result but could not store it."""
    out = dict(payload) if isinstance(payload, dict) else {}
    out["ok"] = False
    out["error"] = message
    out["error_code"] = UPLOAD_FAILED_CODE
    out.setdefault("manifest_version", MANIFEST_VERSION)
    out.setdefault("artifacts", [])
    return out
