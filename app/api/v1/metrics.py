"""Latency instrumentation metrics endpoint."""
from fastapi import APIRouter
from app.core.latency import latency_tracker

router = APIRouter(tags=["Metrics & Diagnostics"])


@router.get("/metrics/latency")
async def get_latency_metrics():
    """
    Exposes p50 and p95 latencies over the last 1 hour:
    - (received_at - captured_at) ingestion network + server transit
    - (ws_sent_at - captured_at) end-to-end edge-to-dashboard transit
    """
    return latency_tracker.get_metrics()
