from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO, Optional
from urllib.parse import urljoin

import aiofiles

from apps.api.storage.base import StorageInterface


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

    async def upload(
        self,
        file_content: bytes | BinaryIO,
        file_path: str,
        content_type: Optional[str] = None,
    ) -> str:
        """Upload file to local storage."""
        # Ensure file_path is relative and safe
        safe_path = file_path.lstrip("/")
        full_path = self.base_path / safe_path
        
        # Create parent directories
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file
        if isinstance(file_content, bytes):
            async with aiofiles.open(full_path, "wb") as f:
                await f.write(file_content)
        else:
            async with aiofiles.open(full_path, "wb") as f:
                while True:
                    chunk = await file_content.read(1024 * 1024)  # 1MB chunks
                    if not chunk:
                        break
                    await f.write(chunk)
                file_content.seek(0)  # Reset for potential reuse
        
        return safe_path

    async def download(self, file_path: str) -> bytes:
        """Download file from local storage."""
        safe_path = file_path.lstrip("/")
        full_path = self.base_path / safe_path
        
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        async with aiofiles.open(full_path, "rb") as f:
            return await f.read()

    async def delete(self, file_path: str) -> bool:
        """Delete file from local storage."""
        safe_path = file_path.lstrip("/")
        full_path = self.base_path / safe_path
        
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
        safe_path = file_path.lstrip("/")
        return urljoin(self.base_url.rstrip("/") + "/", safe_path)

    async def exists(self, file_path: str) -> bool:
        """Check if file exists."""
        safe_path = file_path.lstrip("/")
        full_path = self.base_path / safe_path
        return full_path.exists()

    async def move(self, src_path: str, dst_path: str) -> str:
        """Rename a file within local storage (atomic on same filesystem)."""
        src = self.base_path / src_path.lstrip("/")
        dst = self.base_path / dst_path.lstrip("/")
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        return dst_path.lstrip("/")

    def get_storage_type(self) -> str:
        """Get storage type."""
        return "local"
