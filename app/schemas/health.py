"""Heartbeat and device health schemas."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class HeartbeatCreate(BaseModel):
    """Payload sent by gate box every 30s."""
    camera_a_ok: bool = True
    camera_b_ok: bool = True
    disk_used_pct: float = Field(..., ge=0.0, le=100.0)
    queue_depth: int = Field(default=0, ge=0)
    ups_on_battery: bool = False
    raw: Optional[Dict[str, Any]] = None


class DeviceHealthStatus(BaseModel):
    """Device health status returned to dashboard."""
    device_id: int
    device_name: str
    gate_id: int
    online: bool
    last_seen_at: Optional[datetime] = None
    camera_a_ok: bool = True
    camera_b_ok: bool = True
    disk_used_pct: float = 0.0
    queue_depth: int = 0
    ups_on_battery: bool = False

    model_config = ConfigDict(from_attributes=True)


class HealthSummaryResponse(BaseModel):
    devices: List[DeviceHealthStatus]
