"""
Tests for VehicleDetectionTracker adapter, Spectrico Classifiers,
Direction & Speed calculation, and End-to-End API ingestion.
"""

import math
import numpy as np
import pytest
from httpx import AsyncClient

from edge.vehicle_tracker_adapter import (
    VehicleFeatureExtractor,
    VehicleDirectionAndSpeedTracker,
    AdvancedVehicleTrackerHUD,
)
from app.models.detection import Detection, VehicleType


def test_spectrico_classifiers_loaded():
    """Verify Spectrico Color and MMR models are loaded via OpenCV DNN."""
    extractor = VehicleFeatureExtractor.get_instance()
    assert extractor.color_classifier.loaded is True
    assert len(extractor.color_classifier.labels) > 0
    assert extractor.mmr_classifier.loaded is True
    assert len(extractor.mmr_classifier.labels) > 0


def test_spectrico_color_prediction():
    """Verify color classifier runs on image crop and returns top-3 colors."""
    extractor = VehicleFeatureExtractor.get_instance()
    # Create synthetic test image
    test_img = np.zeros((200, 200, 3), dtype=np.uint8)
    test_img[:, :] = (255, 255, 255)  # White

    res = extractor.classify_color(test_img)
    assert "color" in res
    assert "confidence" in res
    assert "top_3" in res
    assert len(res["top_3"]) > 0


def test_spectrico_mmr_prediction():
    """Verify MMR classifier runs on image crop and returns make and model."""
    extractor = VehicleFeatureExtractor.get_instance()
    test_img = np.zeros((150, 150, 3), dtype=np.uint8)

    res = extractor.classify_make_model(test_img)
    assert "make" in res
    assert "model" in res
    assert "confidence" in res
    assert isinstance(res["top_3"], list)


def test_direction_and_heading_mapping():
    """Test 8-compass direction calculation."""
    # Moving downwards (positive dy) -> Bottom
    rad, label = VehicleDirectionAndSpeedTracker.calculate_direction((100, 100), (100, 200))
    assert label == "Bottom"
    assert math.isclose(rad, math.pi / 2, rel_tol=1e-2)

    # Moving rightwards (positive dx) -> Right
    rad, label = VehicleDirectionAndSpeedTracker.calculate_direction((100, 100), (200, 100))
    assert label == "Right"
    assert math.isclose(rad, 0.0, abs_tol=1e-2)

    # Moving up and left (negative dx, negative dy) -> Top Left
    rad, label = VehicleDirectionAndSpeedTracker.calculate_direction((200, 200), (100, 100))
    assert label == "Top Left"


def test_speed_and_reliability():
    """Verify speed calculation with trap lines and reliability index."""
    positions = [(300, 100), (300, 150), (300, 220), (300, 300), (300, 380), (300, 460)]
    timestamps = [10.0, 10.1, 10.2, 10.3, 10.4, 10.5]
    res = VehicleDirectionAndSpeedTracker.calculate_speed_and_reliability(
        positions=positions,
        timestamps=timestamps,
        trap_distance_m=6.0,
        frame_height=720.0,
    )
    assert res["kph"] is not None
    assert 20.0 < res["kph"] < 120.0
    assert res["reliability"] == 0.7  # 6 points -> moderate reliability
    assert res["direction_label"] == "Bottom"


def test_hud_generation():
    """Test drawing operational HUD overlay on video frame."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    trail = [(320, 150), (320, 200), (320, 250)]
    annotated = AdvancedVehicleTrackerHUD.draw_hud(
        frame=frame,
        track_id=42,
        bbox=(320, 250, 180, 120),
        trail=trail,
        plate="KA05MN4821",
        make_model="Tata Prima",
        color_name="Yellow",
        speed_kph=48.5,
        direction_label="Bottom",
    )
    assert annotated.shape == frame.shape
    # Frame should have drawn pixels
    assert np.any(annotated > 0)
