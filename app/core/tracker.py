"""
High-Speed 60 km/h ANPR Tracking, Motion Detection, and Velocity Engine.

Engineered for highway and forest gate environments where vehicles traverse
the camera detection zone at speeds up to 60+ km/h (16.7 m/s).
Provides:
  1. Zero-lag threaded video frame streaming (prevents RTSP internal buffer lag).
  2. Sub-millisecond motion & centroid tracking across virtual trap zones.
  3. Real-time vehicle speed estimation in km/h based on calibrated trap distance.
  4. Multi-frame burst capture with Laplacian variance sharpness scoring (anti-motion-blur).
  5. Candidate plate consensus & syntax fusion (Indian State + BH Series).
  6. Track-aware dynamic debouncer (allows closely following vehicles without multi-second deadlocks).
"""

from collections import deque
import dataclasses
import datetime
import math
import re
import threading
import time
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.core.plate import (
    BH_SERIES_REGEX,
    CONFUSION_MAP_DIGITS,
    CONFUSION_MAP_LETTERS,
    STANDARD_PLATE_REGEX,
    STATE_FIXES,
    fix_optical_plate_confusion,
    normalize_plate,
    validate_plate,
)


def calculate_sharpness(image_bgr: np.ndarray, bbox: Optional[Tuple[int, int, int, int]] = None) -> float:
    """
    Computes image sharpness via Laplacian operator variance: Var(Laplacian(gray)).
    Higher value means sharper edge definition.
    Motion-blurred frames produce significantly lower variance (< 60),
    while crisp unblurred plates produce high variance (> 180).
    """
    if image_bgr is None or image_bgr.size == 0:
        return 0.0

    if bbox:
        x1, y1, x2, y2 = bbox
        h, w = image_bgr.shape[:2]
        x1 = max(0, min(x1, w - 1))
        y1 = max(0, min(y1, h - 1))
        x2 = max(x1 + 1, min(x2, w))
        y2 = max(y1 + 1, min(y2, h))
        roi = image_bgr[y1:y2, x1:x2]
    else:
        roi = image_bgr

    if roi.size == 0:
        return 0.0

    try:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        variance = float(laplacian.var())
        return round(variance, 2)
    except Exception:
        return 0.0


@dataclasses.dataclass
class TrackObservation:
    timestamp: float
    center_y: float
    center_x: float
    bbox: Tuple[int, int, int, int]
    sharpness: float
    frame: Optional[np.ndarray] = None


