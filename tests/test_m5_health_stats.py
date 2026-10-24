"""Milestone 5 tests: Heartbeat, 90s Offline Health Status, Stats Today, Video Clip Proxy, and CSV Export Audit."""
from datetime import datetime, timedelta, timezone
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.core.security import create_access_token, hash_api_key, hash_password
from app.models.audit import AuditAction, AuditView
from app.models.detection import Detection, DetectionStatus, LoadType, VehicleType
from app.models.gate import Device, Gate
from app.models.health import Health
from app.models.user import User, UserRole


@pytest.fixture
def raw_api_key():
    return "m5-edge-api-key"


@pytest.fixture
async def setup_gate_device_users(db_session: AsyncSession, raw_api_key: str):
    gate = Gate(name="Central Gate", timezone="Asia/Kolkata")
    db_session.add(gate)
    await db_session.flush()

    device = Device(
        gate_id=gate.id,
        name="Edge Controller Cam A/B",
        api_key_hash=hash_api_key(raw_api_key),
    )
    db_session.add(device)

    admin = User(username="admin_m5", password_hash=hash_password("adminpass"), role=UserRole.ADMIN)
    reviewer = User(username="reviewer_m5", password_hash=hash_password("revpass"), role=UserRole.REVIEWER)
    viewer = User(username="viewer_m5", password_hash=hash_password("viewpass"), role=UserRole.VIEWER)
    db_session.add_all([admin, reviewer, viewer])

    await db_session.commit()
    await db_session.refresh(gate)
    await db_session.refresh(device)
    await db_session.refresh(admin)
    await db_session.refresh(reviewer)
    await db_session.refresh(viewer)

    return {
        "gate": gate,
        "device": device,
        "admin": admin,
        "reviewer": reviewer,
        "viewer": viewer,
    }


