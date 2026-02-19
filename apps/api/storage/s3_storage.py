from __future__ import annotations

import os
from typing import BinaryIO, Optional

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

from apps.api.storage.base import StorageInterface


class S3Storage(StorageInterface):
    """AWS S3 storage implementation."""

    def __init__(
        self,
        bucket_name: str,
        region: str = "us-east-1",
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
    ):
        """
        Initialize S3 storage.
        
        Args:
            bucket_name: S3 bucket name
            region: AWS region
            access_key_id: AWS access key (or use IAM role)
            secret_access_key: AWS secret key (or use IAM role)
        """
        self.bucket_name = bucket_name
        self.region = region
        
        # Initialize S3 client
        config = Config(
            signature_version='s3v4',
            region_name=region,
        )
        
        if access_key_id and secret_access_key:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                config=config,
            )
        else:
            # Use IAM role or default credentials
            self.s3_client = boto3.client('s3', config=config)

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

    def get_storage_type(self) -> str:
        """Get storage type."""
        return "s3"
