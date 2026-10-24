#!/usr/bin/env python3
"""
24/7 Continuous HDD Video Recorder for Gate Camera.

Runs as a background thread alongside the ANPR detection pipeline.
Writes video segments to disk in configurable durations (default: 10-minute chunks).
Automatically handles segment rotation and optional oldest-first disk cleanup
when HDD free space falls below a configurable threshold.

Usage (standalone):
    python scripts/continuous_recorder.py --src 0 --dir /mnt/hdd/recordings

Usage (integrated, via edge_camera_gateway.py --record):
    python scripts/edge_camera_gateway.py --camera rtsp://... --record
"""

import argparse
import datetime
import os
import queue
import shutil
import threading
import time
from typing import Optional


class ContinuousHDDRecorder:
    """
    Writes a continuous 24/7 video recording from any OpenCV-compatible source
    or direct frame feed to segmented .mp4 files on a local HDD / SSD.

    Segment layout on disk:
        <recordings_dir>/
            YYYY-MM-DD/
                HH-MM-SS_HH-MM-SS.mp4   (start–end timestamps)
                ...

    Parameters
    ----------
    src : str | int | None
        Camera source — RTSP URL or USB integer index.
        Set to None for direct frame ingestion via `write_frame(frame)`.
    recordings_dir : str
        Absolute path to the directory that will receive video segments.
        Created automatically if it does not exist.
    segment_minutes : int
        Duration of each recording segment in minutes (default 10).
    fps : float
        Frames-per-second for the output encoder (default 25).
    codec : str
        Four-character FourCC codec code (default "mp4v").
    min_free_gb : float
        Minimum free disk space in GiB to maintain.
    enabled : bool
        Master switch — set False to create a no-op recorder.
    """

    def __init__(
        self,
        src=None,
        recordings_dir: str = "./recordings",
        segment_minutes: int = 10,
        fps: float = 25.0,
        codec: str = "mp4v",
        min_free_gb: float = 5.0,
        enabled: bool = True,
    ):
        self.src = src
        self.recordings_dir = os.path.abspath(recordings_dir)
        self.segment_minutes = segment_minutes
        self.fps = fps
        self.codec = codec
        self.min_free_gb = min_free_gb
        self.enabled = enabled

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._current_segment_path: Optional[str] = None
        self._lock = threading.Lock()
        self._frame_queue: queue.Queue = queue.Queue(maxsize=120)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Start the background recording thread."""
        if not self.enabled:
            print("ℹ️  [Recorder] 24/7 HDD recording is disabled (pass --record to enable).")
            return

        os.makedirs(self.recordings_dir, exist_ok=True)
        self._running = True
        target = self._queue_record_loop if self.src is None else self._record_loop
        self._thread = threading.Thread(
            target=target,
            daemon=True,
            name="ContinuousHDDRecorder",
        )
        self._thread.start()
        print(f"🎬 [Recorder] 24/7 HDD recording STARTED → {self.recordings_dir}")
        print(f"   Mode           : {'Direct In-Memory Frame Feed' if self.src is None else f'Stream Capture ({self.src})'}")
        print(f"   Segment length : {self.segment_minutes} min")
        print(f"   Min free space : {self.min_free_gb:.1f} GiB (auto-purge oldest if below)")

    def stop(self):
        """Signal the recording thread to stop and wait for it to finish."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        print("🛑 [Recorder] 24/7 HDD recording stopped.")

    def write_frame(self, frame):
        """Thread-safe non-blocking write of a frame to the recording queue."""
        if not self.enabled or not self._running or frame is None:
            return
        try:
            self._frame_queue.put_nowait(frame)
        except queue.Full:
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frame_queue.put_nowait(frame)
            except queue.Full:
                pass

    def current_segment(self) -> Optional[str]:
        """Return the path of the file currently being written (thread-safe)."""
        with self._lock:
            return self._current_segment_path

    # ------------------------------------------------------------------
    # Internal implementation
    # ------------------------------------------------------------------

    def _queue_record_loop(self):
        """Queue-based recording loop — writes frames passed via write_frame()."""
        try:
            import cv2
        except ImportError:
            print("❌ [Recorder] OpenCV not installed. Run: pip install opencv-python")
            return

        fourcc = cv2.VideoWriter_fourcc(*self.codec)
        writer: Optional[cv2.VideoWriter] = None
        segment_start_time: float = 0.0
        segment_duration_s = self.segment_minutes * 60.0
        width, height = None, None

        while self._running:
            try:
                frame = self._frame_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if frame is None or frame.size == 0:
                continue

            h, w = frame.shape[:2]
            if width is None or height is None or w != width or h != height:
                width, height = w, h
                if writer is not None:
                    writer.release()
                    writer = None

            now = time.time()
            # Segment rotation
            if writer is None or (now - segment_start_time) >= segment_duration_s:
                if writer is not None:
                    writer.release()
                    print(f"   ✂️  Segment saved: {self._current_segment_path}")

                self._ensure_free_space()
                seg_path = self._new_segment_path()
                writer = cv2.VideoWriter(seg_path, fourcc, self.fps, (width, height))
                if not writer.isOpened():
                    print(f"❌ [Recorder] VideoWriter failed for {seg_path}.")
                    writer = None
                    time.sleep(1.0)
                    continue

                with self._lock:
                    self._current_segment_path = seg_path
                segment_start_time = now
                print(f"🎥 [Recorder] New segment: {os.path.basename(seg_path)}")

            if writer is not None:
                writer.write(frame)

        if writer is not None:
            writer.release()

    def _record_loop(self):
        """Main recording loop — reconnects automatically on stream failure."""
        try:
            import cv2
        except ImportError:
            print("❌ [Recorder] OpenCV not installed. Run: pip install opencv-python")
            return

        while self._running:
            try:
                src_val = int(self.src) if str(self.src).isdigit() else self.src
                cap = cv2.VideoCapture(src_val)

                if not cap.isOpened():
                    print(f"⚠️  [Recorder] Cannot open source '{self.src}'. Retrying in 10s…")
                    time.sleep(10)
                    continue

                # Use camera-reported FPS when available and sane
                cam_fps = cap.get(cv2.CAP_PROP_FPS)
                if 5.0 < cam_fps <= 120.0:
                    self.fps = cam_fps

                width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  or 1920
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080

                fourcc = cv2.VideoWriter_fourcc(*self.codec)
                writer: Optional[cv2.VideoWriter] = None
                segment_start_time: float = 0.0
                segment_duration_s  = self.segment_minutes * 60.0

                print(f"✅ [Recorder] Stream opened: {width}×{height} @ {self.fps:.1f} FPS")

                while self._running:
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        print("⚠️  [Recorder] Frame read failed. Reconnecting…")
                        break  # exit inner loop → reconnect

                    now = time.time()

                    # --- Segment rotation ---
                    if writer is None or (now - segment_start_time) >= segment_duration_s:
                        if writer is not None:
                            writer.release()
                            print(f"   ✂️  Segment saved: {self._current_segment_path}")

                        # Free-space guard before starting a new file
                        self._ensure_free_space()

                        seg_path = self._new_segment_path()
                        writer = cv2.VideoWriter(seg_path, fourcc, self.fps, (width, height))
                        if not writer.isOpened():
                            print(f"❌ [Recorder] VideoWriter failed for {seg_path}. "
                                  "Check codec / permissions.")
                            writer = None
                            time.sleep(5)
                            continue

                        with self._lock:
                            self._current_segment_path = seg_path
                        segment_start_time = now
                        print(f"🎥 [Recorder] New segment: {os.path.basename(seg_path)}")

                    if writer is not None:
                        writer.write(frame)

                # Release resources before reconnect
                if writer is not None:
                    writer.release()
                    writer = None
                cap.release()

            except Exception as exc:
                print(f"❌ [Recorder] Unexpected error: {exc}. Retrying in 10s…")
                time.sleep(10)

    def _new_segment_path(self) -> str:
        """Build the file path for a new recording segment."""
        now = datetime.datetime.now()
        day_dir = os.path.join(self.recordings_dir, now.strftime("%Y-%m-%d"))
        os.makedirs(day_dir, exist_ok=True)
        filename = now.strftime("%H-%M-%S") + ".mp4"
        return os.path.join(day_dir, filename)

    def _ensure_free_space(self):
        """
        Delete the oldest recording segment when free disk space is below min_free_gb.
        Continues deleting until enough space is freed or no segments remain.
        """
        if self.min_free_gb <= 0:
            return

        min_free_bytes = self.min_free_gb * 1024 ** 3

        while True:
            try:
                free = shutil.disk_usage(self.recordings_dir).free
            except Exception:
                return

            if free >= min_free_bytes:
                return

            oldest = self._find_oldest_segment()
            if oldest is None:
                print("⚠️  [Recorder] Disk full but no segments found to delete!")
                return

            try:
                os.remove(oldest)
                print(f"🗑️  [Recorder] Disk space low — deleted oldest segment: {oldest}")
            except OSError as exc:
                print(f"⚠️  [Recorder] Could not delete {oldest}: {exc}")
                return

    def _find_oldest_segment(self) -> Optional[str]:
        """Return the absolute path of the oldest .mp4 segment, or None."""
        oldest_path = None
        oldest_mtime = float("inf")

        try:
            for root, _dirs, files in os.walk(self.recordings_dir):
                for fn in files:
                    if fn.endswith(".mp4"):
                        fp = os.path.join(root, fn)
                        # Skip the file currently being written
                        with self._lock:
                            if fp == self._current_segment_path:
                                continue
                        mtime = os.path.getmtime(fp)
                        if mtime < oldest_mtime:
                            oldest_mtime = mtime
                            oldest_path = fp
        except Exception:
            pass

        return oldest_path


# ---------------------------------------------------------------------------
# Standalone entry-point (for testing the recorder independently)
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="24/7 Continuous HDD Recorder — standalone test mode"
    )
    parser.add_argument(
        "--src",
        default="0",
        help="Camera source: USB index (e.g. 0) or RTSP URL",
    )
    parser.add_argument(
        "--dir",
        default="./recordings",
        help="Directory to write video segments to (default: ./recordings)",
    )
    parser.add_argument(
        "--segment",
        type=int,
        default=10,
        help="Segment length in minutes (default: 10)",
    )
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=5.0,
        help="Minimum free disk GiB before oldest segments are auto-purged (default: 5)",
    )
    parser.add_argument(
        "--codec",
        default="mp4v",
        help="FourCC codec (default: mp4v). Use 'avc1' for H.264 on macOS.",
    )
    args = parser.parse_args()

    recorder = ContinuousHDDRecorder(
        src=args.src,
        recordings_dir=args.dir,
        segment_minutes=args.segment,
        min_free_gb=args.min_free_gb,
        codec=args.codec,
        enabled=True,
    )
    recorder.start()

    print("\nPress Ctrl+C to stop recording.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        recorder.stop()
        print("👋 Recording stopped.")


if __name__ == "__main__":
    main()
