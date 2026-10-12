from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, BinaryIO, Optional
from uuid import UUID


@dataclass(frozen=True)
class ObjectStat:
    """What the store itself reports about one stored object."""

    size_bytes: int
    # SHA-256 the uploader recorded on the object (user metadata "sha256"),
    # or None when the object carries none.
    sha256: Optional[str] = None


class StorageInterface(ABC):
    """Abstract base class for storage providers."""

    @abstractmethod
    async def upload(
        self,
        file_content: bytes | BinaryIO,
        file_path: str,
        content_type: Optional[str] = None,
    ) -> str:
        """
        Upload a file to storage.
        
        Args:
            file_content: File content as bytes or file-like object
            file_path: Destination path/key in storage
            content_type: MIME type of the file
            
        Returns:
            Storage path/key of uploaded file
        """
        pass

    @abstractmethod
    async def download(self, file_path: str) -> bytes:
        """
        Download a file from storage.
        
        Args:
            file_path: Storage path/key
            
        Returns:
            File content as bytes
        """
        pass

    @abstractmethod
    async def delete(self, file_path: str) -> bool:
        """
        Delete a file from storage.
        
        Args:
            file_path: Storage path/key
            
        Returns:
            True if deleted successfully
        """
        pass

    @abstractmethod
    async def get_url(
        self,
        file_path: str,
        expires_in: Optional[int] = None,
    ) -> str:
        """
        Get a URL to access the file.
        
        Args:
            file_path: Storage path/key
            expires_in: URL expiration time in seconds (None for permanent URLs)
            
        Returns:
            URL to access the file
        """
        pass

    @abstractmethod
    async def exists(self, file_path: str) -> bool:
        """
        Check if a file exists in storage.
        
        Args:
            file_path: Storage path/key
            
        Returns:
            True if file exists
        """
        pass

    async def stat(self, file_path: str) -> Optional[ObjectStat]:
        """Size (and recorded checksum) of a stored object, or None if absent.

        Unlike ``exists``, this must not hide a store failure: an unreachable or
        refusing store raises, so the caller can tell "missing" from "unknown".
        """
        raise NotImplementedError

    @abstractmethod
    async def move(self, src_path: str, dst_path: str) -> str:
        """
        Move/rename an object within storage.

        For object stores (S3/MinIO) this may be implemented as copy + delete.

        Args:
            src_path: Source storage path/key
            dst_path: Destination storage path/key

        Returns:
            The destination storage path/key
        """
        pass

    @abstractmethod
    def get_storage_type(self) -> str:
        """Get the storage type identifier (e.g., 'local', 's3', 'minio')."""
        pass

    @property
    def bucket(self) -> Optional[str]:
        """Bucket/container name for object stores, or None for local filesystem."""
        return None

    async def stream_download(
        self,
        file_path: str,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncIterator[bytes]:
        """
        Stream a file from storage in chunks without loading it fully into memory.

        The default implementation falls back to ``download`` (full read) and
        re-chunks; object-store backends override this with true streaming.

        Raises:
            FileNotFoundError: if the object does not exist.
        """
        data = await self.download(file_path)
        for offset in range(0, len(data), chunk_size):
            yield data[offset:offset + chunk_size]

    async def upload_file(
        self,
        local_path: str,
        file_path: str,
        content_type: Optional[str] = None,
    ) -> str:
        """
        Upload a file from a local filesystem path to storage.

        The default implementation reads the file into memory and calls
        ``upload``; backends that support streaming uploads override this.

        Returns:
            Storage path/key of the uploaded file.
        """
        with open(local_path, "rb") as f:
            data = f.read()
        return await self.upload(data, file_path, content_type=content_type)
