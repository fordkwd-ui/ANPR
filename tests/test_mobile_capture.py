"""Test mobile camera and direct photo capture endpoint."""
import io
import pytest
from httpx import AsyncClient
from PIL import Image

from app.models.gate import Gate, Device
from app.models.user import User, UserRole
from app.core.security import hash_password, create_access_token


@pytest.mark.asyncio
async def test_mobile_photo_capture_success(async_client: AsyncClient, db_session):
    """Verifies that a photo captured from a mobile device is processed, saved, and creates a detection."""
    # Create test JPEG
    img = Image.new("RGB", (640, 480), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    jpeg_bytes = buf.getvalue()

    # User token
    user = User(
        username="officer_mobile",
        password_hash=hash_password("OfficerPass123!"),
        role=UserRole.REVIEWER,
        active=True,
    )
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(subject=user.username, role=user.role.value, user_id=user.id)

    # Upload photo via multipart
    response = await async_client.post(
        "/api/v1/events/capture",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "plate": "KA 05 MN 4821",
            "vehicle_type": "truck",
            "vehicle_color": "yellow",
            "load_type": "timber_logs",
        },
        files={
            "photo": ("mobile_shot.jpg", jpeg_bytes, "image/jpeg"),
        },
    )

    assert response.status_code == 201, f"Failed: {response.text}"
    data = response.json()
    assert data["plate"] == "KA05MN4821"
    assert data["vehicle_type"] == "truck"
    assert data["vehicle_color"] == "yellow"
    assert data["load_type"] == "timber_logs"
    assert data["media_ready"] is True
    assert "plate" in data["thumbnails"]
    assert "scene" in data["thumbnails"]
    assert "load_thumb" in data["thumbnails"]


@pytest.mark.asyncio
async def test_mobile_photo_capture_without_plate(async_client: AsyncClient, db_session):
    """Verifies that photo capture without plate still creates a clean pass without error."""
    img = Image.new("RGB", (400, 300), color=(80, 80, 80))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    jpeg_bytes = buf.getvalue()

    response = await async_client.post(
        "/api/v1/events/capture",
        headers={"X-API-Key": "gatebox-secret-key-2026"},
        data={},
        files={
            "photo": ("cam_shot.jpg", jpeg_bytes, "image/jpeg"),
        },
    )

    assert response.status_code == 201, f"Failed: {response.text}"
    data = response.json()
    assert data["plate_raw"].startswith("PASS-")
    assert data["day_serial"] >= 1
    assert data["media_ready"] is True
