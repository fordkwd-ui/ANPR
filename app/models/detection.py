"""Detection, Media, and Correction models."""
import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class VehicleType(str, enum.Enum):
    CAR = "car"
    VAN = "van"
    BUS = "bus"
    TRUCK = "truck"
    PICKUP = "pickup"
    SUV = "suv"
    MOTORCYCLE = "motorcycle"
    TRICYCLE = "tricycle"
    OTHER = "other"


class LoadType(str, enum.Enum):
    TIMBER_LOGS = "timber_logs"
    BAMBOO = "bamboo"
    SAND = "sand"
    STONE_GRAVEL = "stone_gravel"
    BAGS = "bags"
    EMPTY = "empty"
    COVERED = "covered"
    OTHER = "other"
    UNKNOWN = "unknown"


class LoadSource(str, enum.Enum):
    AUTO = "auto"
    MANUAL = "manual"


class DetectionStatus(str, enum.Enum):
    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"
    CORRECTED = "corrected"


class MediaKind(str, enum.Enum):
    PLATE = "plate"
    SCENE = "scene"
    LOAD_THUMB = "load_thumb"
    LOAD_FULL = "load_full"


class Detection(Base):
    __tablename__ = "detections"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    event_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    gate_id: Mapped[int] = mapped_column(Integer, ForeignKey("gates.id", ondelete="CASCADE"), nullable=False)
    camera_id: Mapped[str] = mapped_column(String(50), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    day_serial: Mapped[int] = mapped_column(Integer, nullable=False)

    plate_raw: Mapped[str] = mapped_column(String(64), nullable=False)
    plate: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    plate_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    plate_conf: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    vehicle_type: Mapped[VehicleType] = mapped_column(
        Enum(VehicleType, name="vehicle_type_enum", native_enum=False),
        default=VehicleType.OTHER,
        nullable=False,
    )
    vehicle_color: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    load_type: Mapped[LoadType] = mapped_column(
        Enum(LoadType, name="load_type_enum", native_enum=False),
        default=LoadType.UNKNOWN,
        nullable=False,
    )
    load_conf: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    load_source: Mapped[LoadSource] = mapped_column(
        Enum(LoadSource, name="load_source_enum", native_enum=False),
        default=LoadSource.AUTO,
        nullable=False,
    )

    status: Mapped[DetectionStatus] = mapped_column(
        Enum(DetectionStatus, name="detection_status_enum", native_enum=False),
        default=DetectionStatus.NEEDS_REVIEW,
        nullable=False,
    )
    media_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    clip_ref: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    raw_event: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    media: Mapped[List["Media"]] = relationship("Media", back_populates="detection", cascade="all, delete-orphan")
    corrections: Mapped[List["Correction"]] = relationship(
        "Correction", back_populates="detection", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_detections_veh_load", "vehicle_type", "load_type"),
    )

    @property
    def vehicle_make(self) -> Optional[str]:
        if self.raw_event and isinstance(self.raw_event, dict):
            return self.raw_event.get("vehicle_make")
        return None

    @property
    def vehicle_model(self) -> Optional[str]:
        if self.raw_event and isinstance(self.raw_event, dict):
            return self.raw_event.get("vehicle_model")
        return None

    @property
    def speed_kph(self) -> Optional[float]:
        if self.raw_event and isinstance(self.raw_event, dict):
            val = self.raw_event.get("speed_kph")
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
        return None

    @property
    def direction(self) -> Optional[str]:
        if self.raw_event and isinstance(self.raw_event, dict):
            return self.raw_event.get("direction")
        return None

    @property
    def thumbnails(self) -> Dict[str, str]:
        res = {}
        try:
            from sqlalchemy.orm import attributes
            loaded_media = attributes.instance_state(self).dict.get("media")
            if loaded_media:
                for m in loaded_media:
                    if getattr(m, "object_key", None):
                        k = m.kind.value if hasattr(m.kind, "value") else str(m.kind)
                        res[k] = f"/api/v1/media/{m.object_key.lstrip('/')}"
        except Exception:
            pass

        if self.id and getattr(self, "media_ready", False):
            if "plate" not in res:
                res["plate"] = f"/api/v1/media/detection/{self.id}/plate"
            if "scene" not in res:
                res["scene"] = f"/api/v1/media/detection/{self.id}/scene"
            if "load_thumb" not in res:
                res["load_thumb"] = f"/api/v1/media/detection/{self.id}/load_thumb"

        return res



class Media(Base):
    __tablename__ = "media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    detection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("detections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[MediaKind] = mapped_column(
        Enum(MediaKind, name="media_kind_enum", native_enum=False),
        nullable=False,
    )
    object_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    detection: Mapped["Detection"] = relationship("Detection", back_populates="media")


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    detection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("detections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    detection: Mapped["Detection"] = relationship("Detection", back_populates="corrections")
