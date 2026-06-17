from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from apps.api.storage.base import StorageInterface
from apps.api.storage.local_storage import LocalStorage
from apps.api.storage.minio_storage import MinIOStorage
from apps.api.storage.s3_storage import S3Storage

# Repo root: apps/api/storage/__init__.py -> parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _env(*names: str, default: str | None = None) -> str | None:
    """Return the first non-empty environment variable among ``names``."""
    for name in names:
        val = os.getenv(name)
        if val is not None and val.strip() != "":
            return val.strip()
    return default


def _backend() -> str:
    """Resolve the configured storage backend.

    Prefers the unified ``STORAGE_BACKEND`` and falls back to the legacy
    ``STORAGE_TYPE``. Defaults to ``local`` so unit tests and bare checkouts
    do not require a running object store; the documented dev/prod default is
    MinIO via ``.env`` / docker-compose.
    """
    return (_env("STORAGE_BACKEND", "STORAGE_TYPE", default="local") or "local").lower()


def dataset_bucket() -> str:
    return _env("S3_BUCKET_DATASETS", "MINIO_BUCKET", "AWS_S3_BUCKET", default="phylo-datasets") or "phylo-datasets"


def artifact_bucket() -> str:
    return _env("S3_BUCKET_ARTIFACTS", default="phylo-artifacts") or "phylo-artifacts"


def _parse_minio_endpoint() -> tuple[str, bool]:
    """Return (host:port, secure) for the MinIO client from unified or legacy env."""
    url = _env("S3_ENDPOINT_URL")
    if url:
        parsed = urlparse(url if "://" in url else f"//{url}")
        host = parsed.netloc or parsed.path
        secure = parsed.scheme == "https"
        return host, secure
    endpoint = _env("MINIO_ENDPOINT", default="localhost:9000") or "localhost:9000"
    secure = (_env("MINIO_SECURE", default="false") or "false").lower() == "true"
    return endpoint, secure


def _make_storage(bucket: str | None) -> StorageInterface:
    backend = _backend()

    if backend == "minio":
        endpoint, secure = _parse_minio_endpoint()
        return MinIOStorage(
            endpoint=endpoint,
            access_key=_env("S3_ACCESS_KEY_ID", "MINIO_ACCESS_KEY", default="") or "",
            secret_key=_env("S3_SECRET_ACCESS_KEY", "MINIO_SECRET_KEY", default="") or "",
            bucket_name=bucket or dataset_bucket(),
            secure=secure,
        )

    if backend == "s3":
        return S3Storage(
            bucket_name=bucket or dataset_bucket(),
            region=_env("S3_REGION", "AWS_S3_REGION", default="us-east-1") or "us-east-1",
            access_key_id=_env("S3_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"),
            secret_access_key=_env("S3_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"),
            endpoint_url=_env("S3_ENDPOINT_URL"),
            force_path_style=(_env("S3_FORCE_PATH_STYLE", default="false") or "false").lower() == "true",
        )

    # Local filesystem backend (tests / simple isolated dev only).
    # Resolve path against repo root so API and method containers see the same files.
    raw_path = _env("STORAGE_LOCAL_PATH", default="runtime/storage") or "runtime/storage"
    base_path = (Path(raw_path) if Path(raw_path).is_absolute() else _REPO_ROOT / raw_path).resolve()
    return LocalStorage(
        base_path=str(base_path),
        base_url=_env("STORAGE_LOCAL_URL", default="/storage") or "/storage",
    )


def get_dataset_storage() -> StorageInterface:
    """Storage bound to the datasets bucket (uploaded input files)."""
    return _make_storage(dataset_bucket())


def get_artifact_storage() -> StorageInterface:
    """Storage bound to the artifacts bucket (generated run outputs)."""
    return _make_storage(artifact_bucket())


def get_storage() -> StorageInterface:
    """Backward-compatible accessor — returns the datasets-bucket storage."""
    return get_dataset_storage()


__all__ = [
    "StorageInterface",
    "LocalStorage",
    "S3Storage",
    "MinIOStorage",
    "get_storage",
    "get_dataset_storage",
    "get_artifact_storage",
    "dataset_bucket",
    "artifact_bucket",
]
