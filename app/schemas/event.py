"""Event schemas for ingestion and responses."""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from app.models.detection import (
    DetectionStatus,
    LoadSource,
    LoadType,
    VehicleType,
)


class EventCreate(BaseModel):
    """Stage 1 event payload from gate box."""
    id: Optional[uuid.UUID] = None
    event_uid: str = Field(..., min_length=1, max_length=128)
    camera_id: str = Field(..., min_length=1, max_length=50)
    captured_at: datetime
    plate_raw: str = Field(..., max_length=64)
    plate_conf: float = Field(default=0.0, ge=0.0, le=1.0)
    vehicle_type: VehicleType = VehicleType.OTHER
    vehicle_color: Optional[str] = Field(None, max_length=50)
    vehicle_make: Optional[str] = Field(None, max_length=50)
    vehicle_model: Optional[str] = Field(None, max_length=50)
    speed_kph: Optional[float] = None
    direction: Optional[str] = Field(None, max_length=50)
    direction_rad: Optional[float] = None
    speed_reliability: Optional[float] = None
    color_info: Optional[Any] = None
    model_info: Optional[Any] = None
    speed_info: Optional[Any] = None
    load_type: Optional[LoadType] = LoadType.UNKNOWN
    load_conf: Optional[float] = Field(default=0.0, ge=0.0, le=1.0)
    clip_ref: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="allow")


class LateLoadUpdate(BaseModel):
    """Stage 2 late load classifier result."""
    load_type: LoadType
    load_conf: float = Field(..., ge=0.0, le=1.0)


class DetectionRead(BaseModel):
    id: uuid.UUID
    event_uid: str
    gate_id: int
    camera_id: str
    captured_at: datetime
    received_at: datetime
    day_serial: int
    plate_raw: str
    plate: str
    plate_valid: bool
    plate_conf: float
    vehicle_type: VehicleType
    vehicle_color: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    speed_kph: Optional[float] = None
    direction: Optional[str] = None
    load_type: LoadType
    load_conf: float
    load_source: LoadSource
    status: DetectionStatus
    media_ready: bool
    thumbnails: Dict[str, str] = Field(default_factory=dict)
    clip_ref: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("captured_at", "received_at", "created_at", "updated_at", when_used="json")
    def serialize_dt(self, dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    model_config = ConfigDict(from_attributes=True)
