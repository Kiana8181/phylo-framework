from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator, BinaryIO, Optional

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

from apps.api.storage.base import ObjectStat, StorageInterface


class S3Storage(StorageInterface):
    """S3-compatible storage implementation (AWS S3 or any S3-compatible endpoint)."""

    def __init__(
        self,
        bucket_name: str,
        region: str = "us-east-1",
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        force_path_style: bool = False,
    ):
        """
        Initialize S3 storage.

        Args:
            bucket_name: S3 bucket name
            region: AWS region
            access_key_id: AWS access key (or use IAM role)
            secret_access_key: AWS secret key (or use IAM role)
            endpoint_url: Custom endpoint for S3-compatible stores (None for AWS)
            force_path_style: Use path-style addressing (required by most non-AWS stores)
        """
        self.bucket_name = bucket_name
        self.region = region
        self.endpoint_url = endpoint_url

        # Initialize S3 client
        config = Config(
            signature_version='s3v4',
            region_name=region,
            s3={'addressing_style': 'path'} if force_path_style else {},
        )

        client_kwargs = {"config": config}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if access_key_id and secret_access_key:
            client_kwargs["aws_access_key_id"] = access_key_id
            client_kwargs["aws_secret_access_key"] = secret_access_key

        self.s3_client = boto3.client('s3', **client_kwargs)

    async def upload(
        self,
        file_content: bytes | BinaryIO,
        file_path: str,
        content_type: Optional[str] = None,
    ) -> str:
        """Upload file to S3."""
        # Ensure file_path doesn't start with /
        key = file_path.lstrip("/")
        
        extra_args = {}
        if content_type:
            extra_args['ContentType'] = content_type
        
        try:
            if isinstance(file_content, bytes):
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=key,
                    Body=file_content,
                    **extra_args
                )
            else:
                self.s3_client.upload_fileobj(
                    file_content,
                    self.bucket_name,
                    key,
                    ExtraArgs=extra_args,
                )
            return key
        except ClientError as e:
            raise Exception(f"Failed to upload to S3: {e}")

    async def upload_file(
        self,
        local_path: str,
        file_path: str,
        content_type: Optional[str] = None,
    ) -> str:
        """Stream-upload a file from disk to S3 (no full read into memory)."""
        key = file_path.lstrip("/")
        extra_args = {"ContentType": content_type} if content_type else None
        try:
            await asyncio.to_thread(
                self.s3_client.upload_file,
                local_path,
                self.bucket_name,
                key,
                extra_args,
            )
            return key
        except ClientError as e:
            raise Exception(f"Failed to upload to S3: {e}")

    async def download(self, file_path: str) -> bytes:
        """Download file from S3."""
        key = file_path.lstrip("/")

        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            return response['Body'].read()
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                raise FileNotFoundError(f"File not found: {file_path}")
            raise Exception(f"Failed to download from S3: {e}")

    async def stream_download(
        self,
        file_path: str,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncIterator[bytes]:
        """Stream an S3 object in chunks without buffering the whole object."""
        key = file_path.lstrip("/")
        try:
            response = await asyncio.to_thread(
                self.s3_client.get_object, Bucket=self.bucket_name, Key=key
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                raise FileNotFoundError(f"File not found: {file_path}")
            raise Exception(f"Failed to download from S3: {e}")
        body = response["Body"]
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    async def delete(self, file_path: str) -> bool:
        """Delete file from S3."""
        key = file_path.lstrip("/")
        
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError:
            return False

    async def get_url(
        self,
        file_path: str,
        expires_in: Optional[int] = None,
    ) -> str:
        """Get presigned URL for S3 file."""
        key = file_path.lstrip("/")
        
        try:
            if expires_in:
                url = self.s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': self.bucket_name, 'Key': key},
                    ExpiresIn=expires_in,
                )
            else:
                # Public URL (if bucket is public)
                url = f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{key}"
            return url
        except ClientError as e:
            raise Exception(f"Failed to generate S3 URL: {e}")

    async def exists(self, file_path: str) -> bool:
        """Check if file exists in S3."""
        key = file_path.lstrip("/")
        
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError:
            return False

    async def stat(self, file_path: str) -> Optional[ObjectStat]:
        """Size and recorded checksum of an object; None only when it is absent."""
        key = file_path.lstrip("/")
        try:
            head = await asyncio.to_thread(
                self.s3_client.head_object, Bucket=self.bucket_name, Key=key
            )
        except ClientError as e:
            status = (e.response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
            code = str((e.response.get("Error") or {}).get("Code") or "")
            if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        metadata = {str(k).lower(): v for k, v in (head.get("Metadata") or {}).items()}
        sha256 = metadata.get("sha256")
        return ObjectStat(
            size_bytes=int(head.get("ContentLength") or 0),
            sha256=str(sha256).strip().lower() if sha256 else None,
        )

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every object under ``prefix``. Raises if the store fails."""
        key = prefix.lstrip("/")
        if not key:
            raise ValueError("refusing to delete with an empty prefix")

        def _delete_all() -> int:
            deleted = 0
            paginator = self.s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=key):
                for obj in page.get("Contents") or []:
                    self.s3_client.delete_object(Bucket=self.bucket_name, Key=obj["Key"])
                    deleted += 1
            return deleted

        return await asyncio.to_thread(_delete_all)

    async def move(self, src_path: str, dst_path: str) -> str:
        """Move within S3 via copy + delete."""
        src_key = src_path.lstrip("/")
        dst_key = dst_path.lstrip("/")
        try:
            self.s3_client.copy_object(
                Bucket=self.bucket_name,
                CopySource={"Bucket": self.bucket_name, "Key": src_key},
                Key=dst_key,
            )
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=src_key)
            return dst_key
        except ClientError as e:
            raise Exception(f"Failed to move object in S3: {e}")

    def get_storage_type(self) -> str:
        """Get storage type."""
        return "s3"

    @property
    def bucket(self) -> Optional[str]:
        return self.bucket_name
