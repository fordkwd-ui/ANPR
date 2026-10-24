"""Abstract storage driver interface."""
from abc import ABC, abstractmethod


class StorageDriver(ABC):
    """Abstract interface for media object storage (S3 and Local)."""

    @abstractmethod
    async def save_file(self, object_key: str, data: bytes, content_type: str = "image/jpeg") -> int:
        """Stores object bytes under object_key. Returns number of bytes saved."""
        pass

    @abstractmethod
    async def get_url(self, object_key: str, expire_seconds: int = 600) -> str:
        """Generates a temporary signed or direct access URL."""
        pass

    @abstractmethod
    async def read_file(self, object_key: str) -> bytes:
        """Reads object bytes directly."""
        pass

    @abstractmethod
    async def delete_file(self, object_key: str) -> bool:
        """Deletes object under object_key. Returns True if deleted."""
        pass

    @abstractmethod
    async def file_exists(self, object_key: str) -> bool:
        """Checks if object exists."""
        pass
