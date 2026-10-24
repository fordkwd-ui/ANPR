"""Today's dashboard summary statistics."""
from datetime import datetime, timezone
from typing import Optional
import zoneinfo
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.detection import Detection, DetectionStatus, LoadType, VehicleType
from app.models.gate import Gate
from app.models.user import User

router = APIRouter(tags=["Statistics"])


@router.get("/stats/today")
async def get_stats_today(
    gate_id: Optional[int] = Query(None, description="Optional gate ID filter"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns today's aggregate counts (vehicles, trucks, loaded, needs_review)
    calculated for the gate's local day.
    """
    settings = get_settings()
    tz_str = settings.DEFAULT_TIMEZONE

    # If gate_id specified, retrieve its timezone
    if gate_id:
        gate_res = await db.execute(select(Gate).where(Gate.id == gate_id))
        gate = gate_res.scalar_one_or_none()
        if gate:
            tz_str = gate.timezone

    tz = zoneinfo.ZoneInfo(tz_str)
    now_local = datetime.now(tz)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_local.astimezone(timezone.utc)

    base_filter = [Detection.captured_at >= today_start_utc]
    if gate_id:
        base_filter.append(Detection.gate_id == gate_id)

    # Vehicles count
    vehicles_stmt = select(func.count()).select_from(Detection).where(*base_filter)
    vehicles = (await db.execute(vehicles_stmt)).scalar() or 0

    # Trucks count
    trucks_stmt = (
        select(func.count())
        .select_from(Detection)
        .where(*base_filter, Detection.vehicle_type == VehicleType.TRUCK)
    )
    trucks = (await db.execute(trucks_stmt)).scalar() or 0

    # Loaded count (not empty and not unknown)
    loaded_stmt = (
        select(func.count())
        .select_from(Detection)
        .where(
            *base_filter,
            Detection.load_type.notin_([LoadType.EMPTY, LoadType.UNKNOWN]),
        )
    )
    loaded = (await db.execute(loaded_stmt)).scalar() or 0

    # Needs review count
    needs_review_stmt = (
        select(func.count())
        .select_from(Detection)
        .where(*base_filter, Detection.status == DetectionStatus.NEEDS_REVIEW)
    )
    needs_review = (await db.execute(needs_review_stmt)).scalar() or 0

    return {
        "vehicles": vehicles,
        "trucks": trucks,
        "loaded": loaded,
        "needs_review": needs_review,
        "date": today_start_local.date().isoformat(),
        "timezone": tz_str,
    }
