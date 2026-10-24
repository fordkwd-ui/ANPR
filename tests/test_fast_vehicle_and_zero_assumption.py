"""
Test suite for Fast-Moving Vehicle Tracking, Calibrated Velocity,
Strict Indian State/UT Verification, and Zero-Assumption Protection.
"""
import numpy as np
import pytest
import cv2

from app.core.tracker import (
    HighSpeedVehicleTracker,
    calculate_sharpness,
)
from app.core.plate import (
    VALID_INDIAN_STATE_CODES,
    normalize_plate,
    validate_plate,
    fix_optical_plate_confusion,
)
from edge.vehicle_tracker_adapter import VehicleFeatureExtractor


def test_strict_indian_state_plate_validation():
    """Verify that plates are strictly validated against genuine Indian States/UTs and BH series."""
    # Valid Indian States
    assert validate_plate("CG07CU8073") is True
    assert validate_plate("CG07AN8902") is True
    assert validate_plate("DL01AB1234") is True
    assert validate_plate("MH12CD5678") is True
    assert validate_plate("KA05MN4821") is True
    assert validate_plate("UP32AA1111") is True
    assert validate_plate("MP09ZZ9999") is True

    # Valid Bharat (BH) series
    assert validate_plate("22BH1234AA") is True
    assert validate_plate("24BH9876B") is True

    # Invalid fake state codes must be REJECTED (Zero Assumptions)
    assert validate_plate("XX01AB1234") is False
    assert validate_plate("ZZ99ZZ9999") is False
    assert validate_plate("WD12AB1234") is False
    assert validate_plate("QX05CD1234") is False
    assert validate_plate("NO_PLATE_VISIBLE") is False
    assert validate_plate("") is False


def test_fast_moving_vehicle_speed_and_tracking():
    """
    Simulates a vehicle moving at high speed (~50 km/h) through the camera field of view.
    Verifies that speed is accurately calculated and NOT locked to 0.0 km/h.
    """
    tracker = HighSpeedVehicleTracker(
        trap_distance_meters=6.0,
        sweet_spot_y_start=0.30,
        sweet_spot_y_end=0.75,
    )
    frame = np.ones((720, 1280, 3), dtype=np.uint8) * 128

    # Frame 1: Vehicle entering at y=200 (norm_cy = 0.278)
    t0 = 1000.0
    tracks = tracker.update([(540, 160, 660, 240)], frame=frame, now=t0)
    assert len(tracks) == 1
    assert tracks[0]["in_sweet_spot"] is False

    # Frame 2: Vehicle at y=360 (norm_cy = 0.50), dt = 0.12s
    # In 0.12s, vehicle traversed 160 pixels in a 324px 6m trap zone (~50 km/h)
    t1 = t0 + 0.12
    tracks = tracker.update([(530, 310, 670, 410)], frame=frame, now=t1)
    assert len(tracks) == 1
    tr = tracks[0]
    assert tr["in_sweet_spot"] is True
    assert tr["is_stopped"] is False
    assert tr["motion_state"] == "MOVING"
    assert tr["speed_kmh"] > 30.0, f"Speed should be non-zero for fast vehicle, got {tr['speed_kmh']}"
    assert "Ingress" in tr["direction"]

    # Check that track triggers with true non-zero speed
    triggerable = tracker.get_triggerable_tracks()
    assert len(triggerable) == 1
    assert triggerable[0]["speed_kmh"] > 30.0

    # Frame 3: Vehicle exits sweet spot at y=580 (norm_cy = 0.806), dt = 0.28s total
    t2 = t0 + 0.28
    tracks = tracker.update([(520, 520, 680, 640)], frame=frame, now=t2)
    assert len(tracks) == 1
    assert tracks[0]["exited"] is True
    assert tracks[0]["speed_kmh"] > 40.0


def test_exotic_supercar_suppression_and_zero_assumptions():
    """
    Verifies that the MMR classifier NEVER hallucinates exotic hypercars
    like McLaren F1, Ferrari, or Lamborghini on standard road traffic.
    """
    extractor = VehicleFeatureExtractor.get_instance()
    dummy_crop = np.zeros((150, 150, 3), dtype=np.uint8)

    # Classification without brand text should produce realistic category, never exotic supercar
    res = extractor.classify_make_model(dummy_crop, vehicle_class="car")
    assert res["make"].lower() not in ("mclaren", "ferrari", "lamborghini", "bugatti", "koenigsegg")

    # Classification with Indian brand text should identify the brand accurately
    res_tata = extractor.classify_make_model(dummy_crop, vehicle_class="car", observed_texts=["TATA", "NEXON"])
    assert res_tata["make"] == "Tata"

    res_maruti = extractor.classify_make_model(dummy_crop, vehicle_class="car", observed_texts=["SWIFT", "MARUTI"])
    assert res_maruti["make"] == "Maruti Suzuki"


