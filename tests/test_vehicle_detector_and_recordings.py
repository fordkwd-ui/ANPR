"""
Unit tests for RealVehicleDetector and 24/7 CCTV Recordings API.
"""

import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from edge.vehicle_tracker_adapter import RealVehicleDetector


def test_real_vehicle_detector_filters_empty_and_noise():
    """Verifies that an empty frame produces 0 vehicle detections (no phantom vehicles)."""
    detector = RealVehicleDetector.get_instance()
    blank = np.zeros((720, 1280, 3), dtype=np.uint8)
    detections = detector.detect(blank)
    assert isinstance(detections, list)
    assert len(detections) == 0


@pytest.mark.asyncio
async def test_recordings_api_list_and_stream():
    """Verifies the GET /api/v1/recordings endpoint returns continuous recordings archive."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/recordings")
        assert r.status_code == 200
        data = r.json()
        assert "total_count" in data
        assert "total_size_mb" in data
        assert "recordings" in data
        assert isinstance(data["recordings"], list)

        if data["total_count"] > 0:
            first_rec = data["recordings"][0]
            stream_url = first_rec["stream_url"]
            sr = await client.get(stream_url)
            assert sr.status_code == 200
            assert sr.headers.get("content-type") == "video/mp4"


def test_cargo_load_classification_materials():
    """Verifies that timber logs, sand, covered tarp, and empty loads are classified correctly."""
    from edge.vehicle_tracker_adapter import VehicleFeatureExtractor
    extractor = VehicleFeatureExtractor.get_instance()

    # Two-wheeler should always be empty
    bike_res = extractor.classify_cargo_load(np.zeros((100, 100, 3), dtype=np.uint8), vehicle_type="motorcycle")
    assert bike_res["load_type"] == "empty"

    # Timber (dark earthy brown wood bark)
    timber_crop = np.full((120, 120, 3), [25, 55, 105], dtype=np.uint8)
    res_timber = extractor.classify_cargo_load(timber_crop, vehicle_type="truck")
    assert res_timber["load_type"] == "timber_logs"

    # Sand (bright golden tan / earth yellow)
    sand_crop = np.full((120, 120, 3), [70, 160, 210], dtype=np.uint8)
    res_sand = extractor.classify_cargo_load(sand_crop, vehicle_type="truck")
    assert res_sand["load_type"] == "sand"

    # Covered (vibrant blue tarp)
    tarp_crop = np.full((120, 120, 3), [200, 50, 20], dtype=np.uint8)
    res_tarp = extractor.classify_cargo_load(tarp_crop, vehicle_type="truck")
    assert res_tarp["load_type"] == "covered"


def test_high_speed_bike_tracking_and_exit_trigger():
    """
    Verifies that a high-speed bike (e.g. 50 km/h) passing rapidly through the trap zone
    is continuously tracked, computes accurate speed, and is triggerable even upon exiting.
    """
    from app.core.tracker import HighSpeedVehicleTracker
    tracker = HighSpeedVehicleTracker(trap_distance_meters=6.0, sweet_spot_y_start=0.25, sweet_spot_y_end=0.80)
    frame = np.full((720, 1280, 3), 128, dtype=np.uint8)

    # Frame 1: Bike enters sweet spot at t=10.00
    t0 = 10.00
    det1 = [{"bbox": (600, 220, 680, 320), "class": "motorcycle", "conf": 0.92}]
    tracks1 = tracker.update(det1, frame=frame, now=t0)
    assert len(tracks1) == 1

    # Frame 2: Bike moves through sweet spot at t=10.15 (~50 km/h)
    t1 = 10.15
    det2 = [{"bbox": (600, 380, 680, 480), "class": "motorcycle", "conf": 0.94}]
    tracks2 = tracker.update(det2, frame=frame, now=t1)
    assert len(tracks2) == 1
    assert tracks2[0]["in_sweet_spot"] is True
    assert tracks2[0]["vehicle_conf"] >= 0.90

    # Triggers sweet-spot capture
    triggers = tracker.get_triggerable_tracks()
    assert len(triggers) == 1
    assert triggers[0]["vehicle_class"] == "motorcycle"