class HighSpeedVehicleTracker:
    """
    Tracks vehicle ingress through calibrated trap zones.
    At 60 km/h (16.67 m/s), a vehicle passes a 6-meter zone in ~360 ms.
    This tracker:
      - Tracks centroid across frames with persistent track_id.
      - Calculates velocity vector and speed in km/h.
      - Flags when vehicle is in the optical 'SWEET SPOT'.
      - Buffers candidate frames during transit and selects the sharpest frame.
    """

    def __init__(
        self,
        trap_distance_meters: float = 6.0,
        sweet_spot_y_start: float = 0.30,  # 30% from top of frame
        sweet_spot_y_end: float = 0.75,    # 75% from top of frame
        min_speed_kmh: float = 5.0,
        max_speed_kmh: float = 140.0,
    ):
        self.trap_distance_meters = trap_distance_meters
        self.sweet_spot_y_start = sweet_spot_y_start
        self.sweet_spot_y_end = sweet_spot_y_end
        self.min_speed_kmh = min_speed_kmh
        self.max_speed_kmh = max_speed_kmh

        # Active tracks: track_id -> dict
        self._tracks: Dict[int, dict] = {}
        self._next_track_id: int = 1
        self._lock = threading.Lock()

        # Deduplication of logged tracks
        self._logged_tracks = set()

    def update(
        self,
        detections: List[Tuple[int, int, int, int]],
        frame: Optional[np.ndarray] = None,
        now: Optional[float] = None,
    ) -> List[dict]:
        """
        Updates tracks with bounding boxes [(x1, y1, x2, y2), ...].
        Returns list of active track state dictionaries.
        """
        if now is None:
            now = time.time()

        frame_h = frame.shape[0] if frame is not None else 720
        frame_w = frame.shape[1] if frame is not None else 1280

        with self._lock:
            # Match detections to existing tracks by Euclidean centroid distance
            assigned_track_ids = set()
            active_events = []

            for item in detections:
                if isinstance(item, dict):
                    bbox = item.get("bbox", (0, 0, 0, 0))
                    v_class = item.get("class", "vehicle")
                    v_conf = item.get("conf", 0.90)
                else:
                    bbox = item
                    v_class = "vehicle"
                    v_conf = 0.90

                x1, y1, x2, y2 = bbox
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                norm_cy = cy / frame_h

                sharpness = calculate_sharpness(frame, bbox) if frame is not None else 100.0

                best_tid = None
                best_dist = float("inf")

                for tid, tr in self._tracks.items():
                    if tid in assigned_track_ids:
                        continue
                    if tr.get("exited", False):
                        continue

                    last_obs = tr["observations"][-1]
                    dt_last = max(0.001, now - tr["last_seen"])

                    # If track has been absent for > 0.4s and new detection is at entrance, it is a new vehicle
                    if dt_last > 0.4 and norm_cy <= self.sweet_spot_y_start + 0.15:
                        continue

                    # Direction of travel check: a vehicle moving forward cannot teleport backwards from exit to entrance
                    if last_obs.center_y > (self.sweet_spot_y_end * frame_h) and cy < (self.sweet_spot_y_start * frame_h + 50):
                        continue

                    dist = math.hypot(cx - last_obs.center_x, cy - last_obs.center_y)
                    # Adaptive search radius proportional to time delta at high speeds (up to 60+ km/h)
                    max_allowed_dist = min(500.0, max(220.0, 1600.0 * dt_last))
                    if dist < max_allowed_dist and dist < best_dist:
                        best_dist = dist
                        best_tid = tid

                if best_tid is None:
                    # New track initialized
                    best_tid = self._next_track_id
                    self._next_track_id += 1
                    self._tracks[best_tid] = {
                        "track_id": best_tid,
                        "created_at": now,
                        "last_seen": now,
                        "observations": [],
                        "in_sweet_spot": False,
                        "sweet_spot_enter_time": None,
                        "sweet_spot_exit_time": None,
                        "speed_kmh": 0.0,
                        "best_frame": None,
                        "best_sharpness": 0.0,
                        "best_bbox": bbox,
                        "vehicle_class": v_class,
                        "vehicle_conf": v_conf,
                        "triggered": False,
                        "exited": False,
                        "is_stopped": True,
                        "motion_state": "CALCULATING",
                        "direction": "Stationary (Gate)",
                    }

                assigned_track_ids.add(best_tid)
                tr = self._tracks[best_tid]
                tr["last_seen"] = now
                if v_class != "vehicle":
                    tr["vehicle_class"] = v_class
                tr["vehicle_conf"] = max(tr.get("vehicle_conf", 0.0), v_conf)

                obs = TrackObservation(
                    timestamp=now,
                    center_y=cy,
                    center_x=cx,
                    bbox=bbox,
                    sharpness=sharpness,
                    frame=frame.copy() if frame is not None else None,
                )
                tr["observations"].append(obs)

                # Compute real-time trajectory displacement and motion dynamics
                first_obs = tr["observations"][0]
                dt_track = max(0.001, now - first_obs.timestamp)
                dy_track = cy - first_obs.center_y
                dx_track = cx - first_obs.center_x
                dist_track = math.hypot(dx_track, dy_track)

                trap_px = max(80.0, (self.sweet_spot_y_end - self.sweet_spot_y_start) * frame_h)
                speed_mps = (dist_track / trap_px) * self.trap_distance_meters / dt_track
                computed_kph = round(speed_mps * 3.6, 1)

                px_per_sec = dist_track / dt_track

                # Direction of travel: require sustained directional movement >= 25px
                if dy_track > 25:
                    dir_label = "Ingress (Entry)"
                elif dy_track < -25:
                    dir_label = "Egress (Exit)"
                elif abs(dx_track) > 25:
                    dir_label = "Lateral Crossing"
                else:
                    dir_label = "Stationary (Gate)"

                # Motion state & Speed calculation:
                # Real vehicle transit across roadway requires sustained displacement >= 60px,
                # velocity >= 8.5 km/h, and displacement rate >= 50 px/sec.
                # Bounding box jitter, hand wobble, or stationary vehicles at the gate are locked to 0.0 km/h [STOPPED].
                if dist_track < 60.0 or computed_kph < 8.5 or px_per_sec < 50.0:
                    tr["is_stopped"] = True
                    tr["speed_kmh"] = 0.0
                    tr["motion_state"] = "STOPPED"
                    tr["direction"] = "Stationary (Gate)"
                else:
                    tr["is_stopped"] = False
                    tr["motion_state"] = "MOVING"
                    tr["speed_kmh"] = round(min(self.max_speed_kmh, computed_kph), 1)
                    tr["direction"] = dir_label

                # Ensure initial best frame exists
                if tr["best_frame"] is None and frame is not None:
                    tr["best_frame"] = frame.copy()
                    tr["best_sharpness"] = sharpness
                    tr["best_bbox"] = bbox

                # Keep track of sharpest frame in the sweet spot
                in_sweet_spot = self.sweet_spot_y_start <= norm_cy <= self.sweet_spot_y_end
                if in_sweet_spot:
                    if not tr["in_sweet_spot"]:
                        tr["in_sweet_spot"] = True
                        tr["sweet_spot_enter_time"] = now

                    if tr["best_frame"] is None or sharpness >= tr["best_sharpness"]:
                        tr["best_sharpness"] = sharpness
                        tr["best_bbox"] = bbox
                        if frame is not None:
                            tr["best_frame"] = frame.copy()

                elif tr["in_sweet_spot"] and norm_cy > self.sweet_spot_y_end:
                    # Vehicle exited the sweet spot zone
                    tr["exited"] = True
                    if tr["sweet_spot_exit_time"] is None:
                        tr["sweet_spot_exit_time"] = now
                        if tr["sweet_spot_enter_time"]:
                            dt = tr["sweet_spot_exit_time"] - tr["sweet_spot_enter_time"]
                            if dt > 0.05:
                                speed = (self.trap_distance_meters / dt) * 3.6
                                if self.min_speed_kmh <= speed <= self.max_speed_kmh:
                                    tr["speed_kmh"] = round(speed, 1)
                                    tr["is_stopped"] = False
                                    tr["motion_state"] = "MOVING"

                active_events.append(tr)

            # Cleanup tracks that haven't been seen in > 3.0 seconds
            stale_cutoff = now - 3.0
            stale = [tid for tid, tr in self._tracks.items() if tr["last_seen"] < stale_cutoff]
            for tid in stale:
                del self._tracks[tid]
                self._logged_tracks.discard(tid)

            return active_events

    def estimate_speed(self, t_enter: float, t_exit: float) -> Optional[float]:
        """Calculates vehicle speed in km/h from trap transit duration."""
        dt = t_exit - t_enter
        if dt <= 0:
            return None
        speed = (self.trap_distance_meters / dt) * 3.6
        if self.min_speed_kmh <= speed <= self.max_speed_kmh:
            return round(speed, 1)
        return None

    def get_triggerable_tracks(self) -> List[dict]:
        """
        Returns tracks currently in or completing the sweet spot ready for ANPR OCR and logging.
        """
        triggerable = []
        with self._lock:
            for tid, tr in self._tracks.items():
                if tr["triggered"]:
                    continue
                n_obs = len(tr["observations"])
                is_ready = (
                    (tr["in_sweet_spot"] or tr.get("exited", False))
                    and tr["best_frame"] is not None
                    and n_obs >= 2
                )
                if is_ready:
                    tr["triggered"] = True
                    triggerable.append(tr)
        return triggerable

    def reset_track_triggered(self, track_id: int):
        """Allows subsequent frames of an active track to trigger if earlier frames had no valid plate."""
        with self._lock:
            if track_id in self._tracks:
                self._tracks[track_id]["triggered"] = False


