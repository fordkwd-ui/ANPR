"""Storage service factory."""
from functools import lru_cache
from app.config import get_settings
from app.services.storage.base import StorageDriver
from app.services.storage.local import LocalStorageDriver
from app.services.storage.s3 import S3StorageDriver


@lru_cache()
def get_storage() -> StorageDriver:
    """Returns configured storage driver (S3 or Local)."""
    settings = get_settings()
    if settings.STORAGE_DRIVER == "s3":
        return S3StorageDriver(
            endpoint_url=settings.S3_ENDPOINT_URL,
            access_key=settings.S3_ACCESS_KEY,
            secret_key=settings.S3_SECRET_KEY,
            bucket_name=settings.S3_BUCKET_NAME,
            region=settings.S3_REGION,
            public_url=settings.S3_PUBLIC_URL,
        )
    return LocalStorageDriver(base_dir=settings.STORAGE_LOCAL_DIR)
