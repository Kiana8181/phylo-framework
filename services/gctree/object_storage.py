"""Direct upload of artifact files from the method service to MinIO/S3.

Methods write their final artifact files (PNGs, ZIPs, logs, etc.) to a local
tempdir during a job, then call :func:`upload_artifact` to stream each file
directly into the configured artifact bucket. The API worker never touches the
file — it only reads the resulting ``{object_key, size_bytes, checksum_sha256}``
descriptor from ``result.json`` and registers a DB row.

Credentials are a scoped MinIO user with ``s3:PutObject`` only on the artifact
bucket. The method has no read / list / delete permission. See
``minio-init`` in docker-compose.yml for the policy.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import boto3
from botocore.client import Config


_OBJECT_KEY_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_CHUNK = 1024 * 1024


def _sanitize_filename(name: str, default: str = "artifact") -> str:
    base = os.path.basename((name or "").strip().replace("\\", "/")).lstrip(".")
    safe = _OBJECT_KEY_NAME_RE.sub("_", base)[:200]
    return safe or default


_client_lock = threading.Lock()
_client: Optional[Any] = None
_bucket: Optional[str] = None


def _build_client() -> tuple[Any, str]:
    """Build (and cache) a boto3 S3 client from env. Thread-safe.

    Required env: ``S3_ENDPOINT_URL``, ``S3_REGION``, ``S3_ACCESS_KEY_ID``,
    ``S3_SECRET_ACCESS_KEY``, ``S3_BUCKET_ARTIFACTS``. Optional:
    ``S3_FORCE_PATH_STYLE`` (default true for MinIO compatibility).
    """
    global _client, _bucket
    with _client_lock:
        if _client is not None and _bucket is not None:
            return _client, _bucket

        endpoint = os.environ.get("S3_ENDPOINT_URL")
        region = os.environ.get("S3_REGION", "us-east-1")
        access_key = os.environ.get("S3_ACCESS_KEY_ID")
        secret_key = os.environ.get("S3_SECRET_ACCESS_KEY")
        bucket = os.environ.get("S3_BUCKET_ARTIFACTS")
        force_path_style = (os.environ.get("S3_FORCE_PATH_STYLE", "true") or "true").strip().lower() in {"1", "true", "yes"}

        if not endpoint or not access_key or not secret_key or not bucket:
            raise RuntimeError(
                "Object storage env is incomplete: need S3_ENDPOINT_URL, "
                "S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_BUCKET_ARTIFACTS."
            )

        addressing_style = "path" if force_path_style else "auto"
        config = Config(
            signature_version="s3v4",
            s3={"addressing_style": addressing_style},
            retries={"max_attempts": 3, "mode": "standard"},
        )
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=config,
        )
        _client = client
        _bucket = bucket
        return client, bucket


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def build_object_key(run_id: str, job_id: str, filename: str) -> str:
    """Stable per-run prefix; method-supplied filename is sanitized.

    The scoped MinIO policy allows PutObject anywhere in the artifact bucket,
    but in practice all method uploads land under ``artifacts/<run_id>/<job_id>/``
    so the worker can scope cleanup / debugging by run.
    """
    safe = _sanitize_filename(filename)
    return f"artifacts/{run_id}/{job_id}/{safe}"


def upload_artifact(
    local_path: Path,
    *,
    run_id: str,
    job_id: str,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Upload one local file to the artifact bucket. Returns a descriptor.

    Returns a dict with ``object_key``, ``size_bytes``, ``checksum_sha256`` — to
    be placed into ``result["artifact_files"][i]`` alongside the method's
    classification fields (filename, kind, role, content_type, previewable,
    tree_index).

    Raises if the upload fails — callers handle/log the error.
    """
    p = Path(local_path)
    if not p.is_file():
        raise FileNotFoundError(f"upload_artifact: not a file: {p}")

    client, bucket = _build_client()
    fname = filename or p.name
    object_key = build_object_key(run_id, job_id, fname)
    size_bytes = p.stat().st_size
    checksum = _sha256_of(p)

    extra_args: Dict[str, Any] = {}
    if content_type:
        extra_args["ContentType"] = content_type

    client.upload_file(str(p), bucket, object_key, ExtraArgs=extra_args or None)

    return {
        "object_key": object_key,
        "size_bytes": size_bytes,
        "checksum_sha256": checksum,
    }
