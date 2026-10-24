"""S3-compatible (AWS / MinIO) object storage driver."""
import asyncio
from typing import Optional
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from app.services.storage.base import StorageDriver


class S3StorageDriver(StorageDriver):
    """Storage driver for MinIO, AWS S3, or Cloudflare R2."""

    def __init__(
        self,
        endpoint_url: Optional[str] = "http://localhost:9000",
        access_key: Optional[str] = "minioadmin",
        secret_key: Optional[str] = "minioadmin",
        bucket_name: str = "anpr-media",
        region: str = "auto",
        public_url: Optional[str] = None,
    ):
        self.bucket_name = bucket_name
        self.public_url = public_url.rstrip("/") if public_url else None
        clean_endpoint = endpoint_url.rstrip("/") if endpoint_url else None
        self.client = boto3.client(
            "s3",
            endpoint_url=clean_endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region or "auto",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """Attempts to verify or create bucket, ignoring permission limits on read-only tokens."""
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
        except Exception:
            try:
                self.client.create_bucket(Bucket=self.bucket_name)
            except Exception:
                pass

    async def save_file(self, object_key: str, data: bytes, content_type: str = "image/jpeg") -> int:
        def _upload() -> int:
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=object_key,
                Body=data,
                ContentType=content_type,
            )
            return len(data)

        return await asyncio.to_thread(_upload)

    async def get_url(self, object_key: str, expire_seconds: int = 3600) -> str:
        # If a public CDN / Cloudflare R2 public URL is configured, use it directly
        if self.public_url:
            clean_key = object_key.lstrip("/")
            return f"{self.public_url}/{clean_key}"

        def _presign() -> str:
            return self.client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self.bucket_name, "Key": object_key},
                ExpiresIn=expire_seconds,
            )

        return await asyncio.to_thread(_presign)

    async def read_file(self, object_key: str) -> bytes:
        def _read() -> bytes:
            response = self.client.get_object(Bucket=self.bucket_name, Key=object_key)
            return response["Body"].read()

        return await asyncio.to_thread(_read)

    async def delete_file(self, object_key: str) -> bool:
        def _delete() -> bool:
            try:
                self.client.delete_object(Bucket=self.bucket_name, Key=object_key)
                return True
            except ClientError:
                return False

        return await asyncio.to_thread(_delete)

    async def file_exists(self, object_key: str) -> bool:
        def _exists() -> bool:
            try:
                self.client.head_object(Bucket=self.bucket_name, Key=object_key)
                return True
            except ClientError:
                return False

        return await asyncio.to_thread(_exists)
