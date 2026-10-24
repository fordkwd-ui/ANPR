"""Detection ingestion, out-of-order handling, and business logic service."""
from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.core.dedupe import (
    compute_detection_status,
    find_dedupe_match,
    merge_detections,
)
from app.core.latency import latency_tracker
from app.core.plate import normalize_plate, validate_plate
from app.core.serial import allocate_day_serial
from app.models.detection import Detection, DetectionStatus, LoadSource, LoadType
from app.models.gate import Gate
from app.schemas.event import EventCreate


class DetectionService:
    @staticmethod
    async def ingest_event(
        db: AsyncSession,
        gate: Gate,
        payload: EventCreate,
    ) -> Tuple[Detection, bool]:
        """
        Ingests a Stage 1 event:
        1. Checks idempotency on event_uid (repeat returns same record, 200).
        2. Normalizes & validates plate (Indian state & BH series regex).
        3. Checks 30s deduplication window for same plate + camera (merges higher confidences).
        4. Atomically allocates gap-free day_serial in gate's local timezone.
        5. Computes status: 'needs_review' vs 'verified'.
        6. Inserts and commits detection record.
        7. Instruments ingestion latency.
        Returns (detection, is_new).
        """
        settings = get_settings()
        now = datetime.now(timezone.utc)

        # 1. Idempotency and Out-of-Order Check on event_uid or id
        conditions = [Detection.event_uid == payload.event_uid]
        if payload.id:
            conditions.append(Detection.id == payload.id)
        stmt = select(Detection).where(select(Detection).where(*conditions).whereclause)
        result = await db.execute(select(Detection).where(
            (Detection.event_uid == payload.event_uid) | (Detection.id == payload.id if payload.id else False)
        ))
        existing = result.scalar_one_or_none()
        if existing:
            # Check if this was an out-of-order placeholder created by media upload
            if existing.raw_event and existing.raw_event.get("placeholder"):
                # Complete the placeholder with real event data
                normalized_plate = normalize_plate(payload.plate_raw)
                plate_valid = validate_plate(normalized_plate)
                existing.event_uid = payload.event_uid
                existing.camera_id = payload.camera_id
                existing.captured_at = payload.captured_at
                existing.received_at = now
                existing.plate_raw = payload.plate_raw
                existing.plate = normalized_plate
                existing.plate_valid = plate_valid
                existing.plate_conf = payload.plate_conf
                existing.vehicle_type = payload.vehicle_type
                existing.vehicle_color = payload.vehicle_color
                existing.load_type = payload.load_type or LoadType.UNKNOWN
                existing.load_conf = payload.load_conf or 0.0
                existing.clip_ref = payload.clip_ref
                existing.raw_event = payload.model_dump(mode="json")
                existing.day_serial = await allocate_day_serial(
                    db=db,
                    gate_id=gate.id,
                    captured_at=payload.captured_at,
                    timezone_str=gate.timezone,
                )
                existing.status = compute_detection_status(
                    plate_valid=plate_valid,
                    plate_conf=payload.plate_conf,
                    load_conf=payload.load_conf or 0.0,
                    settings=settings,
                )
                await db.commit()
                await db.refresh(existing)
                latency_tracker.record_event(payload.captured_at, now)
                return existing, True
            return existing, False

        # 2. Plate Normalization & Validation
        normalized_plate = normalize_plate(payload.plate_raw)
        plate_valid = validate_plate(normalized_plate)

        # 3. Server-side Deduplication: same plate + camera within 30 s
        dedupe_match = await find_dedupe_match(
            db=db,
            gate_id=gate.id,
            camera_id=payload.camera_id,
            normalized_plate=normalized_plate,
            captured_at=payload.captured_at,
            window_seconds=30,
        )
        if dedupe_match:
            merged = merge_detections(
                target=dedupe_match,
                plate_raw=payload.plate_raw,
                normalized_plate=normalized_plate,
                plate_valid=plate_valid,
                plate_conf=payload.plate_conf,
                vehicle_type=payload.vehicle_type,
                vehicle_color=payload.vehicle_color,
                load_type=payload.load_type or LoadType.UNKNOWN,
                load_conf=payload.load_conf or 0.0,
                settings=settings,
            )
            await db.commit()
            await db.refresh(merged)
            latency_tracker.record_event(payload.captured_at, now)
            return merged, False

        # 4. Atomic Gap-Free day_serial Allocation
        day_serial = await allocate_day_serial(
            db=db,
            gate_id=gate.id,
            captured_at=payload.captured_at,
            timezone_str=gate.timezone,
        )

        # 5. Status Evaluation
        load_conf_val = payload.load_conf or 0.0
        status = compute_detection_status(
            plate_valid=plate_valid,
            plate_conf=payload.plate_conf,
            load_conf=load_conf_val,
            settings=settings,
        )

        # 6. Create Detection
        import uuid as _uuid
        detection = Detection(
            id=payload.id or _uuid.uuid4(),
            event_uid=payload.event_uid,
            gate_id=gate.id,
            camera_id=payload.camera_id,
            captured_at=payload.captured_at,
            received_at=now,
            day_serial=day_serial,
            plate_raw=payload.plate_raw,
            plate=normalized_plate,
            plate_valid=plate_valid,
            plate_conf=payload.plate_conf,
            vehicle_type=payload.vehicle_type,
            vehicle_color=payload.vehicle_color,
            load_type=payload.load_type or LoadType.UNKNOWN,
            load_conf=load_conf_val,
            load_source=LoadSource.AUTO,
            status=status,
            media_ready=False,
            clip_ref=payload.clip_ref,
            raw_event=payload.model_dump(mode="json"),
        )
        db.add(detection)
        await db.commit()
        await db.refresh(detection)

        # 7. Latency instrumentation
        latency_tracker.record_event(payload.captured_at, now)
        return detection, True
