"""Health and heartbeat telemetry model."""
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Health(Base):
    __tablename__ = "health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    camera_a_ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    camera_b_ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    disk_used_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    queue_depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ups_on_battery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    device: Mapped["Device"] = relationship("Device")
