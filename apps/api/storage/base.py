from __future__ import annotations

from abc import ABC, abstractmethod
from typing import BinaryIO, Optional
from uuid import UUID


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
