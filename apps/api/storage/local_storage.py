from __future__ import annotations

import os
import inspect
import shutil
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Optional
from urllib.parse import urljoin

import aiofiles

from apps.api.storage.base import ObjectStat, StorageInterface


class LocalStorage(StorageInterface):
    """Local file system storage for development."""

    def __init__(self, base_path: str = "runtime/storage", base_url: str = "/storage"):
        """
        Initialize local storage.

        Args:
            base_path: Base directory for storing files (can be absolute)
            base_url: Base URL for serving files
        """
        self.base_path = Path(base_path).resolve()
        self.base_url = base_url
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve_key(self, file_path: str) -> tuple[str, Path]:
        key = file_path.lstrip("/")
        full_path = (self.base_path / key).resolve()
        if not full_path.is_relative_to(self.base_path) or full_path == self.base_path:
            raise ValueError("Storage key must stay within the storage directory")
        return key, full_path

    async def upload(
        self,
        file_content: bytes | BinaryIO,
        file_path: str,
        content_type: Optional[str] = None,
    ) -> str:
        """Upload file to local storage."""
        # Ensure file_path is relative and safe
        safe_path, full_path = self._resolve_key(file_path)
        
        # Create parent directories
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file
        if isinstance(file_content, bytes):
            async with aiofiles.open(full_path, "wb") as f:
                await f.write(file_content)
        else:
            async with aiofiles.open(full_path, "wb") as f:
                while True:
                    chunk = file_content.read(1024 * 1024)
                    if inspect.isawaitable(chunk):
                        chunk = await chunk
                    if not chunk:
                        break
                    await f.write(chunk)
                file_content.seek(0)  # Reset for potential reuse
        
        return safe_path

    async def upload_file(
        self,
        local_path: str,
        file_path: str,
        content_type: Optional[str] = None,
    ) -> str:
        """Copy a file from disk into local storage (test/dev backend)."""
        safe_path, full_path = self._resolve_key(file_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, full_path)
        return safe_path

    async def download(self, file_path: str) -> bytes:
        """Download file from local storage."""
        safe_path, full_path = self._resolve_key(file_path)

        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        async with aiofiles.open(full_path, "rb") as f:
            return await f.read()

    async def stream_download(
        self,
        file_path: str,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncIterator[bytes]:
        """Stream a local file in chunks."""
        safe_path, full_path = self._resolve_key(file_path)

        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        async with aiofiles.open(full_path, "rb") as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    async def delete(self, file_path: str) -> bool:
        """Delete file from local storage."""
        safe_path, full_path = self._resolve_key(file_path)
        
        try:
            if full_path.exists():
                full_path.unlink()
                return True
            return False
        except Exception:
            return False

    async def get_url(
        self,
        file_path: str,
        expires_in: Optional[int] = None,
    ) -> str:
        """Get URL for local file."""
        safe_path, _ = self._resolve_key(file_path)
        return urljoin(self.base_url.rstrip("/") + "/", safe_path)

    async def exists(self, file_path: str) -> bool:
        """Check if file exists."""
        safe_path, full_path = self._resolve_key(file_path)
        return full_path.exists()

    async def stat(self, file_path: str) -> Optional[ObjectStat]:
        """Size of a stored file; None when it is absent. No checksum is recorded."""
        _, full_path = self._resolve_key(file_path)
        if not full_path.is_file():
            return None
        return ObjectStat(size_bytes=full_path.stat().st_size)

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every file whose key starts with ``prefix``."""
        key = prefix.lstrip("/")
        if not key:
            raise ValueError("refusing to delete with an empty prefix")
        self._resolve_key(key.rstrip("/") or key)          # must stay inside the storage directory
        deleted = 0
        for path in sorted(self.base_path.rglob("*")):
            if path.is_file() and path.relative_to(self.base_path).as_posix().startswith(key):
                path.unlink()
                deleted += 1
        return deleted

    async def move(self, src_path: str, dst_path: str) -> str:
        """Rename a file within local storage (atomic on same filesystem)."""
        _, src = self._resolve_key(src_path)
        dst_key, dst = self._resolve_key(dst_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        return dst_key

    def get_storage_type(self) -> str:
        """Get storage type."""
        return "local"
