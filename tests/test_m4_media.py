"""Milestone 4 tests: Media Upload, Out-of-Order Safety, Late Load Update, and Retention Purge."""
import io
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import hash_api_key
from app.models.detection import Detection, Media, MediaKind
from app.models.gate import Device, Gate
from app.services.retention_service import RetentionService
from app.services.storage import get_storage


@pytest.fixture
def raw_api_key():
    return "media-test-api-key-2026"


@pytest.fixture
async def setup_gate_and_device(db_session: AsyncSession, raw_api_key: str):
    gate = Gate(name="South Forest Gate", timezone="Asia/Kolkata")
    db_session.add(gate)
    await db_session.flush()

    device = Device(
        gate_id=gate.id,
        name="Media Edge Unit",
        api_key_hash=hash_api_key(raw_api_key),
    )
    db_session.add(device)
    await db_session.commit()
    await db_session.refresh(gate)
    await db_session.refresh(device)
    return gate, device


@pytest.mark.asyncio
async def test_media_upload_after_event(
    async_client: AsyncClient,
    setup_gate_and_device,
    raw_api_key: str,
    db_session: AsyncSession,
):
    """Verifies normal sequence: Stage 1 event followed by Stage 2 media upload."""
    _, _ = setup_gate_and_device
    headers = {"X-API-Key": raw_api_key}

    # 1. Post Stage 1 Event
    event_payload = {
        "event_uid": f"evt-norm-{uuid.uuid4()}",
        "camera_id": "cam-01",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "plate_raw": "KA 01 AB 1234",
        "plate_conf": 0.95,
        "vehicle_type": "truck",
        "load_type": "timber_logs",
        "load_conf": 0.85,
    }
    resp1 = await async_client.post("/api/v1/events", json=event_payload, headers=headers)
    assert resp1.status_code == 200
    detection_id = resp1.json()["id"]
    assert resp1.json()["media_ready"] is False

    # 2. Upload Media (Stage 2)
    files = {
        "plate": ("plate.jpg", io.BytesIO(b"plate_binary_bytes"), "image/jpeg"),
        "scene": ("scene.jpg", io.BytesIO(b"scene_binary_bytes"), "image/jpeg"),
    }
    resp2 = await async_client.put(
        f"/api/v1/detections/{detection_id}/media",
        files=files,
        headers=headers,
    )
    assert resp2.status_code == 200
    media_data = resp2.json()
    assert media_data["media_ready"] is True
    assert "plate" in media_data["saved_media"]
    assert "scene" in media_data["saved_media"]

    # Verify database state
    det = await db_session.get(Detection, uuid.UUID(detection_id))
    assert det.media_ready is True
    media_items = (await db_session.execute(select(Media).where(Media.detection_id == det.id))).scalars().all()
    assert len(media_items) == 2


@pytest.mark.asyncio
async def test_out_of_order_media_before_event(
    async_client: AsyncClient,
    setup_gate_and_device,
    raw_api_key: str,
    db_session: AsyncSession,
):
    """TEST 4: Media upload before and after the event; out-of-order safe."""
    _, _ = setup_gate_and_device
    headers = {"X-API-Key": raw_api_key}
    det_uuid = uuid.uuid4()

    # Step 1: Media arrives FIRST with det_uuid before Stage 1 event
    files = {
        "load_thumb": ("thumb.jpg", io.BytesIO(b"load_thumbnail_bytes"), "image/jpeg"),
        "load_full": ("full.jpg", io.BytesIO(b"load_full_bytes"), "image/jpeg"),
    }
    resp_media = await async_client.put(
        f"/api/v1/detections/{det_uuid}/media",
        files=files,
        headers=headers,
    )
    assert resp_media.status_code == 200
    assert resp_media.json()["media_ready"] is True

    # Step 2: Stage 1 Event arrives LATER with the same ID
    event_payload = {
        "id": str(det_uuid),
        "event_uid": f"evt-late-{det_uuid}",
        "camera_id": "cam-02",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "plate_raw": "MH 12 CD 5678",
        "plate_conf": 0.92,
        "vehicle_type": "truck",
        "load_type": "stone_gravel",
        "load_conf": 0.89,
    }
    resp_event = await async_client.post("/api/v1/events", json=event_payload, headers=headers)
    assert resp_event.status_code == 200
    completed_event = resp_event.json()

    assert completed_event["id"] == str(det_uuid)
    assert completed_event["plate"] == "MH12CD5678"
    assert completed_event["plate_valid"] is True
    assert completed_event["media_ready"] is True
    assert completed_event["day_serial"] >= 1
    assert completed_event["status"] == "verified"

    # Verify media objects are still attached in DB
    media_items = (await db_session.execute(select(Media).where(Media.detection_id == det_uuid))).scalars().all()
    assert len(media_items) == 2


