"""Milestone 3 tests: Ingestion, Idempotency, 200 Concurrency Day Serial, Deduplication, and Plate Rules."""
import asyncio
from datetime import datetime, timedelta, timezone
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.plate import normalize_plate, validate_plate
from app.core.security import hash_api_key
from app.core.serial import allocate_day_serial
from app.models.counter import DailyCounter
from app.models.detection import Detection, DetectionStatus
from app.models.gate import Device, Gate


@pytest.fixture
def raw_api_key():
    return "forest-gate-edge-api-key-2026"


@pytest.fixture
async def setup_gate_and_device(db_session: AsyncSession, raw_api_key: str):
    gate = Gate(name="Pine Ridge Forest Gate", timezone="Asia/Kolkata")
    db_session.add(gate)
    await db_session.flush()

    device = Device(
        gate_id=gate.id,
        name="Edge Mini PC Cam A/B",
        api_key_hash=hash_api_key(raw_api_key),
    )
    db_session.add(device)
    await db_session.commit()
    await db_session.refresh(gate)
    await db_session.refresh(device)
    return gate, device


def test_plate_normalization_and_validation():
    """Verifies plate normalization and Indian / BH-series regex validation."""
    # Standard Indian plates
    assert normalize_plate("dl 01 ab 1234") == "DL01AB1234"
    assert validate_plate("DL01AB1234") is True

    assert normalize_plate("KA-05-M-5678") == "KA05M5678"
    assert validate_plate("KA05M5678") is True

    assert normalize_plate("MH 12 ABC 9999") == "MH12ABC9999"
    assert validate_plate("MH12ABC9999") is True

    # BH-series plates (2 digits year + BH + 4 digits + 1-2 letters)
    assert normalize_plate("22 BH 1234 AA") == "22BH1234AA"
    assert validate_plate("22BH1234AA") is True
    assert validate_plate("24BH9999A") is True

    # Invalid plates (must fail validation but be preserved)
    assert validate_plate("XYZ123") is False
    assert validate_plate("123456") is False
    assert validate_plate("") is False