def test_sharpest_observation_selection():
    """
    Verifies that Laplacian variance correctly ranks blurry vs crisp images
    to guarantee 'perfect pictures' capture.
    """
    # Create sharp image with edges
    sharp_img = np.zeros((200, 400, 3), dtype=np.uint8)
    cv2.putText(sharp_img, "CG07CU8073", (30, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
    cv2.rectangle(sharp_img, (20, 20), (380, 180), (255, 255, 255), 2)

    # Create blurred image with Gaussian blur
    blurred_img = cv2.GaussianBlur(sharp_img, (15, 15), 0)

    sharp_val = calculate_sharpness(sharp_img)
    blur_val = calculate_sharpness(blurred_img)

    assert sharp_val > blur_val * 2.0


def test_is_same_vehicle_plate_similarity_debounce():
    """
    Verifies that optical OCR fluctuations (such as dropped series letter C from CU)
    are recognized as the exact same physical vehicle to prevent duplicate passes.
    """
    from scripts.edge_camera_gateway import is_same_vehicle_plate

    # Optical drop of 'C' from 'CU' on CG07...8073
    assert is_same_vehicle_plate("CG07CU8073", "CG07U8073") is True
    assert is_same_vehicle_plate("CG07U8073", "CG07CU8073") is True

    # Identical plates
    assert is_same_vehicle_plate("CG07CU8073", "CG07CU8073") is True

    # Different vehicles must NOT match
    assert is_same_vehicle_plate("CG07CU8073", "CG07AN8902") is False
    assert is_same_vehicle_plate("DL01AB1234", "MH12CD5678") is False


def test_passenger_vehicle_cargo_suppression():
    """
    Ensures that for motorcycles, scooters, and passenger cars on single-camera setups,
    fake cargo crops from the background room are NEVER generated.
    """
    from scripts.edge_camera_gateway import extract_evidence_crops

    dummy_frame = np.ones((720, 1280, 3), dtype=np.uint8) * 128

    # Passenger vehicle (motorcycle / car) without Camera B: load_bytes must be EMPTY
    p_bytes, s_bytes, l_bytes = extract_evidence_crops(dummy_frame, is_commercial_cargo=False)
    assert len(p_bytes) > 0
    assert len(s_bytes) > 0
    assert len(l_bytes) == 0, "Passenger vehicle without cargo camera must NOT generate fake cargo photo"

    # Commercial cargo carrier (truck / pickup) on Camera A
    p2, s2, l2 = extract_evidence_crops(dummy_frame, is_commercial_cargo=True)
    assert len(l2) > 0, "Commercial cargo carrier must generate load inspection crop"


def test_stopped_vehicle_jitter_speed_lock_zero():
    """
    Verifies that when a vehicle is stopped at the gate with camera or detector jitter (<45px),
    its speed is strictly locked to 0.0 km/h and NOT reported as 20 km/h.
    """
    tracker = HighSpeedVehicleTracker(trap_distance_meters=6.0)
    frame = np.ones((720, 1280, 3), dtype=np.uint8) * 128

    t = 1000.0
    tracks = []
    # 5 frames over 0.25 seconds with 20px bounding box jitter
    for i in range(5):
        jitter_x = 500 + (i % 2) * 15
        jitter_y = 300 + (i % 3) * 10
        tracks = tracker.update([(jitter_x, jitter_y, jitter_x + 180, jitter_y + 120)], frame=frame, now=t + i * 0.05)

    assert len(tracks) == 1
    tr = tracks[0]
    assert tr["is_stopped"] is True
    assert tr["speed_kmh"] == 0.0, f"Stationary vehicle with jitter must be 0.0 km/h, got {tr['speed_kmh']}"
    assert tr["motion_state"] == "STOPPED"
    assert tr["direction"] == "Stationary (Gate)"


def test_multi_vehicle_simultaneous_detection_and_tracking():
    """
    Verifies that multiple vehicles traversing the road simultaneously (e.g. Lane 1 and Lane 2,
    or closely following/traveling in the same area at the same time) are tracked concurrently
    with distinct track IDs and triggered independently without choking.
    """
    tracker = HighSpeedVehicleTracker(
        trap_distance_meters=6.0,
        sweet_spot_y_start=0.30,
        sweet_spot_y_end=0.75,
    )
    frame = np.ones((720, 1280, 3), dtype=np.uint8) * 128

    t0 = 2000.0
    # Frame 1: Two vehicles entering at the same time:
    # Vehicle A in Lane 1 (left: x=200..380, y=180..260)
    # Vehicle B in Lane 2 (right: x=750..930, y=180..260)
    det_f1 = [
        {"bbox": (200, 180, 380, 260), "class": "car", "conf": 0.92},
        {"bbox": (750, 180, 930, 260), "class": "truck", "conf": 0.89},
    ]
    tracks_f1 = tracker.update(det_f1, frame=frame, now=t0)
    assert len(tracks_f1) == 2, "Both vehicles must be tracked simultaneously"
    tid_a = tracks_f1[0]["track_id"]
    tid_b = tracks_f1[1]["track_id"]
    assert tid_a != tid_b, "Each concurrent vehicle must have a unique track ID"

    # Frame 2: Both vehicles advance into the sweet spot (y=360), dt = 0.15s
    t1 = t0 + 0.15
    det_f2 = [
        {"bbox": (205, 320, 385, 420), "class": "car", "conf": 0.94},
        {"bbox": (745, 320, 925, 420), "class": "truck", "conf": 0.91},
    ]
    tracks_f2 = tracker.update(det_f2, frame=frame, now=t1)
    assert len(tracks_f2) == 2

    # Check that both vehicles entered the sweet spot
    tr_a = next(tr for tr in tracks_f2 if tr["track_id"] == tid_a)
    tr_b = next(tr for tr in tracks_f2 if tr["track_id"] == tid_b)
    assert tr_a["in_sweet_spot"] is True
    assert tr_b["in_sweet_spot"] is True
    assert tr_a["speed_kmh"] > 25.0
    assert tr_b["speed_kmh"] > 25.0

    # Both vehicles should trigger for ANPR OCR capture simultaneously
    triggerable = tracker.get_triggerable_tracks()
    assert len(triggerable) == 2, "Both simultaneous vehicles must be ready for ANPR OCR capture"
    trigger_ids = {tr["track_id"] for tr in triggerable}
    assert trigger_ids == {tid_a, tid_b}

