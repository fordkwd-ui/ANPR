"""Local filesystem storage driver implementation."""
import os
from pathlib import Path
from app.services.storage.base import StorageDriver


class LocalStorageDriver(StorageDriver):
    """Stores files on the local filesystem. Ideal for unit tests and local runs."""

    def __init__(self, base_dir: str = "./media_storage"):
        self.base_path = Path(base_dir).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, object_key: str) -> Path:
        safe_key = object_key.lstrip("/")
        return self.base_path / safe_key

    async def save_file(self, object_key: str, data: bytes, content_type: str = "image/jpeg") -> int:
        file_path = self._resolve_path(object_key)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(data)
        return len(data)

    async def get_url(self, object_key: str, expire_seconds: int = 600) -> str:
        # In local mode, return an endpoint URL or relative URL for preview
        return f"/api/v1/media/{object_key.lstrip('/')}"

    async def read_file(self, object_key: str) -> bytes:
        file_path = self._resolve_path(object_key)
        if not file_path.is_file():
            raise FileNotFoundError(f"Object {object_key} not found")
        return file_path.read_bytes()

    async def delete_file(self, object_key: str) -> bool:
        file_path = self._resolve_path(object_key)
        if file_path.is_file():
            file_path.unlink()
            return True
        return False

    async def file_exists(self, object_key: str) -> bool:
        file_path = self._resolve_path(object_key)
        return file_path.is_file()
