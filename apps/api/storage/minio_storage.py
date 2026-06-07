from __future__ import annotations

from typing import BinaryIO, Optional
from urllib.parse import urljoin

from minio import Minio
from minio.error import S3Error

from apps.api.storage.base import StorageInterface


class MinIOStorage(StorageInterface):
    """MinIO storage implementation."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        secure: bool = True,
    ):
        """
        Initialize MinIO storage.
        
        Args:
            endpoint: MinIO server endpoint (e.g., 'localhost:9000')
            access_key: MinIO access key
            secret_key: MinIO secret key
            bucket_name: Bucket name
            secure: Use HTTPS (True) or HTTP (False)
        """
        self.bucket_name = bucket_name
        self.endpoint = endpoint
        self.secure = secure
        
        # Initialize MinIO client
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        
        # Ensure bucket exists
        self._ensure_bucket()

    def _ensure_bucket(self):
        """Ensure bucket exists, create if not."""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
        except S3Error as e:
            raise Exception(f"Failed to ensure bucket exists: {e}")

    async def upload(
        self,
        file_content: bytes | BinaryIO,
        file_path: str,
        content_type: Optional[str] = None,
    ) -> str:
        """Upload file to MinIO."""
        key = file_path.lstrip("/")
        
        try:
            if isinstance(file_content, bytes):
                from io import BytesIO
                file_obj = BytesIO(file_content)
                length = len(file_content)
            else:
                file_obj = file_content
                # Get file size
                file_obj.seek(0, 2)  # Seek to end
                length = file_obj.tell()
                file_obj.seek(0)  # Reset to beginning
            
            self.client.put_object(
                self.bucket_name,
                key,
                file_obj,
                length=length,
                content_type=content_type or "application/octet-stream",
            )
            return key
        except S3Error as e:
            raise Exception(f"Failed to upload to MinIO: {e}")

    async def download(self, file_path: str) -> bytes:
        """Download file from MinIO."""
        key = file_path.lstrip("/")
        
        try:
            response = self.client.get_object(self.bucket_name, key)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            if e.code == 'NoSuchKey':
                raise FileNotFoundError(f"File not found: {file_path}")
            raise Exception(f"Failed to download from MinIO: {e}")

    async def delete(self, file_path: str) -> bool:
        """Delete file from MinIO."""
        key = file_path.lstrip("/")
        
        try:
            self.client.remove_object(self.bucket_name, key)
            return True
        except S3Error:
            return False

    async def get_url(
        self,
        file_path: str,
        expires_in: Optional[int] = None,
    ) -> str:
        """Get presigned URL for MinIO file."""
        key = file_path.lstrip("/")
        
        try:
            if expires_in:
                url = self.client.presigned_get_object(
                    self.bucket_name,
                    key,
                    expires_in=expires_in,
                )
            else:
                # Public URL (if bucket policy allows)
                protocol = "https" if self.secure else "http"
                url = f"{protocol}://{self.endpoint}/{self.bucket_name}/{key}"
            return url
        except S3Error as e:
            raise Exception(f"Failed to generate MinIO URL: {e}")

    async def exists(self, file_path: str) -> bool:
        """Check if file exists in MinIO."""
        key = file_path.lstrip("/")
        
        try:
            self.client.stat_object(self.bucket_name, key)
            return True
        except S3Error:
            return False

    async def move(self, src_path: str, dst_path: str) -> str:
        """Move within MinIO via server-side copy + remove."""
        from minio.commonconfig import CopySource

        src_key = src_path.lstrip("/")
        dst_key = dst_path.lstrip("/")
        try:
            self.client.copy_object(
                self.bucket_name,
                dst_key,
                CopySource(self.bucket_name, src_key),
            )
            self.client.remove_object(self.bucket_name, src_key)
            return dst_key
        except S3Error as e:
            raise Exception(f"Failed to move object in MinIO: {e}")

    def get_storage_type(self) -> str:
        """Get storage type."""
        return "minio"
