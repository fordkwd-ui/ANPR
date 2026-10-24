"""Deduplication and detection status evaluation rules."""
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import Settings
from app.models.detection import Detection, DetectionStatus, LoadType, VehicleType


def compute_detection_status(
    plate_valid: bool,
    plate_conf: float,
    load_conf: float,
    settings: Settings,
) -> DetectionStatus:
    """
    Evaluates status:
    'needs_review' when load_conf < 0.60, or plate_valid is false, or plate_conf < 0.85;
    else 'verified'.
    """
    if not plate_valid:
        return DetectionStatus.NEEDS_REVIEW
    if plate_conf < settings.CONF_THRESHOLD_PLATE:
        return DetectionStatus.NEEDS_REVIEW
    if load_conf < settings.CONF_THRESHOLD_LOAD:
        return DetectionStatus.NEEDS_REVIEW
    return DetectionStatus.VERIFIED


async def find_dedupe_match(
    db: AsyncSession,
    gate_id: int,
    camera_id: str,
    normalized_plate: str,
    captured_at: datetime,
    window_seconds: int = 30,
) -> Optional[Detection]:
    """
    Finds existing detection for the same plate + camera within window_seconds.
    """
    if not normalized_plate:
        return None

    window_start = captured_at - timedelta(seconds=window_seconds)
    window_end = captured_at + timedelta(seconds=window_seconds)

    stmt = (
        select(Detection)
        .where(
            Detection.gate_id == gate_id,
            Detection.camera_id == camera_id,
            Detection.plate == normalized_plate,
            Detection.captured_at >= window_start,
            Detection.captured_at <= window_end,
        )
        .order_by(Detection.captured_at.asc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def merge_detections(
    target: Detection,
    plate_raw: str,
    normalized_plate: str,
    plate_valid: bool,
    plate_conf: float,
    vehicle_type: VehicleType,
    vehicle_color: Optional[str],
    load_type: LoadType,
    load_conf: float,
    settings: Settings,
) -> Detection:
    """
    Merges higher-confidence values into target detection.
    """
    if plate_conf > target.plate_conf:
        target.plate_conf = plate_conf
        target.plate_raw = plate_raw
        target.plate = normalized_plate
        target.plate_valid = plate_valid

    if load_conf > target.load_conf:
        target.load_conf = load_conf
        target.load_type = load_type

    if vehicle_type != VehicleType.OTHER and target.vehicle_type == VehicleType.OTHER:
        target.vehicle_type = vehicle_type

    if vehicle_color and not target.vehicle_color:
        target.vehicle_color = vehicle_color

    # Re-evaluate status
    target.status = compute_detection_status(
        plate_valid=target.plate_valid,
        plate_conf=target.plate_conf,
        load_conf=target.load_conf,
        settings=settings,
    )
    return target
