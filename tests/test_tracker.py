"""Unit tests for High-Speed 60 km/h ANPR Tracking, Velocity, and Sharpness Engine."""
import numpy as np
import pytest
import cv2

from app.core.tracker import (
    HighSpeedVehicleTracker,
    PlateConsensusAggregator,
    calculate_sharpness,
    fix_optical_plate_confusion,
)


def test_optical_plate_confusion_fixes():
    """Verifies that common OCR optical confusion characters are corrected based on Indian RTO syntax."""
    # Letter O in RTO code position 2 should become digit 0
    assert fix_optical_plate_confusion("DLO1AB1234") == "DL01AB1234"

    # Positions 0 and 1 must be valid state letters (0L resolves to Delhi DL)
    assert fix_optical_plate_confusion("0L01AB1234") == "DL01AB1234"

    # Letter S in digit position 2 should become digit 5
    assert fix_optical_plate_confusion("KAS5MN4821") == "KA55MN4821"

    # Digit in last 4 positions
    assert fix_optical_plate_confusion("DL01AB123O") == "DL01AB1230"
    assert fix_optical_plate_confusion("KA05MN482I") == "KA05MN4821"

    # Bharat (BH) series
    assert fix_optical_plate_confusion("22BH1234AA") == "22BH1234AA"
    assert fix_optical_plate_confusion("22BH1234A") == "22BH1234A"


def test_sharpness_discrimination():
    """Verifies that Laplacian variance accurately distinguishes crisp vs motion-blurred frames."""
    # Create sharp image with high-contrast text and edge step transitions
    sharp_img = np.zeros((200, 400, 3), dtype=np.uint8)
    for x in range(20, 380, 20):
        cv2.line(sharp_img, (x, 10), (x, 190), (255, 255, 255), 3)
    cv2.putText(sharp_img, "KA05MN4821", (40, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)

    # Create motion-blurred version of the same image (horizontal blur simulating 60 km/h motion)
    kernel_size = 25
    kernel_motion = np.zeros((kernel_size, kernel_size))
    kernel_motion[int((kernel_size - 1) / 2), :] = np.ones(kernel_size)
    kernel_motion = kernel_motion / kernel_size
    blurred_img = cv2.filter2D(sharp_img, -1, kernel_motion)

    sharp_score = calculate_sharpness(sharp_img)
    blurred_score = calculate_sharpness(blurred_img)

    assert sharp_score > blurred_score * 3.0, f"Sharp ({sharp_score}) should be much higher than blurred ({blurred_score})"
    assert sharp_score > 100.0


def test_speed_estimation_at_60_kmh():
    """Verifies accurate speed calculation at 60 km/h across calibrated trap distance."""
    tracker = HighSpeedVehicleTracker(trap_distance_meters=6.0)

    # At 60 km/h: v = 16.6667 m/s -> transit of 6m takes exactly 0.36 seconds
    t_enter = 1000.0
    t_exit = 1000.36
    speed = tracker.estimate_speed(t_enter, t_exit)
    assert speed is not None
    assert 59.5 <= speed <= 60.5, f"Expected ~60.0 km/h, got {speed}"

    # At 40 km/h: v = 11.111 m/s -> transit of 6m takes 0.54 seconds
    speed_40 = tracker.estimate_speed(1000.0, 1000.54)
    assert speed_40 is not None
    assert 39.5 <= speed_40 <= 40.5, f"Expected ~40.0 km/h, got {speed_40}"


def test_tracker_vehicle_lifecycle_and_sweet_spot():
    """Simulates a vehicle approaching, entering the sweet-spot, and exiting at high speed."""
    tracker = HighSpeedVehicleTracker(
        trap_distance_meters=6.0,
        sweet_spot_y_start=0.30,
        sweet_spot_y_end=0.75,
    )

    dummy_frame = np.ones((720, 1280, 3), dtype=np.uint8) * 128
    cv2.rectangle(dummy_frame, (500, 300), (700, 400), (255, 255, 255), 2)

    # Frame 1: Vehicle far (y=150, 20% down -> approaching, outside sweet spot)
    t0 = 100.0
    tracks = tracker.update([(540, 130, 660, 170)], frame=dummy_frame, now=t0)
    assert len(tracks) == 1
    assert tracks[0]["in_sweet_spot"] is False
    assert len(tracker.get_triggerable_tracks()) == 0

    # Frame 2: Vehicle enters Sweet Spot (y=350, 48% down)
    t1 = 100.15
    tracks = tracker.update([(530, 320, 670, 380)], frame=dummy_frame, now=t1)
    assert len(tracks) == 1
    assert tracks[0]["in_sweet_spot"] is True

    # Check that track is now triggerable for sweet-spot OCR
    triggerable = tracker.get_triggerable_tracks()
    assert len(triggerable) == 1
    assert triggerable[0]["track_id"] == tracks[0]["track_id"]

    # Frame 3: Vehicle exits Sweet Spot (y=600, 83% down)
    t2 = 100.36
    tracks = tracker.update([(510, 560, 690, 640)], frame=dummy_frame, now=t2)
    assert len(tracks) == 1
    # Speed should now be computed from t_enter to t_exit
    assert tracks[0]["speed_kmh"] is not None
    assert tracks[0]["speed_kmh"] > 40.0


def test_rapid_succession_vehicles_no_lockout():
    """
    Verifies that when Car 2 follows Car 1 closely (1.2 seconds behind at 60 km/h),
    Car 2 is tracked and triggered immediately without being blocked by Car 1's passage.
    """
    tracker = HighSpeedVehicleTracker(trap_distance_meters=6.0)
    dummy_frame = np.ones((720, 1280, 3), dtype=np.uint8) * 128

    # Vehicle 1 enters and completes
    tracker.update([(540, 150, 660, 200)], frame=dummy_frame, now=10.0)
    tracker.update([(530, 350, 670, 420)], frame=dummy_frame, now=10.18)
    v1_triggers = tracker.get_triggerable_tracks()
    assert len(v1_triggers) == 1
    assert v1_triggers[0]["track_id"] == 1

    # Vehicle 1 exits
    tracker.update([(510, 600, 690, 680)], frame=dummy_frame, now=10.36)

    # Vehicle 2 approaches only 1.2 seconds later!
    t_v2_start = 11.5
    tracker.update([(540, 150, 660, 200)], frame=dummy_frame, now=t_v2_start)
    tracker.update([(530, 360, 670, 430)], frame=dummy_frame, now=t_v2_start + 0.18)

    v2_triggers = tracker.get_triggerable_tracks()
    assert len(v2_triggers) == 1
    assert v2_triggers[0]["track_id"] == 2, "Vehicle 2 must trigger cleanly without lockout"



def test_plate_consensus_aggregator():
    """Verifies that multi-frame candidates are aggregated and validated properly."""
    agg = PlateConsensusAggregator()

    # Add noisy fragments from blurred frames
    agg.add_candidate("DL01", confidence=0.70)
    agg.add_candidate("01AB", confidence=0.75)

    # Add complete valid plate from sharp sweet-spot frame
    agg.add_candidate("DL 01 AB 1234", confidence=0.93)

    best = agg.get_best()
    assert best is not None
    assert best["normalized"] == "DL01AB1234"
    assert best["is_valid"] is True
