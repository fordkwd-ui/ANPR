"""Milestone 6 tests: Keyset Pagination, Trigram Search, Reviewer Corrections Audit, and WebSocket Live Updates."""
import asyncio
import io
import time
from datetime import datetime, timezone
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient
from app.core.security import create_access_token, hash_api_key, hash_password
from app.main import app
from app.models.audit import AuditAction, AuditView
from app.models.detection import Correction, Detection, DetectionStatus, LoadType, VehicleType
from app.models.gate import Device, Gate
from app.models.user import User, UserRole


@pytest.fixture
def raw_api_key():
    return "m6-edge-api-key"


@pytest.fixture
async def setup_m6_environment(db_session: AsyncSession, raw_api_key: str):
    gate = Gate(name="West Forest Gate", timezone="Asia/Kolkata")
    db_session.add(gate)
    await db_session.flush()

    device = Device(
        gate_id=gate.id,
        name="Edge Terminal 6",
        api_key_hash=hash_api_key(raw_api_key),
    )
    db_session.add(device)

    admin = User(username="admin_6", password_hash=hash_password("adminpass"), role=UserRole.ADMIN)
    reviewer = User(username="reviewer_6", password_hash=hash_password("revpass"), role=UserRole.REVIEWER)
    viewer = User(username="viewer_6", password_hash=hash_password("viewpass"), role=UserRole.VIEWER)
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
async def test_role_matrix_and_corrections(
    async_client: AsyncClient,
    setup_m6_environment,
    db_session: AsyncSession,
):
    """TEST 5: Role matrix: viewer cannot PATCH or export; reviewer can; admin all."""
    env = setup_m6_environment
    gate = env["gate"]
    viewer = env["viewer"]
    reviewer = env["reviewer"]
    admin = env["admin"]

    viewer_token = create_access_token(viewer.username, viewer.role.value, viewer.id)
    reviewer_token = create_access_token(reviewer.username, reviewer.role.value, reviewer.id)
    admin_token = create_access_token(admin.username, admin.role.value, admin.id)

    # Create a detection needing review
    det = Detection(
        event_uid=f"evt-corr-{uuid.uuid4()}",
        gate_id=gate.id,
        camera_id="cam-1",
        captured_at=datetime.now(timezone.utc),
        day_serial=10,
        plate_raw="DL01AA0000",
        plate="DL01AA0000",
        plate_valid=True,
        plate_conf=0.90,
        vehicle_type=VehicleType.CAR,
        load_type=LoadType.UNKNOWN,
        load_conf=0.10,
        status=DetectionStatus.NEEDS_REVIEW,
    )
    db_session.add(det)
    await db_session.commit()
    await db_session.refresh(det)

    # 1. Viewer tries to PATCH detection -> 403 Forbidden
    v_patch = await async_client.patch(
        f"/api/v1/detections/{det.id}",
        json={"vehicle_type": "truck", "load_type": "timber_logs"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert v_patch.status_code == 403

    # 2. Reviewer PATCHes detection -> 200 OK
    r_patch = await async_client.patch(
        f"/api/v1/detections/{det.id}",
        json={
            "plate": "DL01AA9999",
            "vehicle_type": "truck",
            "load_type": "timber_logs",
        },
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert r_patch.status_code == 200
    patched_data = r_patch.json()
    assert patched_data["plate"] == "DL01AA9999"
    assert patched_data["vehicle_type"] == "truck"
    assert patched_data["load_type"] == "timber_logs"
    assert patched_data["status"] == "corrected"
    assert len(patched_data["corrections"]) == 3

    # Verify corrections table has rows
    corr_stmt = select(Correction).where(Correction.detection_id == det.id)
    corr_rows = (await db_session.execute(corr_stmt)).scalars().all()
    assert len(corr_rows) == 3

    # 3. Admin can also PATCH
    a_patch = await async_client.patch(
        f"/api/v1/detections/{det.id}",
        json={"vehicle_type": "van"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert a_patch.status_code == 200
    assert a_patch.json()["vehicle_type"] == "van"


@pytest.mark.asyncio
async def test_audit_view_on_detail(
    async_client: AsyncClient,
    setup_m6_environment,
    db_session: AsyncSession,
):
    """Verifies that GET /detections/{id} logs an audit_views view record."""
    env = setup_m6_environment
    viewer = env["viewer"]
    viewer_token = create_access_token(viewer.username, viewer.role.value, viewer.id)
    gate = env["gate"]

    det = Detection(
        event_uid=f"evt-view-audit-{uuid.uuid4()}",
        gate_id=gate.id,
        camera_id="cam-1",
        captured_at=datetime.now(timezone.utc),
        day_serial=11,
        plate_raw="KA05AA1234",
        plate="KA05AA1234",
        plate_valid=True,
        plate_conf=0.95,
    )
    db_session.add(det)
    await db_session.commit()
    await db_session.refresh(det)

    resp = await async_client.get(
        f"/api/v1/detections/{det.id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200

    # Verify audit view
    stmt = select(AuditView).where(
        AuditView.user_id == viewer.id,
        AuditView.detection_id == det.id,
        AuditView.action == AuditAction.VIEW,
    )
    entry = (await db_session.execute(stmt)).scalar_one_or_none()
    assert entry is not None


@pytest.mark.asyncio
async def test_keyset_pagination_and_plate_search(
    async_client: AsyncClient,
    setup_m6_environment,
    db_session: AsyncSession,
):
    """Verifies keyset cursor pagination and plate trigram search."""
    env = setup_m6_environment
    viewer = env["viewer"]
    viewer_token = create_access_token(viewer.username, viewer.role.value, viewer.id)
    gate = env["gate"]
    now = datetime.now(timezone.utc)

    # Insert 5 detections with sequential captured_at
    for i in range(5):
        d = Detection(
            event_uid=f"evt-page-{i}-{uuid.uuid4()}",
            gate_id=gate.id,
            camera_id="cam-1",
            captured_at=datetime.fromtimestamp(now.timestamp() + i, tz=timezone.utc),
            day_serial=i + 1,
            plate_raw=f"MH12AA{i:04d}",
            plate=f"MH12AA{i:04d}",
            plate_valid=True,
            plate_conf=0.95,
        )
        db_session.add(d)
    await db_session.commit()

    # Page 1 (limit 2)
    resp1 = await async_client.get(
        "/api/v1/detections?limit=2",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp1.status_code == 200
    page1 = resp1.json()
    assert len(page1["items"]) == 2
    assert page1["has_more"] is True
    cursor1 = page1["next_cursor"]
    assert cursor1 is not None

    # Page 2 with cursor
    resp2 = await async_client.get(
        f"/api/v1/detections?limit=2&cursor={cursor1}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp2.status_code == 200
    page2 = resp2.json()
    assert len(page2["items"]) == 2
    # Ensure items on page 2 are different from page 1
    p1_ids = [item["id"] for item in page1["items"]]
    p2_ids = [item["id"] for item in page2["items"]]
    assert len(set(p1_ids).intersection(p2_ids)) == 0

    # Search with plate substring
    search_resp = await async_client.get(
        "/api/v1/detections?plate=AA0003",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert search_resp.status_code == 200
    search_items = search_resp.json()["items"]
    assert len(search_items) == 1
    assert search_items[0]["plate"] == "MH12AA0003"


@pytest.mark.asyncio
async def test_websocket_created_then_updated_within_1_second(
    setup_m6_environment,
    raw_api_key: str,
):
    """TEST 6: WebSocket receives created then updated within 1 s locally."""
    env = setup_m6_environment
    viewer = env["viewer"]
    from app.db.session import get_db
    from tests.conftest import TestSessionLocal

    async def override_get_db():
        async with TestSessionLocal() as session:
            yield session
            await session.commit()

    viewer_token = create_access_token(viewer.username, viewer.role.value, viewer.id)
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    headers = {"X-API-Key": raw_api_key}

    start_time = time.time()
    with client.websocket_connect(f"/ws/live?token={viewer_token}") as websocket:
        # Step 1: Ingest event (Stage 1)
        event_uid = f"evt-ws-{uuid.uuid4()}"
        post_resp = client.post(
            "/api/v1/events",
            json={
                "event_uid": event_uid,
                "camera_id": "cam-a",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "plate_raw": "KA01AB9999",
                "plate_conf": 0.95,
                "vehicle_type": "truck",
                "load_type": "timber_logs",
                "load_conf": 0.90,
            },
            headers=headers,
        )
        assert post_resp.status_code == 200
        det_id = post_resp.json()["id"]

        # Step 2: Read WebSocket message 1: detection.created
        msg1 = websocket.receive_json()
        assert msg1["type"] == "detection.created"
        assert msg1["data"]["id"] == det_id
        assert "ws_sent_at" in msg1

        # Step 3: Edge uploads media (Stage 2)
        put_resp = client.put(
            f"/api/v1/detections/{det_id}/media",
            files={"plate": ("plate.jpg", io.BytesIO(b"img_bytes"), "image/jpeg")},
            headers=headers,
        )
        assert put_resp.status_code == 200

        # Step 4: Read WebSocket message 2: detection.updated
        msg2 = websocket.receive_json()
        assert msg2["type"] == "detection.updated"
        assert msg2["data"]["id"] == det_id
        assert "ws_sent_at" in msg2

        elapsed = time.time() - start_time
        # Must be received within 1 s locally
        assert elapsed < 1.0, f"WebSocket messages took {elapsed:.2f}s, expected < 1.0s"
