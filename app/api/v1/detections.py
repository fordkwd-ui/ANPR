"""Dashboard detections endpoints: CSV export, clip proxy, query listing, and corrections."""
import base64
import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.config import get_settings
from app.core.dependencies import get_current_user, require_role
from app.core.plate import normalize_plate, validate_plate
from app.db.session import get_db
from app.models.audit import AuditAction, AuditView
from app.models.detection import (
    Correction,
    Detection,
    DetectionStatus,
    LoadSource,
    LoadType,
    Media,
    VehicleType,
)
from app.models.user import User, UserRole
from app.schemas.detection import (
    CorrectionRead,
    DetectionCorrectionUpdate,
    DetectionDetailResponse,
    DetectionListItem,
    DetectionListResponse,
)
from app.services.storage import get_storage
from app.services.storage.base import StorageDriver

router = APIRouter(prefix="/detections", tags=["Detections & Analytics"])


@router.get("", response_model=DetectionListResponse)
async def list_detections(
    from_time: Optional[datetime] = Query(None, alias="from"),
    to_time: Optional[datetime] = Query(None, alias="to"),
    plate: Optional[str] = Query(None, description="Trigram/substring search on plate"),
    vehicle_type: Optional[VehicleType] = None,
    load_type: Optional[LoadType] = None,
    status_filter: Optional[DetectionStatus] = Query(None, alias="status"),
    gate_id: Optional[int] = Query(None, alias="gate"),
    cursor: Optional[str] = Query(None, description="Keyset cursor base64(captured_at|id)"),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: StorageDriver = Depends(get_storage),
):
    """
    Lists detections with newest-first keyset pagination and filters.
    Includes thumbnails as short-lived presigned URLs.
    """
    settings = get_settings()
    stmt = (
        select(Detection)
        .options(selectinload(Detection.media))
        .order_by(desc(Detection.captured_at), desc(Detection.id))
    )

    # Apply filters
    if from_time:
        stmt = stmt.where(Detection.captured_at >= from_time)
    if to_time:
        stmt = stmt.where(Detection.captured_at <= to_time)
    if plate:
        clean_plate = normalize_plate(plate)
        stmt = stmt.where(Detection.plate.ilike(f"%{clean_plate}%"))
    if vehicle_type:
        stmt = stmt.where(Detection.vehicle_type == vehicle_type)
    if load_type:
        stmt = stmt.where(Detection.load_type == load_type)
    if status_filter:
        stmt = stmt.where(Detection.status == status_filter)
    if gate_id:
        stmt = stmt.where(Detection.gate_id == gate_id)

    # Keyset cursor pagination
    if cursor:
        try:
            raw_cursor = base64.urlsafe_b64decode(cursor.encode()).decode()
            c_time_str, c_id_str = raw_cursor.split("|")
            c_time = datetime.fromisoformat(c_time_str)
            c_id = uuid.UUID(c_id_str)

            stmt = stmt.where(
                or_(
                    Detection.captured_at < c_time,
                    and_(Detection.captured_at == c_time, Detection.id < c_id),
                )
            )
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid pagination cursor")

    # Fetch limit + 1 to check has_more
    stmt = stmt.limit(limit + 1)
    result = await db.execute(stmt)
    records = list(result.scalars().all())

    has_more = len(records) > limit
    page_records = records[:limit]

    # Generate presigned URLs for thumbnails
    items: List[DetectionListItem] = []
    for d in page_records:
        thumb_map: Dict[str, str] = {}
        for m in d.media:
            if m.object_key:
                thumb_map[m.kind.value] = await storage.get_url(
                    m.object_key,
                    expire_seconds=settings.PRESIGNED_URL_EXPIRE_SECONDS,
                )

        item = DetectionListItem(
            id=d.id,
            event_uid=d.event_uid,
            day_serial=d.day_serial,
            gate_id=d.gate_id,
            camera_id=d.camera_id,
            captured_at=d.captured_at,
            received_at=d.received_at,
            plate_raw=d.plate_raw,
            plate=d.plate,
            plate_valid=d.plate_valid,
            plate_conf=d.plate_conf,
            vehicle_type=d.vehicle_type,
            vehicle_color=d.vehicle_color,
            vehicle_make=d.vehicle_make,
            vehicle_model=d.vehicle_model,
            speed_kph=d.speed_kph,
            direction=d.direction,
            load_type=d.load_type,
            load_conf=d.load_conf,
            load_source=d.load_source,
            status=d.status,
            media_ready=d.media_ready,
            thumbnails=thumb_map,
            clip_ref=d.clip_ref,
            raw_event=d.raw_event,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        items.append(item)

    next_cursor = None
    if has_more and page_records:
        last = page_records[-1]
        raw_val = f"{last.captured_at.isoformat()}|{str(last.id)}"
        next_cursor = base64.urlsafe_b64encode(raw_val.encode()).decode()

    return DetectionListResponse(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get("/export.csv")
async def export_detections_csv(
    from_time: Optional[datetime] = Query(None, alias="from"),
    to_time: Optional[datetime] = Query(None, alias="to"),
    vehicle_type: Optional[VehicleType] = None,
    load_type: Optional[LoadType] = None,
    status_filter: Optional[DetectionStatus] = Query(None, alias="status"),
    gate_id: Optional[int] = Query(None, alias="gate"),
    current_user: User = Depends(require_role(UserRole.REVIEWER, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    Exports filtered detections as CSV.
    Reviewer or Admin only. Logs an audit_views export event.
    """
    now = datetime.now(timezone.utc)

    # 1. Log audit_views row
    audit = AuditView(
        user_id=current_user.id,
        detection_id=None,
        action=AuditAction.EXPORT,
        at=now,
    )
    db.add(audit)
    await db.commit()

    # 2. Build Query
    stmt = select(Detection).order_by(desc(Detection.captured_at))
    if from_time:
        stmt = stmt.where(Detection.captured_at >= from_time)
    if to_time:
        stmt = stmt.where(Detection.captured_at <= to_time)
    if vehicle_type:
        stmt = stmt.where(Detection.vehicle_type == vehicle_type)
    if load_type:
        stmt = stmt.where(Detection.load_type == load_type)
    if status_filter:
        stmt = stmt.where(Detection.status == status_filter)
    if gate_id:
        stmt = stmt.where(Detection.gate_id == gate_id)

    result = await db.execute(stmt)
    detections = result.scalars().all()

    # 3. Stream CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id",
        "day_serial",
        "captured_at",
        "gate_id",
        "camera_id",
        "plate",
        "plate_valid",
        "plate_conf",
        "vehicle_type",
        "vehicle_color",
        "load_type",
        "load_conf",
        "status",
        "media_ready",
    ])
    for d in detections:
        writer.writerow([
            str(d.id),
            d.day_serial,
            d.captured_at.isoformat() if d.captured_at else "",
            d.gate_id,
            d.camera_id,
            d.plate,
            d.plate_valid,
            d.plate_conf,
            d.vehicle_type.value,
            d.vehicle_color or "",
            d.load_type.value,
            d.load_conf,
            d.status.value,
            d.media_ready,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="detections_export.csv"'},
    )


@router.get("/{detection_id}/clip")
async def get_detection_clip(
    detection_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns short-lived video clip URL from CLIP_BASE_URL + clip_ref."""
    settings = get_settings()
    stmt = select(Detection).where(Detection.id == detection_id)
    result = await db.execute(stmt)
    detection = result.scalar_one_or_none()
    if not detection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detection not found")

    if not detection.clip_ref:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Clip reference is not available for this detection",
        )

    if not settings.CLIP_BASE_URL:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="CLIP_BASE_URL is not configured on the server",
        )

    base = settings.CLIP_BASE_URL.rstrip("/")
    clip_ref = detection.clip_ref
    camera = clip_ref.get("camera", detection.camera_id)
    segment = clip_ref.get("segment", "latest")
    start = clip_ref.get("start", "")
    end = clip_ref.get("end", "")

    clip_url = f"{base}/clips/{camera}/{segment}?start={start}&end={end}&expires=600"
    return {
        "clip_url": clip_url,
        "expires_in": 600,
    }


@router.get("/{detection_id}", response_model=DetectionDetailResponse)
async def get_detection_detail(
    detection_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: StorageDriver = Depends(get_storage),
):
    """
    Retrieves full detection record, presigned media URLs, and corrections history.
    Logs an audit_views view action.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)

    # 1. Log view in audit_views
    audit = AuditView(
        user_id=current_user.id,
        detection_id=detection_id,
        action=AuditAction.VIEW,
        at=now,
    )
    db.add(audit)
    await db.commit()

    # 2. Query detection with media and corrections
    stmt = (
        select(Detection)
        .options(
            selectinload(Detection.media),
            selectinload(Detection.corrections),
        )
        .where(Detection.id == detection_id)
    )
    result = await db.execute(stmt)
    detection = result.scalar_one_or_none()
    if not detection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detection not found")

    # 3. Presigned URLs
    media_map: Dict[str, str] = {}
    for m in detection.media:
        if m.object_key:
            media_map[m.kind.value] = await storage.get_url(
                m.object_key,
                expire_seconds=settings.PRESIGNED_URL_EXPIRE_SECONDS,
            )

    return DetectionDetailResponse(
        id=detection.id,
        event_uid=detection.event_uid,
        day_serial=detection.day_serial,
        gate_id=detection.gate_id,
        camera_id=detection.camera_id,
        captured_at=detection.captured_at,
        received_at=detection.received_at,
        plate_raw=detection.plate_raw,
        plate=detection.plate,
        plate_valid=detection.plate_valid,
        plate_conf=detection.plate_conf,
        vehicle_type=detection.vehicle_type,
        vehicle_color=detection.vehicle_color,
        vehicle_make=detection.vehicle_make,
        vehicle_model=detection.vehicle_model,
        speed_kph=detection.speed_kph,
        direction=detection.direction,
        load_type=detection.load_type,
        load_conf=detection.load_conf,
        load_source=detection.load_source,
        status=detection.status,
        media_ready=detection.media_ready,
        thumbnails=media_map,
        media_urls=media_map,
        clip_ref=detection.clip_ref,
        raw_event=detection.raw_event,
        created_at=detection.created_at,
        updated_at=detection.updated_at,
        corrections=[CorrectionRead.model_validate(c) for c in detection.corrections],
    )


@router.patch("/{detection_id}", response_model=DetectionDetailResponse)
async def correct_detection(
    detection_id: uuid.UUID,
    payload: DetectionCorrectionUpdate,
    current_user: User = Depends(require_role(UserRole.REVIEWER, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
    storage: StorageDriver = Depends(get_storage),
):
    """
    Reviewer or Admin correction endpoint:
    Modifies plate, vehicle_type, or load_type.
    Writes corrections rows, updates status=corrected, and broadcasts detection.updated.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        select(Detection)
        .options(
            selectinload(Detection.media),
            selectinload(Detection.corrections),
        )
        .where(Detection.id == detection_id)
    )
    result = await db.execute(stmt)
    detection = result.scalar_one_or_none()
    if not detection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detection not found")

    corrections_added = False

    # Plate correction
    if payload.plate is not None:
        norm_plate = normalize_plate(payload.plate)
        if norm_plate != detection.plate:
            corr = Correction(
                detection_id=detection.id,
                field="plate",
                old_value=detection.plate,
                new_value=norm_plate,
                user_id=current_user.id,
                at=now,
            )
            db.add(corr)
            detection.plate_raw = payload.plate
            detection.plate = norm_plate
            detection.plate_valid = validate_plate(norm_plate)
            corrections_added = True

    # Vehicle type correction
    if payload.vehicle_type is not None and payload.vehicle_type != detection.vehicle_type:
        corr = Correction(
            detection_id=detection.id,
            field="vehicle_type",
            old_value=detection.vehicle_type.value,
            new_value=payload.vehicle_type.value,
            user_id=current_user.id,
            at=now,
        )
        db.add(corr)
        detection.vehicle_type = payload.vehicle_type
        corrections_added = True

    # Load type correction
    if payload.load_type is not None and payload.load_type != detection.load_type:
        corr = Correction(
            detection_id=detection.id,
            field="load_type",
            old_value=detection.load_type.value,
            new_value=payload.load_type.value,
            user_id=current_user.id,
            at=now,
        )
        db.add(corr)
        detection.load_type = payload.load_type
        detection.load_source = LoadSource.MANUAL
        corrections_added = True

    # Status update (e.g. verified or needs_review)
    if payload.status is not None and payload.status != detection.status:
        corr = Correction(
            detection_id=detection.id,
            field="status",
            old_value=detection.status.value,
            new_value=payload.status.value,
            user_id=current_user.id,
            at=now,
        )
        db.add(corr)
        detection.status = payload.status
        corrections_added = True

    if corrections_added:
        if payload.status is None:
            detection.status = DetectionStatus.CORRECTED
        detection.updated_at = now
        await db.commit()
        await db.refresh(detection)

        # Broadcast update to live dashboard
        from app.services.websocket import broadcaster
        await broadcaster.broadcast("detection.updated", {
            "id": str(detection.id),
            "status": detection.status.value,
            "plate": detection.plate,
            "vehicle_type": detection.vehicle_type.value,
            "load_type": detection.load_type.value,
        })

    # Return refreshed detail response
    return await get_detection_detail(detection_id, current_user, db, storage)


@router.post("/clear-all", status_code=status.HTTP_200_OK)
async def clear_all_detections(
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.REVIEWER)),
    db: AsyncSession = Depends(get_db),
):
    """
    Clears all test detection records and resets daily counters.
    Allows operational testing on clean real data.
    """
    from sqlalchemy import text
    await db.execute(text("DELETE FROM audit_views"))
    await db.execute(text("DELETE FROM corrections"))
    await db.execute(text("DELETE FROM media"))
    await db.execute(text("DELETE FROM detections"))
    await db.execute(text("DELETE FROM daily_counters"))
    await db.commit()

    from app.services.websocket import broadcaster
    await broadcaster.broadcast("register.cleared", {})

    return {"status": "ok", "message": "All detection records and counters cleared."}