@pytest.mark.asyncio
async def test_late_load_classifier_update(
    async_client: AsyncClient,
    setup_gate_and_device,
    raw_api_key: str,
):
    """Verifies PATCH /detections/{id}/load updates load classification and status."""
    _, _ = setup_gate_and_device
    headers = {"X-API-Key": raw_api_key}

    # Create event with low load_conf -> starts as needs_review
    event_payload = {
        "event_uid": f"evt-late-load-{uuid.uuid4()}",
        "camera_id": "cam-01",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "plate_raw": "DL 01 AA 1111",
        "plate_conf": 0.95,
        "vehicle_type": "truck",
        "load_type": "unknown",
        "load_conf": 0.20,
    }
    resp1 = await async_client.post("/api/v1/events", json=event_payload, headers=headers)
    assert resp1.status_code == 200
    det_id = resp1.json()["id"]
    assert resp1.json()["status"] == "needs_review"

    # Patch with high confidence load classification from Camera B
    patch_payload = {
        "load_type": "sand",
        "load_conf": 0.88,
    }
    resp_patch = await async_client.patch(
        f"/api/v1/detections/{det_id}/load",
        json=patch_payload,
        headers=headers,
    )
    assert resp_patch.status_code == 200
    patched_data = resp_patch.json()
    assert patched_data["load_type"] == "sand"
    assert patched_data["load_conf"] == 0.88
    # Status re-evaluated to verified!
    assert patched_data["status"] == "verified"


@pytest.mark.asyncio
async def test_retention_job_removes_only_old_media(
    db_session: AsyncSession,
    setup_gate_and_device,
):
    """TEST 8: Retention job removes only media older than MEDIA_RETENTION_DAYS, nulls keys, keeps records."""
    gate, _ = setup_gate_and_device
    storage = get_storage()
    now = datetime.now(timezone.utc)

    # 1. Create a detection
    detection = Detection(
        event_uid=f"evt-retention-{uuid.uuid4()}",
        gate_id=gate.id,
        camera_id="cam-01",
        captured_at=now - timedelta(days=100),
        received_at=now - timedelta(days=100),
        day_serial=1,
        plate_raw="KA01AA1234",
        plate="KA01AA1234",
        plate_valid=True,
        plate_conf=0.95,
        media_ready=True,
    )
    db_session.add(detection)
    await db_session.flush()

    # 2. Add an old media item (100 days old)
    old_key = f"detections/{detection.id}/old_plate.jpg"
    await storage.save_file(old_key, b"old_binary_content")
    old_media = Media(
        detection_id=detection.id,
        kind=MediaKind.PLATE,
        object_key=old_key,
        bytes=18,
        created_at=now - timedelta(days=100),
    )

    # 3. Add a recent media item (10 days old)
    recent_key = f"detections/{detection.id}/recent_scene.jpg"
    await storage.save_file(recent_key, b"recent_binary_content")
    recent_media = Media(
        detection_id=detection.id,
        kind=MediaKind.SCENE,
        object_key=recent_key,
        bytes=21,
        created_at=now - timedelta(days=10),
    )

    db_session.add_all([old_media, recent_media])
    await db_session.commit()

    assert await storage.file_exists(old_key) is True
    assert await storage.file_exists(recent_key) is True

    # 4. Run retention purge for 90 days
    purged_count = await RetentionService.purge_old_media(db_session, storage, retention_days=90)
    assert purged_count == 1

    # Verify old file removed from storage and object_key set to None
    assert await storage.file_exists(old_key) is False
    await db_session.refresh(old_media)
    assert old_media.object_key is None
    # Media row still exists!
    assert old_media.id is not None

    # Verify recent file is NOT removed and key remains intact
    assert await storage.file_exists(recent_key) is True
    await db_session.refresh(recent_media)
    assert recent_media.object_key == recent_key

    # Detection record still exists
    det_check = await db_session.get(Detection, detection.id)
    assert det_check is not None
