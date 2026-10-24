"""
Camera B Cargo Vehicle Tracker (YOLOv8 + ByteTrack).

Reads Camera B's sub-stream RTSP feed (e.g. 102 path) to avoid overloading camera sessions.
Tracks passing vehicles, records bounding boxes and sharpest frames per track_id,
and matches the best cargo photo to Camera A's license plate events within a ±3 second window.
"""

import datetime
import math
import threading
import time
from typing import Dict, Optional, Tuple


class CameraBTracker:
    def __init__(
        self,
        rtsp_url: str = "rtsp://admin:CameraPass2026@192.168.10.11:554/Streaming/Channels/102",
        model_name: str = "yolov8n.pt",
        enabled: bool = True,
    ):
        self.rtsp_url = rtsp_url
        self.model_name = model_name
        self.enabled = enabled
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Track buffer: track_id -> { "sharpness": float, "box_area": float, "time": datetime, "frame_jpeg": bytes }
        self._track_history: Dict[int, dict] = {}
        self._lock = threading.Lock()

    def start(self):
        """Starts the background tracking thread."""
        if not self.enabled:
            print("ℹ️ Camera B tracking is disabled by configuration.")
            return

        self._running = True
        self._thread = threading.Thread(target=self._tracker_worker, daemon=True, name="CameraBTracker")
        self._thread.start()
        print(f"🎥 Camera B tracker initialized on RTSP: {self.rtsp_url}")

    def stop(self):
        """Stops the tracking loop."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _estimate_sharpness(self, cv2_frame) -> float:
        """Estimates frame sharpness using the Laplacian variance."""
        try:
            import cv2
            gray = cv2.cvtColor(cv2_frame, cv2.COLOR_BGR2GRAY)
            return cv2.Laplacian(gray, cv2.CV_64F).var()
        except Exception:
            return 1.0

    def _tracker_worker(self):
        """Worker thread running YOLOv8 tracking on Camera B sub-stream."""
        try:
            from ultralytics import YOLO
            import cv2
        except ImportError:
            print("⚠️ 'ultralytics' or 'cv2' not installed. Camera B tracking is in passive mode.")
            print("   To enable live cargo tracking: pip install ultralytics opencv-python")
            return

        print("⚡ Loading YOLOv8 model for Camera B cargo classification...")
        try:
            model = YOLO(self.model_name)
        except Exception as e:
            print(f"❌ Failed to load YOLO model: {e}")
            return

        while self._running:
            try:
                print(f"🎥 Connecting to Camera B stream: {self.rtsp_url}")
                # COCO classes: 2 car, 3 motorcycle, 5 bus, 7 truck
                # vid_stride=1 ensures continuous frame tracking at high speeds (up to 60+ km/h)
                stream = model.track(
                    source=self.rtsp_url,
                    stream=True,
                    persist=True,
                    tracker="bytetrack.yaml",
                    classes=[2, 3, 5, 7],
                    imgsz=640,
                    vid_stride=1,
                    verbose=False,
                )

                for r in stream:
                    if not self._running:
                        break

                    now = datetime.datetime.now(datetime.timezone.utc)
                    frame_bgr = r.orig_img

                    if r.boxes is None or len(r.boxes) == 0:
                        continue

                    for box in r.boxes:
                        if box.id is None:
                            continue

                        track_id = int(box.id[0])
                        xyxy = box.xyxy[0].tolist()
                        width = xyxy[2] - xyxy[0]
                        height = xyxy[3] - xyxy[1]
                        area = width * height

                        # Estimate sharpness
                        sharpness = self._estimate_sharpness(frame_bgr)

                        # Encode frame to JPEG
                        _, buffer = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        jpeg_bytes = buffer.tobytes()

                        with self._lock:
                            existing = self._track_history.get(track_id)
                            # Keep the sharpest frame with significant area
                            if existing is None or (sharpness > existing["sharpness"] and area >= existing["box_area"] * 0.8):
                                self._track_history[track_id] = {
                                    "sharpness": sharpness,
                                    "box_area": area,
                                    "time": now,
                                    "frame_jpeg": jpeg_bytes,
                                    "cls_id": int(box.cls[0]),
                                }

                    # Clean up old tracks older than 60 seconds
                    with self._lock:
                        cutoff = now - datetime.timedelta(seconds=60)
                        expired = [tid for tid, data in self._track_history.items() if data["time"] < cutoff]
                        for tid in expired:
                            del self._track_history[tid]

            except Exception as e:
                print(f"⚠️ Camera B stream disconnected: {e}. Reconnecting in 5s...")
                time.sleep(5)

    def get_best_frame_near_time(
        self,
        target_time: datetime.datetime,
        window_seconds: float = 2.0,
    ) -> Optional[Tuple[bytes, str]]:
        """
        When Camera A's ANPR event arrives at time t, pick the Camera B track
        associated with this vehicle pass using Gaussian temporal proximity weighting.
        Prevents a large truck passing later from stealing a sedan's cargo photo.
        Returns: (jpeg_bytes, suggested_vehicle_type) or None.
        """
        if not self.enabled:
            return None

        # Ensure target_time has UTC timezone if naive
        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=datetime.timezone.utc)

        class_map = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

        with self._lock:
            best_match = None
            best_score = -1.0

            for tid, data in self._track_history.items():
                data_time = data["time"]
                if data_time.tzinfo is None:
                    data_time = data_time.replace(tzinfo=datetime.timezone.utc)

                time_delta = abs((data_time - target_time).total_seconds())
                if time_delta <= window_seconds:
                    # Gaussian proximity weight: peaks at time_delta = 0
                    time_weight = math.exp(- (time_delta ** 2) / (2.0 * (0.8 ** 2)))
                    area_factor = math.sqrt(max(100.0, data["box_area"]))
                    sharpness_factor = min(2.0, max(0.5, data.get("sharpness", 1.0) / 100.0))

                    score = time_weight * area_factor * sharpness_factor
                    if score > best_score:
                        best_score = score
                        best_match = data

            if best_match:
                veh_type = class_map.get(best_match.get("cls_id", 7), "truck")
                return best_match["frame_jpeg"], veh_type

        return None