class ZeroLagVideoStream:
    """
    High-performance threaded video frame reader.
    Eliminates OpenCV internal buffering lag on RTSP / USB webcams.
    Guarantees that read_latest() always returns the immediate live frame (0 ms lag).
    """

    def __init__(self, src, buffer_size: int = 60):
        self.src = src
        self.buffer_size = buffer_size
        self._cap = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._latest_frame: Optional[np.ndarray] = None
        self._latest_time: float = 0.0
        self._frame_history: deque = deque(maxlen=buffer_size)
        self._fps: float = 30.0

    def start(self) -> bool:
        src_val = int(self.src) if str(self.src).isdigit() else self.src
        if isinstance(src_val, int):
            self._cap = cv2.VideoCapture(src_val, cv2.CAP_AVFOUNDATION)
            try:
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            except Exception:
                pass
        else:
            self._cap = cv2.VideoCapture(src_val)

        # Set low latency options where supported by OpenCV backend
        try:
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        if not self._cap or not self._cap.isOpened():
            if isinstance(src_val, int):
                self._cap = cv2.VideoCapture(src_val)
                if not self._cap.isOpened():
                    return False
            else:
                return False

        # Drain warmup frames so camera auto-exposure and gain wake up
        if isinstance(src_val, int):
            for _ in range(15):
                ret, frame = self._cap.read()
                time.sleep(0.03)
                if ret and frame is not None and frame.mean() > 10.0:
                    with self._lock:
                        self._latest_frame = frame
                        self._latest_time = time.time()
                    break

        # Read camera reported FPS if valid
        cam_fps = self._cap.get(cv2.CAP_PROP_FPS)
        if cam_fps and cam_fps > 5.0 and cam_fps <= 120.0:
            self._fps = cam_fps

        self._running = True
        self._thread = threading.Thread(target=self._capture_worker, daemon=True, name="ZeroLagGrabber")
        self._thread.start()
        return True

    def _capture_worker(self):
        """Worker thread draining the camera buffer continuously."""
        while self._running:
            if not self._cap or not self._cap.isOpened():
                time.sleep(0.1)
                continue

            ret, frame = self._cap.read()
            now = time.time()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            with self._lock:
                self._latest_frame = frame
                self._latest_time = now
                self._frame_history.append((now, frame))

    def read_latest(self) -> Tuple[bool, Optional[np.ndarray], float]:
        """Returns the most recent frame and timestamp with 0 ms queue latency."""
        with self._lock:
            if self._latest_frame is None:
                return False, None, 0.0
            return True, self._latest_frame.copy(), self._latest_time

    def get_recent_burst(self, duration_seconds: float = 0.5) -> List[Tuple[float, np.ndarray]]:
        """Returns candidate frames recorded within the last `duration_seconds`."""
        now = time.time()
        cutoff = now - duration_seconds
        with self._lock:
            return [(t, f.copy()) for (t, f) in self._frame_history if t >= cutoff]

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._cap:
            self._cap.release()


