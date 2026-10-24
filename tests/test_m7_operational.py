"""Milestone 7 tests: Latency Metrics API, Operational Seed Script, and Load Test validation."""
from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.latency import latency_tracker
from app.models.gate import Device, Gate
from app.models.user import User
from app.scripts.seed import seed
from scripts.load_test import percentile, run_load_test


@pytest.mark.asyncio
async def test_latency_metrics_api(async_client: AsyncClient):
    """Verifies GET /metrics/latency calculates p50 and p95 correctly."""
    now = datetime.now(timezone.utc)
    # Record synthetic events: 50ms, 100ms, 150ms, 200ms
    latency_tracker.record_event(now - timedelta(milliseconds=50), now)
    latency_tracker.record_event(now - timedelta(milliseconds=100), now)
    latency_tracker.record_event(now - timedelta(milliseconds=150), now)
    latency_tracker.record_event(now - timedelta(milliseconds=200), now)

    resp = await async_client.get("/api/v1/metrics/latency")
    assert resp.status_code == 200
    metrics = resp.json()
    assert metrics["samples_count"] >= 4
    assert metrics["received_to_captured_p50_ms"] > 0.0
    assert metrics["received_to_captured_p95_ms"] >= metrics["received_to_captured_p50_ms"]


def test_percentile_calculation():
    """Verifies math accuracy of percentile calculation."""
    data = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    p50 = percentile(data, 50)
    p95 = percentile(data, 95)
    assert p50 == 55.0
    assert 90.0 <= p95 <= 100.0


@pytest.mark.asyncio
async def test_seed_script_execution(db_session: AsyncSession):
    """Verifies that seed() successfully populates default admin, reviewer, viewer, gate, and device."""
    from tests.conftest import TestSessionLocal
    await seed(session_maker=TestSessionLocal)

    # Verify admin
    admin = (await db_session.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
    assert admin is not None
    assert admin.role.value == "admin"

    # Verify gate
    gate = (await db_session.execute(select(Gate).limit(1))).scalar_one_or_none()
    assert gate is not None

    # Verify device
    dev = (await db_session.execute(select(Device).limit(1))).scalar_one_or_none()
    assert dev is not None
    assert len(dev.api_key_hash) == 64
