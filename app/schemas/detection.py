"""Schemas for dashboard detection query, detail, and corrections."""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.models.detection import DetectionStatus, LoadSource, LoadType, VehicleType


class CorrectionRead(BaseModel):
    id: int
    field: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    user_id: Optional[int] = None
    at: datetime

    model_config = ConfigDict(from_attributes=True)


class DetectionListItem(BaseModel):
    id: uuid.UUID
    event_uid: str
    day_serial: int
    gate_id: int
    camera_id: str
    captured_at: datetime
    received_at: datetime
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
    raw_event: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DetectionListResponse(BaseModel):
    items: List[DetectionListItem]
    next_cursor: Optional[str] = None
    has_more: bool


class DetectionDetailResponse(DetectionListItem):
    media_urls: Dict[str, str] = Field(default_factory=dict)
    corrections: List[CorrectionRead] = Field(default_factory=list)


class DetectionCorrectionUpdate(BaseModel):
    plate: Optional[str] = None
    vehicle_type: Optional[VehicleType] = None
    load_type: Optional[LoadType] = None
    status: Optional[DetectionStatus] = None
