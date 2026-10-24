"""Heartbeat telemetry ingestion and health monitoring endpoints."""
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_current_device, get_current_user
from app.db.session import get_db
from app.models.gate import Device
from app.models.health import Health
from app.models.user import User
from app.schemas.health import DeviceHealthStatus, HealthSummaryResponse, HeartbeatCreate

router = APIRouter(tags=["Health & Telemetry"])


@router.post("/heartbeat", status_code=status.HTTP_200_OK)
async def post_heartbeat(
    payload: HeartbeatCreate,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """
    Heartbeat sent by gate box every 30s.
    Logs telemetry, updates last_seen_at, and broadcasts health status.
    """
    now = datetime.now(timezone.utc)
    health_log = Health(
        device_id=device.id,
        at=now,
        camera_a_ok=payload.camera_a_ok,
        camera_b_ok=payload.camera_b_ok,
        disk_used_pct=payload.disk_used_pct,
        queue_depth=payload.queue_depth,
        ups_on_battery=payload.ups_on_battery,
        raw=payload.raw,
    )
    db.add(health_log)
    device.last_seen_at = now
    await db.commit()

    from app.services.websocket import broadcaster
    await broadcaster.broadcast("health.updated", {
        "device_id": device.id,
        "last_seen_at": now.isoformat(),
        "camera_a_ok": payload.camera_a_ok,
        "camera_b_ok": payload.camera_b_ok,
        "disk_used_pct": payload.disk_used_pct,
        "queue_depth": payload.queue_depth,
        "ups_on_battery": payload.ups_on_battery,
    })

    return {"status": "ok"}


@router.get("/health/status", response_model=HealthSummaryResponse)
async def get_health_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns online/offline status for all gate devices.
    Device is online if last_seen_at is within the last 90 seconds.
    """
    now = datetime.now(timezone.utc)
    devices_stmt = select(Device).order_by(Device.id)
    devices = (await db.execute(devices_stmt)).scalars().all()

    status_list: List[DeviceHealthStatus] = []
    for dev in devices:
        is_online = False
        if dev.last_seen_at:
            last_seen = dev.last_seen_at
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            delta = (now - last_seen).total_seconds()
            is_online = delta < 90.0

        # Fetch latest health record
        h_stmt = (
            select(Health)
            .where(Health.device_id == dev.id)
            .order_by(desc(Health.at))
            .limit(1)
        )
        h_res = await db.execute(h_stmt)
        latest_h = h_res.scalar_one_or_none()

        status_list.append(
            DeviceHealthStatus(
                device_id=dev.id,
                device_name=dev.name,
                gate_id=dev.gate_id,
                online=is_online,
                last_seen_at=dev.last_seen_at,
                camera_a_ok=(latest_h.camera_a_ok if latest_h else False) if is_online else False,
                camera_b_ok=(latest_h.camera_b_ok if latest_h else False) if is_online else False,
                disk_used_pct=latest_h.disk_used_pct if latest_h else 0.0,
                queue_depth=latest_h.queue_depth if latest_h else 0,
                ups_on_battery=latest_h.ups_on_battery if latest_h else False,
            )
        )

    return HealthSummaryResponse(devices=status_list)
