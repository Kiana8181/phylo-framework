from __future__ import annotations

import os
from pathlib import Path

from apps.api.storage.base import StorageInterface
from apps.api.storage.local_storage import LocalStorage
from apps.api.storage.minio_storage import MinIOStorage
from apps.api.storage.s3_storage import S3Storage

# Repo root: apps/api/storage/__init__.py -> parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]


def get_storage() -> StorageInterface:
    """
    Get storage instance based on environment configuration.
    
    Returns:
        StorageInterface instance
    """
    storage_type = os.getenv("STORAGE_TYPE", "local").lower()
    
    if storage_type == "s3":
        return S3Storage(
            bucket_name=os.getenv("AWS_S3_BUCKET", ""),
            region=os.getenv("AWS_S3_REGION", "us-east-1"),
            access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )
    elif storage_type == "minio":
        return MinIOStorage(
            endpoint=os.getenv("MINIO_ENDPOINT", "localhost:9000"),
            access_key=os.getenv("MINIO_ACCESS_KEY", ""),
            secret_key=os.getenv("MINIO_SECRET_KEY", ""),
            bucket_name=os.getenv("MINIO_BUCKET", "phylo-files"),
            secure=os.getenv("MINIO_SECURE", "true").lower() == "true",
        )
    else:
        # Local storage: resolve path against repo root so API and method containers see the same files
        raw_path = os.getenv("STORAGE_LOCAL_PATH", "runtime/storage")
        base_path = (Path(raw_path) if Path(raw_path).is_absolute() else _REPO_ROOT / raw_path).resolve()
        return LocalStorage(
            base_path=str(base_path),
            base_url=os.getenv("STORAGE_LOCAL_URL", "/storage"),
        )


__all__ = [
    "StorageInterface",
    "LocalStorage",
    "S3Storage",
    "MinIOStorage",
    "get_storage",
]
