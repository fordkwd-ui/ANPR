"""Daily counters for atomic, gap-free day_serial allocation."""
from datetime import date
from sqlalchemy import Date, ForeignKey, Integer, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class DailyCounter(Base):
    __tablename__ = "daily_counters"

    gate_id: Mapped[int] = mapped_column(Integer, ForeignKey("gates.id", ondelete="CASCADE"), nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("gate_id", "local_date", name="pk_daily_counters"),
    )