@pytest.mark.asyncio
async def test_heartbeat_and_device_health_status(
    async_client: AsyncClient,
    setup_gate_device_users,
    raw_api_key: str,
    db_session: AsyncSession,
):
    """Verifies edge heartbeat logging and 90s online/offline threshold in /health/status."""
    data = setup_gate_device_users
    viewer = data["viewer"]
    viewer_token = create_access_token(viewer.username, viewer.role.value, viewer.id)

    # 1. Post heartbeat from gate box
    hb_payload = {
        "camera_a_ok": True,
        "camera_b_ok": True,
        "disk_used_pct": 42.5,
        "queue_depth": 3,
        "ups_on_battery": False,
        "raw": {"temperature_c": 51.2},
    }
    hb_resp = await async_client.post(
        "/api/v1/heartbeat",
        json=hb_payload,
        headers={"X-API-Key": raw_api_key},
    )
    assert hb_resp.status_code == 200
    assert hb_resp.json()["status"] == "ok"

    # Verify health row written
    h_stmt = select(Health).where(Health.device_id == data["device"].id)
    h_row = (await db_session.execute(h_stmt)).scalar_one_or_none()
    assert h_row is not None
    assert h_row.disk_used_pct == 42.5

    # 2. Check /health/status: device is online (< 90s)
    status_resp = await async_client.get(
        "/api/v1/health/status",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert status_resp.status_code == 200
    devices_status = status_resp.json()["devices"]
    assert len(devices_status) == 1
    assert devices_status[0]["online"] is True
    assert devices_status[0]["disk_used_pct"] == 42.5

    # 3. Simulate device going offline (last_seen_at 100 seconds ago)
    device = data["device"]
    device.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=100)
    await db_session.commit()

    offline_resp = await async_client.get(
        "/api/v1/health/status",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert offline_resp.status_code == 200
    assert offline_resp.json()["devices"][0]["online"] is False


@pytest.mark.asyncio
async def test_stats_today(
    async_client: AsyncClient,
    setup_gate_device_users,
    db_session: AsyncSession,
):
    """Verifies aggregate counts: vehicles, trucks, loaded, needs_review."""
    data = setup_gate_device_users
    viewer = data["viewer"]
    viewer_token = create_access_token(viewer.username, viewer.role.value, viewer.id)
    gate = data["gate"]
    now = datetime.now(timezone.utc)

    # Insert test detections:
    # 1. Truck with timber_logs (loaded, verified)
    d1 = Detection(
        event_uid="evt-stat-1",
        gate_id=gate.id,
        camera_id="cam-1",
        captured_at=now,
        day_serial=1,
        plate_raw="KA01AA1111",
        plate="KA01AA1111",
        plate_valid=True,
        plate_conf=0.95,
        vehicle_type=VehicleType.TRUCK,
        load_type=LoadType.TIMBER_LOGS,
        load_conf=0.90,
        status=DetectionStatus.VERIFIED,
    )
    # 2. Car, empty (not loaded, verified)
    d2 = Detection(
        event_uid="evt-stat-2",
        gate_id=gate.id,
        camera_id="cam-1",
        captured_at=now,
        day_serial=2,
        plate_raw="DL01BB2222",
        plate="DL01BB2222",
        plate_valid=True,
        plate_conf=0.95,
        vehicle_type=VehicleType.CAR,
        load_type=LoadType.EMPTY,
        load_conf=0.90,
        status=DetectionStatus.VERIFIED,
    )
    # 3. Truck, sand (loaded, needs_review)
    d3 = Detection(
        event_uid="evt-stat-3",
        gate_id=gate.id,
        camera_id="cam-1",
        captured_at=now,
        day_serial=3,
        plate_raw="MH12CC3333",
        plate="MH12CC3333",
        plate_valid=True,
        plate_conf=0.75,  # low conf
        vehicle_type=VehicleType.TRUCK,
        load_type=LoadType.SAND,
        load_conf=0.80,
        status=DetectionStatus.NEEDS_REVIEW,
    )
    db_session.add_all([d1, d2, d3])
    await db_session.commit()

    stats_resp = await async_client.get(
        "/api/v1/stats/today",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert stats["vehicles"] == 3
    assert stats["trucks"] == 2
    assert stats["loaded"] == 2  # timber_logs and sand
    assert stats["needs_review"] == 1


@pytest.mark.asyncio
async def test_csv_export_and_audit_logging(
    async_client: AsyncClient,
    setup_gate_device_users,
    db_session: AsyncSession,
):
    """Verifies that viewer cannot export, reviewer can, and an audit_views record is created."""
    data = setup_gate_device_users
    viewer = data["viewer"]
    reviewer = data["reviewer"]
    viewer_token = create_access_token(viewer.username, viewer.role.value, viewer.id)
    reviewer_token = create_access_token(reviewer.username, reviewer.role.value, reviewer.id)

    # 1. Viewer attempts export -> 403 Forbidden
    v_resp = await async_client.get(
        "/api/v1/detections/export.csv",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert v_resp.status_code == 403

    # 2. Reviewer exports -> 200 OK with CSV
    r_resp = await async_client.get(
        "/api/v1/detections/export.csv",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert r_resp.status_code == 200
    assert "text/csv" in r_resp.headers["Content-Type"]
    assert "plate_valid" in r_resp.text

    # 3. Verify audit_views logged row
    audit_stmt = select(AuditView).where(
        AuditView.user_id == reviewer.id,
        AuditView.action == AuditAction.EXPORT,
    )
    audit_entry = (await db_session.execute(audit_stmt)).scalar_one_or_none()
    assert audit_entry is not None
    assert audit_entry.action == AuditAction.EXPORT


@pytest.mark.asyncio
async def test_clip_proxy_url(
    async_client: AsyncClient,
    setup_gate_device_users,
    db_session: AsyncSession,
    monkeypatch,
):
    """Verifies GET /detections/{id}/clip behavior (501 when unset, 200 when configured)."""
    data = setup_gate_device_users
    viewer = data["viewer"]
    gate = data["gate"]
    viewer_token = create_access_token(viewer.username, viewer.role.value, viewer.id)

    # Detection with clip_ref
    det = Detection(
        event_uid="evt-clip-test",
        gate_id=gate.id,
        camera_id="cam-a",
        captured_at=datetime.now(timezone.utc),
        day_serial=1,
        plate_raw="KA01AA9999",
        plate="KA01AA9999",
        plate_valid=True,
        plate_conf=0.95,
        clip_ref={"camera": "cam-a", "segment": "seg_001.mp4", "start": "00:00:10", "end": "00:00:25"},
    )
    db_session.add(det)
    await db_session.commit()
    await db_session.refresh(det)

    # Case 1: CLIP_BASE_URL unset -> 501
    settings = get_settings()
    monkeypatch.setattr(settings, "CLIP_BASE_URL", None)
    resp1 = await async_client.get(
        f"/api/v1/detections/{det.id}/clip",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp1.status_code == 501

    # Case 2: CLIP_BASE_URL set -> 200 with URL
    monkeypatch.setattr(settings, "CLIP_BASE_URL", "https://tunnel.forest-gate-01.internal")
    resp2 = await async_client.get(
        f"/api/v1/detections/{det.id}/clip",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp2.status_code == 200
    clip_data = resp2.json()
    assert "https://tunnel.forest-gate-01.internal" in clip_data["clip_url"]
    assert "seg_001.mp4" in clip_data["clip_url"]
    assert clip_data["expires_in"] == 600
