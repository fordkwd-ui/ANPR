import random
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.core.dedupe import compute_detection_status
from app.core.dependencies import get_current_actor, get_current_device
from app.core.ocr_helper import process_mobile_photo_capture
from app.core.plate import normalize_plate, validate_plate
from app.db.session import get_db
from app.models.detection import (
    Detection,
    DetectionStatus,
    LoadSource,
    LoadType,
    Media,
    MediaKind,
    VehicleType,
)
from app.models.gate import Device, Gate
from app.models.user import User
from app.schemas.event import DetectionRead, EventCreate, LateLoadUpdate
from app.services.detection_service import DetectionService
from app.services.storage import get_storage
from app.services.storage.base import StorageDriver

router = APIRouter(tags=["Gate Box Ingestion"])


@router.post(
    "/events",
    response_model=DetectionRead,
    status_code=status.HTTP_200_OK,
    summary="Stage 1 Edge Event Ingestion",
)
async def post_event(
    payload: EventCreate,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """
    Stage 1 small JSON event from gate box.
    Idempotent on event_uid (repeat returns same id, 200).
    Normalizes plates, runs server-side dedupe (30s window), allocates gap-free day_serial.
    """
    stmt = select(Gate).where(Gate.id == device.gate_id)
    result = await db.execute(stmt)
    gate = result.scalar_one()

    detection, _ = await DetectionService.ingest_event(db, gate, payload)
    read_data = DetectionRead.model_validate(detection)

    # Real-time WebSocket broadcast (<1s)
    from app.services.websocket import broadcaster
    await broadcaster.broadcast("detection.created", read_data.model_dump(mode="json"))

    return read_data


@router.post(
    "/events/capture",
    response_model=DetectionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Direct Mobile / Edge Camera Photo Ingestion & Processing",
)
async def capture_event_photo(
    photo: UploadFile = File(..., description="High-resolution vehicle photo from mobile camera or edge camera"),
    cargo_photo: Optional[UploadFile] = File(None, description="Optional cargo bed or rear snapshot"),
    plate: Optional[str] = Form(None, description="Optional manual license plate number override"),
    vehicle_type: Optional[str] = Form(None, description="Optional vehicle class (car, motorcycle, truck, bus, pickup)"),
    vehicle_color: Optional[str] = Form(None, description="Optional vehicle color"),
    load_type: Optional[str] = Form(None, description="Optional cargo classification"),
    speed_kph: Optional[float] = Form(0.0),
    direction: Optional[str] = Form("Ingress (Entry)"),
    actor: Tuple[Optional[Device], Optional[User]] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
    storage: StorageDriver = Depends(get_storage),
):
    """
    Direct Photo Capture Endpoint for Mobile Officers & Live Camera Gate:
    1. Ingests raw photo taken directly from phone camera or gate stream.
    2. Auto-rotates image according to mobile EXIF data.
    3. Runs neural OCR & vehicle analysis.
    4. Slices 3 crisp evidentiary photos: Plate Crop, Full Scene, Cargo Bed.
    5. Allocates official Daily Gate Pass Serial (#001, #002, etc.).
    6. Persists media photos to Cloud Storage & Neon Postgres.
    7. Broadcasts live updates via WebSockets in 0 seconds!
    """
    device, user = actor
    gate_id = device.gate_id if device else 1
    stmt = select(Gate).where(Gate.id == gate_id)
    result = await db.execute(stmt)
    gate = result.scalar_one_or_none()
    if not gate:
        stmt_any = select(Gate).limit(1)
        res_any = await db.execute(stmt_any)
        gate = res_any.scalar_one_or_none()
    if not gate:
        gate = Gate(name="Sector 01 Main Gate", timezone="Asia/Kolkata")
        db.add(gate)
        await db.flush()

    photo_bytes = await photo.read()
    if not photo_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded photo is empty")

    cargo_bytes = await cargo_photo.read() if cargo_photo else None

    # Run AI pipeline
    processed = process_mobile_photo_capture(
        photo_bytes=photo_bytes,
        user_plate=plate,
        cargo_bytes=cargo_bytes,
        user_vehicle_type=vehicle_type,
        user_load_type=load_type,
        user_color=vehicle_color,
    )

    now = datetime.now(timezone.utc)
    event_uid = f"mob-{uuid.uuid4().hex[:12]}"

    payload = EventCreate(
        event_uid=event_uid,
        camera_id="cam-mobile-1" if not device else "cam-edge",
        captured_at=now,
        plate_raw=processed["plate_raw"],
        plate_conf=processed["plate_conf"],
        vehicle_type=processed["vehicle_type"],
        vehicle_color=processed["vehicle_color"],
        load_type=processed["load_type"],
        load_conf=0.95,
        speed_kph=speed_kph or 0.0,
        direction=direction or "Ingress (Entry)",
        speed_reliability=1.0,
    )

    # 1. Ingest event metadata and assign Day Serial
    detection, _ = await DetectionService.ingest_event(db, gate, payload)

    # 2. Save the 3 evidentiary photos to storage
    obj_key_plate = f"detections/{detection.id}/plate.jpg"
    obj_key_scene = f"detections/{detection.id}/scene.jpg"
    obj_key_cargo = f"detections/{detection.id}/cargo.jpg"

    b_plate = await storage.save_file(obj_key_plate, processed["plate_bytes"], "image/jpeg")
    b_scene = await storage.save_file(obj_key_scene, processed["scene_bytes"], "image/jpeg")
    b_cargo = await storage.save_file(obj_key_cargo, processed["cargo_bytes"], "image/jpeg")

    m_plate = Media(
        detection_id=detection.id,
        kind=MediaKind.PLATE,
        object_key=obj_key_plate,
        bytes=b_plate,
        created_at=now,
    )
    m_scene = Media(
        detection_id=detection.id,
        kind=MediaKind.SCENE,
        object_key=obj_key_scene,
        bytes=b_scene,
        created_at=now,
    )
    m_cargo = Media(
        detection_id=detection.id,
        kind=MediaKind.LOAD_THUMB,
        object_key=obj_key_cargo,
        bytes=b_cargo,
        created_at=now,
    )
    db.add_all([m_plate, m_scene, m_cargo])
    detection.media_ready = True
    detection.updated_at = now
    await db.commit()
    await db.refresh(detection)

    read_data = DetectionRead.model_validate(detection)

    # 3. Real-time broadcast (< 100ms)
    from app.services.websocket import broadcaster
    await broadcaster.broadcast("detection.created", read_data.model_dump(mode="json"))
    await broadcaster.broadcast("detection.updated", read_data.model_dump(mode="json"))

    return read_data


_sim_cycle_index = 0


@router.post(
    "/events/simulate",
    response_model=DetectionRead,
    status_code=status.HTTP_200_OK,
    summary="Simulate edge vehicle crossing for instant live demo",
)
async def post_simulate_event(
    db: AsyncSession = Depends(get_db),
    storage: StorageDriver = Depends(get_storage),
):
    """
    Simulates authentic gate crossings matching real-world checkpost captures.
    Strictly follows zero-assumption policy:
    - Vehicles at gate barrier stop: speed is locked to 0.0 km/h [STOPPED AT GATE].
    - Two-wheelers and cars are never assigned fake commercial timber cargo.
    - Attaches real high-resolution capture photos from gate_captures/ for plate crop, front, and back views.
    """
    global _sim_cycle_index
    stmt = select(Gate).limit(1)
    result = await db.execute(stmt)
    gate = result.scalar_one_or_none()

    if not gate:
        gate = Gate(name="Pine Valley Forest Gate", timezone="Asia/Kolkata")
        db.add(gate)
        await db.commit()
        await db.refresh(gate)

    # Authentic real-world vehicle profiles
    sample_profiles = [
        {
            "plate": "CG 07 CU 8073",
            "vehicle_type": VehicleType.MOTORCYCLE,
            "color": "black",
            "make": "Honda",
            "model": "Activa 6G",
            "load_type": LoadType.EMPTY,
            "load_conf": 1.0,
            "speed_kph": 0.0,
            "direction": "Stationary (Gate)",
            "plate_file": "gate_captures/20261024_012933_CG07CU8073_1_plate.jpg",
            "scene_file": "gate_captures/20261024_012933_CG07CU8073_2_vehicle.jpg",
            "cargo_file": "gate_captures/20261024_012933_CG07CU8073_3_cargo.jpg",
        },
        {
            "plate": "KA 05 MN 4821",
            "vehicle_type": VehicleType.TRUCK,
            "color": "yellow",
            "make": "Tata",
            "model": "Prima 4028.S",
            "load_type": LoadType.TIMBER_LOGS,
            "load_conf": 0.95,
            "speed_kph": 0.0,
            "direction": "Stationary (Gate)",
            "plate_file": "gate_captures/20261022_191213_CG07AN8902_1_plate.jpg",
            "scene_file": "gate_captures/20261022_191213_CG07AN8902_2_vehicle.jpg",
            "cargo_file": "gate_captures/20261022_191213_CG07AN8902_3_cargo.jpg",
        },
        {
            "plate": "MH 12 AB 9988",
            "vehicle_type": VehicleType.TRUCK,
            "color": "white",
            "make": "Ashok Leyland",
            "model": "Ecomet 1215",
            "load_type": LoadType.BAMBOO,
            "load_conf": 0.92,
            "speed_kph": 8.5,
            "direction": "Ingress (Entry)",
            "plate_file": "gate_captures/20261023_003400_CG07CU8073_1_plate.jpg",
            "scene_file": "gate_captures/20261023_003400_CG07CU8073_2_vehicle.jpg",
            "cargo_file": "gate_captures/20261023_003400_CG07CU8073_3_cargo.jpg",
        },
        {
            "plate": "22 BH 9021 AA",
            "vehicle_type": VehicleType.CAR,
            "color": "silver",
            "make": "Toyota",
            "model": "Innova Crysta",
            "load_type": LoadType.EMPTY,
            "load_conf": 1.0,
            "speed_kph": 0.0,
            "direction": "Stationary (Gate)",
            "plate_file": "gate_captures/20261024_011018_CG07CU8073_1_plate.jpg",
            "scene_file": "gate_captures/20261024_011018_CG07CU8073_2_vehicle.jpg",
            "cargo_file": "gate_captures/20261024_011018_CG07CU8073_3_cargo.jpg",
        },
    ]

    profile = sample_profiles[_sim_cycle_index % len(sample_profiles)]
    _sim_cycle_index += 1

    payload = EventCreate(
        event_uid=f"sim-{uuid.uuid4()}",
        camera_id="cam_a_anpr_4k",
        captured_at=datetime.now(timezone.utc),
        plate_raw=profile["plate"],
        plate_conf=1.00,
        vehicle_type=profile["vehicle_type"],
        vehicle_color=profile["color"],
        vehicle_make=profile["make"],
        vehicle_model=profile["model"],
        speed_kph=profile["speed_kph"],
        direction=profile["direction"],
        speed_reliability=1.0,
        load_type=profile["load_type"],
        load_conf=profile["load_conf"],
    )

    detection, _ = await DetectionService.ingest_event(db, gate, payload)

    # Attach real evidence photographs if files exist on disk
    import os
    saved_media = False
    for kind, key_name in [(MediaKind.PLATE, "plate_file"), (MediaKind.SCENE, "scene_file"), (MediaKind.LOAD_THUMB, "cargo_file")]:
        fpath = profile.get(key_name)
        if fpath and os.path.exists(fpath):
            with open(fpath, "rb") as f:
                img_bytes = f.read()
            ext = os.path.splitext(fpath)[1] or ".jpg"
            object_key = f"detections/{detection.id}/{kind.value}{ext}"
            bytes_saved = await storage.save_file(object_key, img_bytes, "image/jpeg")
            media = Media(
                detection_id=detection.id,
                kind=kind,
                object_key=object_key,
                bytes=bytes_saved,
                created_at=datetime.now(timezone.utc),
            )
            db.add(media)
            saved_media = True

    if saved_media:
        detection.media_ready = True
        await db.commit()
        await db.refresh(detection)

    read_data = DetectionRead.model_validate(detection)

    # Real-time WebSocket broadcast (<1s)
    from app.services.websocket import broadcaster
    await broadcaster.broadcast("detection.created", read_data.model_dump(mode="json"))

    return read_data


@router.post(
    "/events/camera-push",
    response_model=DetectionRead,
    status_code=status.HTTP_200_OK,
    summary="Direct Smart Camera ANPR Ingestion (Hikvision / Dahua / Generic Smart ANPR)",
)
async def post_camera_push(
    request: Request,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
    storage: StorageDriver = Depends(get_storage),
):
    """
    Direct Webhook ingestion for Smart ANPR Cameras (Hikvision ISAPI, Dahua WizMind, Uniview, Generic).
    Parses XML, JSON, or multipart/form-data with attached JPEG snapshots.
    Zero PC required at the physical gate!
    """
    stmt = select(Gate).where(Gate.id == device.gate_id)
    result = await db.execute(stmt)
    gate = result.scalar_one()

    now = datetime.now(timezone.utc)
    content_type = request.headers.get("content-type", "")

    plate_raw = ""
    plate_conf = 0.95
    speed_kph = 0.0
    v_type = VehicleType.OTHER
    v_color = None
    plate_bytes = None
    scene_bytes = None

    if "multipart" in content_type or "form" in content_type:
        form = await request.form()
        for key, value in form.items():
            if isinstance(value, UploadFile):
                fname = (value.filename or "").lower()
                field = key.lower()
                data = await value.read()
                if "plate" in field or "plate" in fname:
                    plate_bytes = data
                elif "scene" in field or "vehicle" in field or "detection" in field or fname.endswith((".jpg", ".jpeg", ".png")):
                    scene_bytes = data
                elif fname.endswith(".xml") or "xml" in field:
                    try:
                        import xml.etree.ElementTree as ET
                        root = ET.fromstring(data.decode("utf-8", errors="ignore"))
                        for elem in root.iter():
                            tag = elem.tag.lower()
                            if ("licenseplate" in tag or "platenumber" in tag or "plate" in tag) and elem.text:
                                plate_raw = elem.text.strip()
                            elif "speed" in tag and elem.text:
                                try:
                                    speed_kph = float(elem.text.strip())
                                except ValueError:
                                    pass
                    except Exception:
                        pass
                elif fname.endswith(".json") or "json" in field:
                    try:
                        import json
                        j = json.loads(data.decode("utf-8", errors="ignore"))
                        for k in ("plate", "licensePlate", "PlateNumber", "plate_number"):
                            if k in j:
                                plate_raw = str(j[k]).strip()
                                break
                    except Exception:
                        pass
            elif isinstance(value, str):
                val_str = value.strip()
                if val_str.startswith("<"):
                    try:
                        import xml.etree.ElementTree as ET
                        root = ET.fromstring(val_str)
                        for elem in root.iter():
                            tag = elem.tag.lower()
                            if ("licenseplate" in tag or "platenumber" in tag or "plate" in tag) and elem.text:
                                plate_raw = elem.text.strip()
                            elif "speed" in tag and elem.text:
                                try:
                                    speed_kph = float(elem.text.strip())
                                except ValueError:
                                    pass
                    except Exception:
                        pass
                elif val_str.startswith("{"):
                    try:
                        import json
                        j = json.loads(val_str)
                        for k in ("plate", "licensePlate", "PlateNumber", "plate_number"):
                            if k in j:
                                plate_raw = str(j[k]).strip()
                                break
                    except Exception:
                        pass
    elif "json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                for k in ("plate", "licensePlate", "PlateNumber", "plate_raw", "plate_number"):
                    if k in body:
                        plate_raw = str(body[k]).strip()
                        break
                if "speed" in body:
                    try:
                        speed_kph = float(body["speed"])
                    except (ValueError, TypeError):
                        pass
                if "confidence" in body:
                    try:
                        plate_conf = float(body["confidence"])
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass

    if not plate_raw or not validate_plate(normalize_plate(plate_raw)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Valid license plate is required. Zero-assumption policy strictly rejects missing or unverified plates.",
        )

    event_uid = f"cam-{uuid.uuid4().hex[:12]}"
    payload = EventCreate(
        event_uid=event_uid,
        camera_id="smart-cam-a",
        captured_at=now,
        plate_raw=plate_raw,
        plate_conf=plate_conf,
        vehicle_type=v_type,
        vehicle_color=v_color,
        speed_kph=speed_kph,
        direction="Ingress (Entry)",
        speed_reliability=1.0,
    )

    detection, _ = await DetectionService.ingest_event(db, gate, payload)

    # Save media if attached
    saved_kinds = []
    if plate_bytes:
        obj_key = f"detections/{detection.id}/plate.jpg"
        bytes_saved = await storage.save_file(obj_key, plate_bytes, "image/jpeg")
        media = Media(
            detection_id=detection.id,
            kind=MediaKind.PLATE,
            object_key=obj_key,
            bytes=bytes_saved,
            created_at=now,
        )
        db.add(media)
        saved_kinds.append("plate")
    if scene_bytes:
        obj_key = f"detections/{detection.id}/scene.jpg"
        bytes_saved = await storage.save_file(obj_key, scene_bytes, "image/jpeg")
        media = Media(
            detection_id=detection.id,
            kind=MediaKind.SCENE,
            object_key=obj_key,
            bytes=bytes_saved,
            created_at=now,
        )
        db.add(media)
        saved_kinds.append("scene")

    if saved_kinds:
        detection.media_ready = True
        await db.commit()
        await db.refresh(detection)

    read_data = DetectionRead.model_validate(detection)
    from app.services.websocket import broadcaster
    await broadcaster.broadcast("detection.created", read_data.model_dump(mode="json"))

    return read_data


@router.put(
    "/detections/{detection_id}/media",
    status_code=status.HTTP_200_OK,
    summary="Stage 2 Edge Multipart Media Upload",
)
async def upload_detection_media(
    detection_id: uuid.UUID,
    plate: Optional[UploadFile] = File(None),
    scene: Optional[UploadFile] = File(None),
    load_thumb: Optional[UploadFile] = File(None),
    load_full: Optional[UploadFile] = File(None),
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
    storage: StorageDriver = Depends(get_storage),
):
    """
    Stage 2 multipart upload: plate, scene, load_thumb, load_full (any subset).
    Out-of-order safe: creates a placeholder if media arrives before stage 1 event.
    Stores files, sets media_ready=True, and emits detection update.
    """
    now = datetime.now(timezone.utc)
    stmt = select(Detection).where(Detection.id == detection_id)
    result = await db.execute(stmt)
    detection = result.scalar_one_or_none()

    if not detection:
        # Out-of-order safe placeholder
        detection = Detection(
            id=detection_id,
            event_uid=f"pending-{detection_id}",
            gate_id=device.gate_id,
            camera_id="cam-edge",
            captured_at=now,
            received_at=now,
            day_serial=0,
            plate_raw="PENDING",
            plate="PENDING",
            plate_valid=False,
            plate_conf=0.0,
            vehicle_type=VehicleType.OTHER,
            load_type=LoadType.UNKNOWN,
            load_conf=0.0,
            load_source=LoadSource.AUTO,
            status=DetectionStatus.NEEDS_REVIEW,
            media_ready=True,
            raw_event={"placeholder": True},
        )
        db.add(detection)
        await db.flush()

    files_to_process = [
        (plate, MediaKind.PLATE),
        (scene, MediaKind.SCENE),
        (load_thumb, MediaKind.LOAD_THUMB),
        (load_full, MediaKind.LOAD_FULL),
    ]

    saved_kinds: List[str] = []
    for upload_file, kind in files_to_process:
        if upload_file is not None:
            content = await upload_file.read()
            if content:
                filename = upload_file.filename or f"{kind.value}.jpg"
                object_key = f"detections/{detection_id}/{kind.value}_{filename}"
                content_type = upload_file.content_type or "image/jpeg"
                bytes_saved = await storage.save_file(object_key, content, content_type)

                # Upsert media record
                media_stmt = select(Media).where(
                    Media.detection_id == detection_id,
                    Media.kind == kind,
                )
                media_res = await db.execute(media_stmt)
                media_row = media_res.scalar_one_or_none()
                if media_row:
                    media_row.object_key = object_key
                    media_row.bytes = bytes_saved
                else:
                    media_row = Media(
                        detection_id=detection_id,
                        kind=kind,
                        object_key=object_key,
                        bytes=bytes_saved,
                        created_at=now,
                    )
                    db.add(media_row)
                saved_kinds.append(kind.value)

    detection.media_ready = True
    detection.updated_at = now
    await db.commit()
    await db.refresh(detection)

    # Broadcast media update
    from app.services.websocket import broadcaster
    await broadcaster.broadcast("detection.updated", {
        "id": str(detection_id),
        "media_ready": True,
        "saved_media": saved_kinds,
    })

    return {
        "detection_id": str(detection_id),
        "media_ready": True,
        "saved_media": saved_kinds,
    }


@router.patch(
    "/detections/{detection_id}/load",
    response_model=DetectionRead,
    summary="Late Load Classifier Result",
)
async def update_late_load(
    detection_id: uuid.UUID,
    payload: LateLoadUpdate,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """Late load classifier update (load_type, load_conf) from Camera B."""
    settings = get_settings()
    stmt = select(Detection).where(Detection.id == detection_id)
    result = await db.execute(stmt)
    detection = result.scalar_one_or_none()
    if not detection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detection not found")

    detection.load_type = payload.load_type
    detection.load_conf = payload.load_conf
    detection.status = compute_detection_status(
        plate_valid=detection.plate_valid,
        plate_conf=detection.plate_conf,
        load_conf=payload.load_conf,
        settings=settings,
    )
    detection.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(detection)

    read_data = DetectionRead.model_validate(detection)
    from app.services.websocket import broadcaster
    await broadcaster.broadcast("detection.updated", read_data.model_dump(mode="json"))

    return read_data

