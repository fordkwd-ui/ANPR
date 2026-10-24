"""API v1 master router."""
from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.detections import router as detections_router
from app.api.v1.events import router as events_router
from app.api.v1.health import router as health_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1.recordings import router as recordings_router
from app.api.v1.stats import router as stats_router
from app.api.v1.users import router as users_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(auth_router)
v1_router.include_router(users_router)
v1_router.include_router(events_router)
v1_router.include_router(health_router)
v1_router.include_router(stats_router)
v1_router.include_router(detections_router)
v1_router.include_router(metrics_router)
v1_router.include_router(recordings_router)
