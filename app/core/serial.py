"""Atomic gap-free day_serial allocator."""
from datetime import date, datetime, timezone
import zoneinfo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def get_gate_local_date(dt: datetime, tz_name: str = "Asia/Kolkata") -> date:
    """Converts a UTC datetime to local date in gate's timezone."""
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = zoneinfo.ZoneInfo("Asia/Kolkata")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).date()


async def allocate_day_serial(
    db: AsyncSession,
    gate_id: int,
    captured_at: datetime,
    timezone_str: str = "Asia/Kolkata",
) -> int:
    """
    Atomically increments and returns the sequential day_serial for the gate's local date.
    Guarantees gap-free and unique serials under high concurrency using atomic upsert with RETURNING.
    """
    local_date = get_gate_local_date(captured_at, timezone_str)

    stmt = text(
        """
        INSERT INTO daily_counters (gate_id, local_date, last_no)
        VALUES (:gate_id, :local_date, 1)
        ON CONFLICT (gate_id, local_date)
        DO UPDATE SET last_no = daily_counters.last_no + 1
        RETURNING last_no;
        """
    )
    result = await db.execute(stmt, {"gate_id": gate_id, "local_date": local_date})
    serial = result.scalar_one()
    return int(serial)
