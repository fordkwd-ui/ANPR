"""
Automated validation suite for:
1. Rear motorcycle two-line plate OCR assembly (CG.07 / AN.8902 -> CG07AN8902)
2. Accurate two-wheeler classification (Honda Activa, Hero Splendor, Two-Wheeler) suppressing car models (Jeep Wrangler)
3. Zero-speed lock for stationary vehicles stopped at gate (0.0 km/h)
4. Vehicle body color sampling avoiding white license plate bias
"""
import numpy as np
import pytest
from app.core.tracker import HighSpeedVehicleTracker
from edge.vehicle_tracker_adapter import (
    VehicleDirectionAndSpeedTracker,
    VehicleFeatureExtractor,
)
from scripts.edge_camera_gateway import (
    BH_SERIES_REGEX,
    STANDARD_PLATE_REGEX,
    fix_plate_chars,
)


def test_rear_motorcycle_two_line_plate_assembly():
    """Verify that stacked 2-line Indian rear motorcycle plates assemble correctly."""
    # Line 1: CG.07 or CG 07
    # Line 2: AN.8902 or AN 8902
    line1 = "CG.07"
    line2 = "AN.8902"
    combo = fix_plate_chars((line1 + line2).replace(".", "").replace(" ", "").upper())
    assert combo == "CG07AN8902"
    assert STANDARD_PLATE_REGEX.match(combo) is not None

    # Three-line plate: CG 07 / CU / 8073
    l1, l2, l3 = "CG 07", "CU", "8073"
    combo_3 = fix_plate_chars((l1 + l2 + l3).replace(" ", "").upper())
    assert combo_3 == "CG07CU8073"
    assert STANDARD_PLATE_REGEX.match(combo_3) is not None


def test_two_wheeler_make_model_suppresses_car_mmr():
    """Ensure two-wheelers are never classified as passenger cars like Jeep Wrangler."""
    extractor = VehicleFeatureExtractor.get_instance()
    dummy_crop = np.zeros((200, 150, 3), dtype=np.uint8)  # Vertical aspect ratio

    # Case 1: Honda Activa scooter with HONDA or ACTIVA text detected on cowl
    res_honda = extractor.classify_make_model(
        vehicle_crop=dummy_crop,
        vehicle_class="motorcycle",
        observed_texts=["HONDA", "CAMA", "ACTIVE"],
    )
    assert res_honda["make"] == "Honda"
    assert "Activa" in res_honda["model"]
    assert "Jeep" not in res_honda["make"]

    # Case 2: Hero motorcycle with HERO badge
    res_hero = extractor.classify_make_model(
        vehicle_crop=dummy_crop,
        vehicle_class="motorcycle",
        observed_texts=["HERO", "SPLENDOR"],
    )
    assert res_hero["make"] == "Hero"
    assert "Splendor" in res_hero["model"]

    # Case 3: Generic two-wheeler without brand text
    res_generic = extractor.classify_make_model(
        vehicle_crop=dummy_crop,
        vehicle_class="motorcycle",
        observed_texts=[],
    )
    assert "Two-Wheeler" in res_generic["model"] or "Motorcycle" in res_generic["make"]
    assert res_generic["make"] != "Jeep"


def test_stationary_vehicle_speed_lock_zero():
    """Verify that vehicles stopped at the gate are locked to exactly 0.0 km/h."""
    tracker = HighSpeedVehicleTracker(trap_distance_meters=6.0)
    dummy_frame = np.ones((720, 1280, 3), dtype=np.uint8) * 128

    # Vehicle stopped in sweet spot (pixel jitter < 20px over 1.0 second)
    t = 100.0
    tracks = []
    for i in range(10):
        # Center around (600, 360) with minor sensor noise
        x1 = 500 + (i % 2) * 2
        y1 = 300 + (i % 3) * 2
        tracks = tracker.update([(x1, y1, x1 + 200, y1 + 120)], frame=dummy_frame, now=t + i * 0.1)

    assert len(tracks) == 1
    tr = tracks[0]
    assert tr["is_stopped"] is True
    assert tr["speed_kmh"] == 0.0
    assert tr["motion_state"] == "STOPPED"
    assert tr["direction"] == "Stationary (Gate)"


def test_vehicle_body_color_sampling():
    """Ensure black vehicle body color is not overwhelmed by white license plate."""
    extractor = VehicleFeatureExtractor.get_instance()
    # Create black vehicle body (dark pixels) with small white strip at bottom
    crop = np.zeros((200, 200, 3), dtype=np.uint8) + 25  # Dark black body
    crop[160:190, 60:140] = 250  # White plate at bottom

    res = extractor.classify_color(crop)
    assert res["color"] in ("Black", "Grey")
    assert res["color"] != "White"


def test_indian_plate_positional_syntax_corrections():
    """Verify that optical confusion in state, RTO, series, and serial positions is corrected."""
    from app.core.plate import fix_optical_plate_confusion, validate_plate

    # 1. Z -> 7 when preceded by 0 in CG 0X plates (user test vehicle: CG07CU8073)
    assert fix_optical_plate_confusion("CG0ZCU8073") == "CG07CU8073"
    assert validate_plate("CG07CU8073") is True

    # 2. State code optical confusion: C6 -> CG, D1 -> DL, K4 -> KA, M8 -> MH
    assert fix_optical_plate_confusion("C607AN8902") == "CG07AN8902"
    assert fix_optical_plate_confusion("D101AB1234") == "DL01AB1234"
    assert fix_optical_plate_confusion("K405MN4821") == "KA05MN4821"

    # 3. Series letter digit confusion: 4 -> A, 0/O -> U (in CMVR Rule 50, O/I are prohibited)
    assert fix_optical_plate_confusion("CG074N8902") == "CG07AN8902"
    assert fix_optical_plate_confusion("CG07CO8073") == "CG07CU8073"

    # 4. Serial number letter confusion: O -> 0, Z -> 2, S -> 5, B -> 8
    assert fix_optical_plate_confusion("CG07AN89OZ") == "CG07AN8902"
    assert fix_optical_plate_confusion("CG07CU807S") == "CG07CU8075"


def test_multi_frame_fragment_consensus():
    """Verify that multi-frame fragments (CG.07 in frame 1, AN.8902 in frame 2) fuse cleanly."""
    from app.core.tracker import PlateConsensusAggregator

    agg = PlateConsensusAggregator()
    # Frame 1 sees top line
    agg.add_fragment("CG.07", confidence=0.88)
    # Frame 2 sees bottom line
    agg.add_fragment("AN.8902", confidence=0.92)

    best = agg.get_best(require_valid=True)
    assert best is not None
    assert best["normalized"] == "CG07AN8902"
    assert best["is_valid"] is True


def test_real_camera_screenshot_ocr_accuracy():
    """Verify that live camera screenshot with Activa scooter produces CG07CU8073 with 100% confidence."""
    import os
    import cv2
    from scripts.edge_camera_gateway import run_real_anpr_ocr

    img_path = "/Users/mohitbaghel/.gemini/antigravity-ide/brain/f736b4ca-55e0-414c-bc71-b8780d2655a0/.user_uploaded/media_1792676770002.png"
    if not os.path.exists(img_path):
        pytest.skip("Test image not present")

    full_screenshot = cv2.imread(img_path)
    # Extract camera monitor viewport
    cam_viewport = full_screenshot[35:340, 0:512]

    plate, conf, crop_bytes, bbox, all_texts, is_two_wheeler = run_real_anpr_ocr(cam_viewport)
    assert plate == "CG07CU8073"
    assert conf >= 0.95
    assert is_two_wheeler is True
    assert bbox is not None

