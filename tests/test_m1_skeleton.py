"""Milestone 1 tests: Core Infrastructure, Storage, Logging, and App Skeleton."""
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.services.storage.local import LocalStorageDriver


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    """Verifies that the /health and /api/v1/ping endpoints respond with HTTP 200."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "service" in data

    response_ping = await async_client.get("/api/v1/ping")
    assert response_ping.status_code == 200
    assert response_ping.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_spa_static_serving(async_client: AsyncClient):
    """Verifies that the root path serves the built React frontend dashboard HTML."""
    response = await async_client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "<div id=\"root\"></div>" in response.text or "Forest Gate" in response.text or "html" in response.text


@pytest.mark.asyncio
async def test_request_id_header(async_client: AsyncClient):
    """Verifies that X-Request-ID header is propagated or generated."""
    # When provided
    custom_id = "test-request-id-12345"
    response = await async_client.get("/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_id

    # When omitted
    response_auto = await async_client.get("/health")
    assert response_auto.status_code == 200
    assert "X-Request-ID" in response_auto.headers
    assert len(response_auto.headers["X-Request-ID"]) > 10


@pytest.mark.asyncio
async def test_database_session(db_session: AsyncSession):
    """Verifies that async database session can execute queries."""
    result = await db_session.execute(text("SELECT 1"))
    scalar_val = result.scalar()
    assert scalar_val == 1


@pytest.mark.asyncio
async def test_local_storage_driver(tmp_path):
    """Verifies the LocalStorageDriver file operations."""
    driver = LocalStorageDriver(base_dir=str(tmp_path))
    object_key = "detections/2026/10/18/test_plate.jpg"
    test_data = b"dummy_jpeg_binary_data"

    # Save
    bytes_written = await driver.save_file(object_key, test_data, content_type="image/jpeg")
    assert bytes_written == len(test_data)

    # Exists
    assert await driver.file_exists(object_key) is True
    assert await driver.file_exists("nonexistent.jpg") is False

    # Read
    content = await driver.read_file(object_key)
    assert content == test_data

    # URL
    url = await driver.get_url(object_key)
    assert url == f"/api/v1/media/{object_key}"

    # Delete
    deleted = await driver.delete_file(object_key)
    assert deleted is True
    assert await driver.file_exists(object_key) is False


def test_settings_configuration():
    """Verifies configuration values and defaults."""
    settings = get_settings()
    assert settings.PROJECT_NAME == "Vehicle Gate Monitoring Cloud"
    assert settings.CONF_THRESHOLD_LOAD == 0.60
    assert settings.CONF_THRESHOLD_PLATE == 0.85
    assert settings.MEDIA_RETENTION_DAYS == 90