@pytest.mark.asyncio
async def test_idempotency_same_event_uid_5_times(
    async_client: AsyncClient,
    setup_gate_and_device,
    raw_api_key: str,
    db_session: AsyncSession,
):
    """TEST 1: The same event_uid posted 5 times gives one row."""
    gate, device = setup_gate_and_device
    event_uid = f"evt-idemp-{uuid.uuid4()}"
    payload = {
        "event_uid": event_uid,
        "camera_id": "cam-anpr-01",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "plate_raw": "DL 01 AB 1234",
        "plate_conf": 0.95,
        "vehicle_type": "truck",
        "vehicle_color": "white",
        "load_type": "timber_logs",
        "load_conf": 0.88,
    }

    headers = {"X-API-Key": raw_api_key}
    detection_ids = []

    for _ in range(5):
        resp = await async_client.post("/api/v1/events", json=payload, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        detection_ids.append(data["id"])

    # All 5 responses return the exact same detection ID
    assert len(set(detection_ids)) == 1

    # Verify database has exactly 1 row with this event_uid
    stmt = select(func.count()).select_from(Detection).where(Detection.event_uid == event_uid)
    res = await db_session.execute(stmt)
    count = res.scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_concurrency_200_parallel_posts_gap_free_serial(
    db_session: AsyncSession,
    setup_gate_and_device,
):
    """TEST 2: Concurrency: 200 parallel posts give unique, gap-free day_serial."""
    gate, _ = setup_gate_and_device
    now = datetime.now(timezone.utc)
    num_concurrent = 200

    # Allocate 200 serials concurrently
    tasks = [
        allocate_day_serial(
            db=db_session,
            gate_id=gate.id,
            captured_at=now,
            timezone_str=gate.timezone,
        )
        for _ in range(num_concurrent)
    ]
    serials = await asyncio.gather(*tasks)

    # Must contain 200 results
    assert len(serials) == num_concurrent
    # All must be unique
    assert len(set(serials)) == num_concurrent
    # Must be strictly 1 through 200 without any gaps
    assert sorted(serials) == list(range(1, num_concurrent + 1))


@pytest.mark.asyncio
async def test_dedupe_window_merge_and_invalid_plate(
    async_client: AsyncClient,
    setup_gate_and_device,
    raw_api_key: str,
    db_session: AsyncSession,
):
    """TEST 3: Dedupe window merge (within 30 s merges into first record, keeping higher conf); invalid plate kept with plate_valid=false."""
    gate, device = setup_gate_and_device
    headers = {"X-API-Key": raw_api_key}

    # 1. Invalid plate test: kept with plate_valid=false, status=needs_review
    inv_event_uid = f"evt-inv-{uuid.uuid4()}"
    inv_payload = {
        "event_uid": inv_event_uid,
        "camera_id": "cam-anpr-01",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "plate_raw": "INVALID-1234",
        "plate_conf": 0.90,
        "vehicle_type": "car",
        "load_type": "empty",
        "load_conf": 0.90,
    }
    resp_inv = await async_client.post("/api/v1/events", json=inv_payload, headers=headers)
    assert resp_inv.status_code == 200
    inv_data = resp_inv.json()
    assert inv_data["plate"] == "INVALID1234"
    assert inv_data["plate_valid"] is False
    assert inv_data["status"] == "needs_review"  # Because plate_valid is False

    # 2. Dedupe window merge test:
    # First detection at t0 with low load_conf
    t0 = datetime.now(timezone.utc)
    first_event_uid = f"evt-first-{uuid.uuid4()}"
    first_payload = {
        "event_uid": first_event_uid,
        "camera_id": "cam-gate-north",
        "captured_at": t0.isoformat(),
        "plate_raw": "KA 05 M 5678",
        "plate_conf": 0.86,
        "vehicle_type": "other",
        "load_type": "unknown",
        "load_conf": 0.20,
    }
    resp1 = await async_client.post("/api/v1/events", json=first_payload, headers=headers)
    assert resp1.status_code == 200
    first_record = resp1.json()
    first_id = first_record["id"]
    assert first_record["status"] == "needs_review"  # low load_conf

    # Second detection at t0 + 10s (within 30s window) with same camera + plate, higher confidences
    t1 = t0 + timedelta(seconds=10)
    second_event_uid = f"evt-second-{uuid.uuid4()}"
    second_payload = {
        "event_uid": second_event_uid,
        "camera_id": "cam-gate-north",
        "captured_at": t1.isoformat(),
        "plate_raw": "KA05M5678",
        "plate_conf": 0.98,
        "vehicle_type": "truck",
        "load_type": "timber_logs",
        "load_conf": 0.92,
    }
    resp2 = await async_client.post("/api/v1/events", json=second_payload, headers=headers)
    assert resp2.status_code == 200
    merged_record = resp2.json()

    # The returned detection ID must match the first record's ID!
    assert merged_record["id"] == first_id
    assert merged_record["plate_conf"] == 0.98
    assert merged_record["load_conf"] == 0.92
    assert merged_record["load_type"] == "timber_logs"
    assert merged_record["vehicle_type"] == "truck"
    # Status should now be 'verified' because confidences are high!
    assert merged_record["status"] == "verified"


@pytest.mark.asyncio
async def test_direct_camera_push_endpoint(async_client: AsyncClient, setup_gate_and_device, raw_api_key: str):
    """Verifies that direct smart camera HTTP webhooks (Hikvision/Dahua) are parsed cleanly with zero PC."""
    gate, device = setup_gate_and_device

    # 1. Test direct camera push via query parameter api_key with JSON payload
    cam_json = {
        "plate": "CG07CU8073",
        "speed": 42.5,
        "confidence": 0.98,
    }
    resp = await async_client.post(
        f"/api/v1/events/camera-push?api_key={raw_api_key}",
        json=cam_json,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["plate"] == "CG07CU8073"
    assert data["plate_valid"] is True

    # 2. Test direct camera push with XML string in form (Hikvision ISAPI format)
    xml_data = """<?xml version="1.0" encoding="UTF-8"?>
    <EventNotificationAlert>
        <ANPR>
            <licensePlate>CG07AN8902</licensePlate>
            <speed>38.0</speed>
            <confidenceLevel>95</confidenceLevel>
        </ANPR>
    </EventNotificationAlert>
    """
    resp_xml = await async_client.post(
        f"/api/v1/events/camera-push?api_key={raw_api_key}",
        data={"anpr_xml": xml_data},
    )
    assert resp_xml.status_code == 200
    data_xml = resp_xml.json()
    assert data_xml["plate"] == "CG07AN8902"
    assert data_xml["plate_valid"] is True