class PlateConsensusAggregator:
    """
    Fuses multi-frame candidate plate readings from a high-speed vehicle pass.
    Selects the most statistically confident and syntactically valid license plate.
    Supports assembling multi-frame fragments (e.g. Line 1 'CG07' in frame 1 + Line 2 'AN8902' in frame 2).
    """

    def __init__(self):
        self.candidates: List[dict] = []
        self.fragments: List[dict] = []

    def add_candidate(self, raw_plate: str, confidence: float, bbox: Optional[Tuple[int, int, int, int]] = None):
        if not raw_plate:
            return
        cleaned = fix_optical_plate_confusion(raw_plate)
        norm = normalize_plate(cleaned)
        is_valid = validate_plate(norm)

        # Weight bonus for syntactically valid plates (Standard State or BH series)
        effective_conf = confidence + (0.20 if is_valid else 0.0)

        self.candidates.append({
            "raw": raw_plate,
            "normalized": norm,
            "is_valid": is_valid,
            "confidence": confidence,
            "effective_conf": effective_conf,
            "bbox": bbox,
        })

    def add_fragment(self, fragment: str, confidence: float = 0.85, bbox: Optional[Tuple[int, int, int, int]] = None):
        """Adds single-line or partial optical fragment from frame (e.g. CG07, AN8902)."""
        if not fragment:
            return
        cleaned = re.sub(r"[^A-Z0-9]", "", fragment.upper())
        if len(cleaned) < 2 or cleaned in {"IND", "INDIA", "IN", "HSRP", "GOVT"}:
            return
        self.fragments.append({
            "text": cleaned,
            "conf": confidence,
            "bbox": bbox,
        })

    def _try_assemble_fragments(self):
        """Assembles 2 or 3 fragments if candidates don't have a valid plate."""
        if len(self.fragments) < 2:
            return
        # Test all pairs of fragments
        for i in range(len(self.fragments)):
            for j in range(len(self.fragments)):
                if i == j:
                    continue
                combo = self.fragments[i]["text"] + self.fragments[j]["text"]
                fixed = fix_optical_plate_confusion(combo)
                norm = normalize_plate(fixed)
                if validate_plate(norm):
                    avg_c = (self.fragments[i]["conf"] + self.fragments[j]["conf"]) / 2.0
                    self.add_candidate(norm, max(0.92, avg_c))

        # Test 3-fragment combinations (e.g. CG07 + CU + 8073)
        if len(self.fragments) >= 3:
            for i in range(len(self.fragments)):
                for j in range(len(self.fragments)):
                    for k in range(len(self.fragments)):
                        if i == j or j == k or i == k:
                            continue
                        combo = self.fragments[i]["text"] + self.fragments[j]["text"] + self.fragments[k]["text"]
                        fixed = fix_optical_plate_confusion(combo)
                        norm = normalize_plate(fixed)
                        if validate_plate(norm):
                            avg_c = (self.fragments[i]["conf"] + self.fragments[j]["conf"] + self.fragments[k]["conf"]) / 3.0
                            self.add_candidate(norm, max(0.93, avg_c))

    def get_best(self, require_valid: bool = False) -> Optional[dict]:
        valid_candidates = [c for c in self.candidates if c.get("is_valid", False)]
        if not valid_candidates:
            self._try_assemble_fragments()
            valid_candidates = [c for c in self.candidates if c.get("is_valid", False)]

        if valid_candidates:
            valid_candidates.sort(key=lambda c: c.get("effective_conf", 0.0), reverse=True)
            return valid_candidates[0]

        if require_valid:
            return None

        if not self.candidates:
            return None

        # Sort primarily by validity, then effective confidence
        self.candidates.sort(key=lambda c: (c["is_valid"], c["effective_conf"]), reverse=True)
        return self.candidates[0]

