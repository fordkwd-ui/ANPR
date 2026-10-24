#!/usr/bin/env python3
"""
Production Edge Gate Box Adapter & Sender Agent.

Runs on the physical Gate Box (Mini PC / Raspberry Pi / Jetson) at the forest checkpost.
Architecture:
  1. FastAPI listener on port 5000 receives Hikvision ANPR camera pushes.
  2. Parses XML/JSON + multipart JPEG images.
  3. Computes deterministic SHA-1 event_uid: SHA1("A|<captured_at>|<plate_raw>").
  4. Queries Camera B tracker (YOLOv8 + ByteTrack) for matching cargo frame within ±3s.
  5. Stores media locally on disk (under photos/) and enqueues to durable SQLite queue (queue.db).
  6. Sends Stage 1 (small JSON) immediately, then Stage 2 (photos).
  7. Background worker retries with backoff across 4G dropouts (zero data loss across power cuts).
  8. Background heartbeat pings Camera A & B on TCP 554 and reports edge health every 30s.
"""

import argparse
import asyncio
import datetime
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import sys
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import uvicorn

# Configuration defaults
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PHOTOS_DIR = os.path.join(BASE_DIR, "photos")
RAW_DIR = os.path.join(PHOTOS_DIR, "raw")
DB_PATH = os.path.join(BASE_DIR, "queue.db")

os.makedirs(PHOTOS_DIR, exist_ok=True)
os.makedirs(RAW_DIR, exist_ok=True)

# Global runtime state
CONFIG = {
    "cloud_url": "http://localhost:8000/api/v1",
    "api_key": "gate_key_DSxf-AxjAI8bWripHPjFqrv13oVsoolwxwDV_wTmpB4",
    "camera_a_ip": "192.168.10.10",
    "camera_b_ip": "192.168.10.11",
    "camera_b_rtsp": "rtsp://admin:CameraPass2026@192.168.10.11:554/Streaming/Channels/102",
    "enable_camera_b": False,
}

# ---------------------------------------------------------------------------
# Durable SQLite Queue (survives sudden power cuts on edge mini PCs)
# ---------------------------------------------------------------------------
class DurableQueue:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS q (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,          -- 'event' or 'media'
                    event_uid TEXT NOT NULL,
                    detection_id TEXT,
                    payload TEXT NOT NULL,
                    tries INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending', -- 'pending', 'done', 'failed'
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_q_status ON q(status, id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_q_uid ON q(event_uid)")

    def enqueue(self, kind: str, event_uid: str, payload: dict, detection_id: Optional[str] = None):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO q (kind, event_uid, detection_id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    kind,
                    event_uid,
                    detection_id,
                    json.dumps(payload),
                    datetime.datetime.now(datetime.timezone.utc).isoformat(),
                ),
            )

    def get_pending(self, limit: int = 1) -> list:
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM q WHERE status = 'pending' ORDER BY id ASC LIMIT ?",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def mark_done(self, item_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM q WHERE id = ?", (item_id,))

    def mark_retry(self, item_id: int, tries: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE q SET tries = ?, status = 'pending' WHERE id = ?", (tries + 1, item_id))

    def update_detection_id_for_uid(self, event_uid: str, detection_id: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE q SET detection_id = ? WHERE event_uid = ? AND kind = 'media'",
                (detection_id, event_uid),
            )

    def count_pending(self) -> int:
        with self._get_conn() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM q WHERE status = 'pending'")
            return cur.fetchone()[0]


queue = DurableQueue(DB_PATH)

# ---------------------------------------------------------------------------
# Camera B Tracker Integration (Ultralytics YOLOv8 + ByteTrack)
# ---------------------------------------------------------------------------
camera_b_tracker = None

def init_camera_b():
    global camera_b_tracker
    if CONFIG["enable_camera_b"]:
        try:
            from edge.camera_b_tracker import CameraBTracker
            camera_b_tracker = CameraBTracker(rtsp_url=CONFIG["camera_b_rtsp"], enabled=True)
            camera_b_tracker.start()
        except Exception as e:
            print(f"⚠️ Could not start Camera B tracker: {e}")

# ---------------------------------------------------------------------------
# Hikvision XML / JSON Parser
# ---------------------------------------------------------------------------
def parse_hikvision(form) -> dict:
    """
    Parses Hikvision ANPR camera HTTP push multipart payload.
    Extracts:
      - captured_at (ISO datetime with timezone)
      - plate_raw (plate string)
      - plate_conf (float 0.0 - 1.0)
      - vehicle_type (truck, car, van, etc.)
      - scene_jpeg (bytes or None)
      - plate_jpeg (bytes or None)
    """
    plate_raw = "UNKNOWN"
    plate_conf = 0.90
    vehicle_type = "truck"
    captured_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    plate_jpeg = None
    scene_jpeg = None

    # Inspect all form keys
    for key, value in form.items():
        key_lower = key.lower()

        # 1. XML notification payload
        if "xml" in key_lower or (hasattr(value, "filename") and value.filename and value.filename.endswith(".xml")):
            try:
                raw_xml = value.file.read() if hasattr(value, "file") else str(value).encode("utf-8")
                root = ET.fromstring(raw_xml)

                # Hikvision XML schema elements
                # Typically: <PlateResult><plateNumber>KA05MN4821</plateNumber><confidenceLevel>95</confidenceLevel>
                for elem in root.iter():
                    tag = elem.tag.split("}")[-1]  # Strip namespace
                    text = (elem.text or "").strip()
                    if tag in ["plateNumber", "licensePlate", "plateText"] and text:
                        plate_raw = text
                    elif tag in ["confidenceLevel", "confidence", "plateConfidence"] and text:
                        try:
                            val = float(text)
                            plate_conf = val / 100.0 if val > 1.0 else val
                        except ValueError:
                            pass
                    elif tag in ["vehicleType", "vehicleCategory"] and text:
                        v_lower = text.lower()
                        if any(w in v_lower for w in ["truck", "heavy", "lorry"]):
                            vehicle_type = "truck"
                        elif any(w in v_lower for w in ["pickup", "bolero"]):
                            vehicle_type = "pickup"
                        elif any(w in v_lower for w in ["car", "sedan", "suv"]):
                            vehicle_type = "car"
                        elif any(w in v_lower for w in ["van", "omni"]):
                            vehicle_type = "van"
                    elif tag in ["dateTime", "captureTime", "eventTime"] and text:
                        try:
                            # Normalize Hikvision format "2026-10-18T10:15:30.123+05:30"
                            captured_at = datetime.datetime.fromisoformat(text).isoformat()
                        except Exception:
                            pass
            except Exception as e:
                print(f"⚠️ XML Parse warning: {e}")

        # 2. JSON notification payload
        elif "json" in key_lower:
            try:
                raw_json = value.file.read() if hasattr(value, "file") else str(value)
                data = json.loads(raw_json)
                pr = data.get("PlateResult") or data.get("EventNotificationAlert", {}).get("ANPR", {}) or data
                plate_raw = pr.get("plateNumber") or pr.get("licensePlate") or plate_raw
                if "confidenceLevel" in pr:
                    val = float(pr["confidenceLevel"])
                    plate_conf = val / 100.0 if val > 1.0 else val
                if "vehicleType" in pr:
                    vehicle_type = str(pr["vehicleType"]).lower()
            except Exception as e:
                print(f"⚠️ JSON Parse warning: {e}")

        # 3. Photo parts
        if hasattr(value, "filename") and value.filename:
            content = value.file.read() if hasattr(value, "file") else b""
            if any(k in key_lower for k in ["licenseplatepicture", "platepicture", "plate"]):
                plate_jpeg = content
            elif any(k in key_lower for k in ["detectionpicture", "scenepicture", "scene", "overview"]):
                scene_jpeg = content

    return {
        "captured_at": captured_at,
        "plate_raw": plate_raw,
        "plate_conf": plate_conf,
        "vehicle_type": vehicle_type,
        "scene_jpeg": scene_jpeg,
        "plate_jpeg": plate_jpeg,
    }


def save_media(ev: dict) -> Tuple[str, str]:
    """Saves plate and scene photos to local disk on edge mini PC."""
    event_uid = ev["event_uid"]
    plate_path = os.path.join(PHOTOS_DIR, f"{event_uid}_plate.jpg")
    scene_path = os.path.join(PHOTOS_DIR, f"{event_uid}_scene.jpg")

    if ev.get("plate_jpeg"):
        with open(plate_path, "wb") as f:
            f.write(ev["plate_jpeg"])
    else:
        # Create minimal 1x1 placeholder
        with open(plate_path, "wb") as f:
            f.write(b"\xff\xd8\xff\xd9")

    if ev.get("scene_jpeg"):
        with open(scene_path, "wb") as f:
            f.write(ev["scene_jpeg"])
    else:
        with open(scene_path, "wb") as f:
            f.write(b"\xff\xd8\xff\xd9")

    return plate_path, scene_path


# ---------------------------------------------------------------------------
# FastAPI Camera Listener on Gate Box (:5000)
# ---------------------------------------------------------------------------
app = FastAPI(title="Gate Box ANPR Edge Receiver")


@app.post("/anpr/event")
@app.post("/ISAPI/Event/notification/alertStream")
@app.post("/")
async def anpr_event(request: Request):
    """
    HTTP Push target for Camera A.
    Returns 200 fast (< 25ms) so camera connection never times out.
    """
    form = await request.form()

    # 1. Parse fields
    ev = parse_hikvision(form)

    # 2. Compute deterministic SHA-1 event_uid
    # Format: SHA1("A|<captured_at>|<plate_raw>")
    uid_seed = f"A|{ev['captured_at']}|{ev['plate_raw']}"
    ev["event_uid"] = hashlib.sha1(uid_seed.encode("utf-8")).hexdigest()

    # 3. Check Camera B tracker for matching cargo frame within ±3 seconds
    load_jpeg = None
    load_type = "timber_logs"  # Default forest gate load or unknown
    load_conf = 0.88

    if camera_b_tracker:
        try:
            target_dt = datetime.datetime.fromisoformat(ev["captured_at"])
            b_match = camera_b_tracker.get_best_frame_near_time(target_dt, window_seconds=3.0)
            if b_match:
                load_jpeg, suggested_veh = b_match
                if suggested_veh:
                    ev["vehicle_type"] = suggested_veh
                print(f"🎯 Matched Camera B cargo frame to plate {ev['plate_raw']}!")
        except Exception as e:
            print(f"⚠️ Camera B match warning: {e}")

    # 4. Save photos to local disk
    plate_path, scene_path = save_media(ev)
    load_path = ""
    if load_jpeg:
        load_path = os.path.join(PHOTOS_DIR, f"{ev['event_uid']}_load.jpg")
        with open(load_path, "wb") as f:
            f.write(load_jpeg)

    # 5. Enqueue Stage 1 (small JSON metadata)
    stage1_payload = {
        "event_uid": ev["event_uid"],
        "camera_id": "cam_a_anpr_4k",
        "captured_at": ev["captured_at"],
        "plate_raw": ev["plate_raw"],
        "plate_conf": ev["plate_conf"],
        "vehicle_type": ev["vehicle_type"],
        "vehicle_color": "white",
        "load_type": load_type,
        "load_conf": load_conf,
    }
    queue.enqueue("event", ev["event_uid"], stage1_payload)

    # 6. Enqueue Stage 2 (photos)
    stage2_payload = {
        "event_uid": ev["event_uid"],
        "plate_path": plate_path,
        "scene_path": scene_path,
        "load_path": load_path,
    }
    queue.enqueue("media", ev["event_uid"], stage2_payload)

    print(f"📥 [CAMERA A PUSH] Plate: {ev['plate_raw']} | UID: {ev['event_uid'][:12]}... (Enqueued)")
    return JSONResponse(content={"ok": True, "event_uid": ev["event_uid"]})


# ---------------------------------------------------------------------------
# Background Sender Loop: Durable Retry Worker
# ---------------------------------------------------------------------------
async def sender_worker():
    """
    Reads queue oldest-first.
    Posts /events (reusing event_uid on retry).
    Uploads media /detections/{id}/media.
    On failure: waits with exponential backoff.
    """
    client = httpx.AsyncClient(timeout=12.0)
    headers = {"X-API-Key": CONFIG["api_key"]}
    cloud_url = CONFIG["cloud_url"].rstrip("/")

    print("🚀 Background sender worker running (watching queue.db)...")

    while True:
        items = queue.get_pending(limit=1)
        if not items:
            await asyncio.sleep(1.0)
            continue

        item = items[0]
        item_id = item["id"]
        kind = item["kind"]
        event_uid = item["event_uid"]
        payload = json.loads(item["payload"])
        tries = item["tries"]

        try:
            if kind == "event":
                # Stage 1: Send small JSON
                r = await client.post(f"{cloud_url}/events", json=payload, headers=headers)
                if r.status_code in [200, 201]:
                    detection = r.json()
                    detection_id = detection["id"]
                    serial = detection["day_serial"]
                    print(f"✅ [CLOUD STAGE 1] Pass #{serial:03d} confirmed ({detection['plate']})")

                    # Link detection_id to corresponding media item
                    queue.update_detection_id_for_uid(event_uid, detection_id)
                    queue.mark_done(item_id)
                elif r.status_code == 409:
                    # Idempotent repeat
                    detection = r.json()
                    queue.update_detection_id_for_uid(event_uid, detection["id"])
                    queue.mark_done(item_id)
                else:
                    raise Exception(f"HTTP {r.status_code}: {r.text}")

            elif kind == "media":
                # Stage 2: Send photos
                detection_id = item["detection_id"]
                if not detection_id:
                    # Stage 1 hasn't resolved detection_id yet; retry in next iteration
                    await asyncio.sleep(1.0)
                    continue

                files = {}
                plate_path = payload.get("plate_path")
                scene_path = payload.get("scene_path")
                load_path = payload.get("load_path")

                if plate_path and os.path.exists(plate_path):
                    files["plate"] = ("plate.jpg", open(plate_path, "rb"), "image/jpeg")
                if scene_path and os.path.exists(scene_path):
                    files["scene"] = ("scene.jpg", open(scene_path, "rb"), "image/jpeg")
                if load_path and os.path.exists(load_path):
                    files["load_thumb"] = ("load.jpg", open(load_path, "rb"), "image/jpeg")

                if files:
                    r = await client.put(
                        f"{cloud_url}/detections/{detection_id}/media",
                        files=files,
                        headers=headers,
                    )
                    # Close file handles
                    for _, f_tuple in files.items():
                        f_tuple[1].close()

                    if r.status_code == 200:
                        print(f"✅ [CLOUD STAGE 2] Photos uploaded for detection {detection_id[:8]}...")
                        queue.mark_done(item_id)
                    else:
                        raise Exception(f"HTTP {r.status_code}: {r.text}")
                else:
                    queue.mark_done(item_id)

        except Exception as e:
            backoff = min(60, 2 ** min(tries, 6))
            print(f"⚠️ [4G SENDER RETRY] Item #{item_id} ({kind}) failed: {e}. Backoff {backoff}s...")
            queue.mark_retry(item_id, tries)
            await asyncio.sleep(backoff)


# ---------------------------------------------------------------------------
# Background Heartbeat: Camera Ping & Disk Health
# ---------------------------------------------------------------------------
def tcp_ok(host: str, port: int = 554, timeout: float = 1.5) -> bool:
    """Verifies TCP reachability of camera RTSP port 554."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False


def heartbeat_thread():
    """Reports camera connection states and edge disk usage every 30s."""
    client = httpx.Client(timeout=6.0)
    cloud_url = CONFIG["cloud_url"].rstrip("/")
    headers = {"X-API-Key": CONFIG["api_key"]}

    print(f"💓 Heartbeat service active (probing Camera A={CONFIG['camera_a_ip']}, Camera B={CONFIG['camera_b_ip']})...")

    while True:
        try:
            total, used, free = shutil.disk_usage(PHOTOS_DIR)
            disk_used_pct = round((used / total) * 100.0, 1)

            cam_a_ok = tcp_ok(CONFIG["camera_a_ip"], 554)
            cam_b_ok = tcp_ok(CONFIG["camera_b_ip"], 554)

            payload = {
                "camera_a_ok": cam_a_ok,
                "camera_b_ok": cam_b_ok,
                "disk_used_pct": disk_used_pct,
                "queue_depth": queue.count_pending(),
                "ups_on_battery": False,
                "raw": {
                    "cam_a_ip": CONFIG["camera_a_ip"],
                    "cam_b_ip": CONFIG["camera_b_ip"],
                    "uptime_sec": int(time.time()),
                },
            }

            r = client.post(f"{cloud_url}/heartbeat", json=payload, headers=headers)
            status_txt = "ONLINE" if r.status_code == 200 else f"HTTP {r.status_code}"
            print(f"💓 [{datetime.datetime.now().strftime('%H:%M:%S')}] Heartbeat: CamA={'OK' if cam_a_ok else 'DOWN'} CamB={'OK' if cam_b_ok else 'DOWN'} Disk={disk_used_pct}% Queue={payload['queue_depth']} -> {status_txt}")

        except Exception as e:
            print(f"⚠️ Heartbeat network error: {e}")

        time.sleep(30)


# ---------------------------------------------------------------------------
# CLI & App Startup
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Gate Box ANPR Edge Agent")
    parser.add_argument("--port", type=int, default=5000, help="Listen port for Camera A push (default: 5000)")
    parser.add_argument("--host", default="0.0.0.0", help="Listen host (default: 0.0.0.0)")
    parser.add_argument("--cloud", default=CONFIG["cloud_url"], help="Cloud backend API v1 URL")
    parser.add_argument("--key", default=CONFIG["api_key"], help="Gate device X-API-Key")
    parser.add_argument("--cam-a-ip", default=CONFIG["camera_a_ip"], help="Camera A IP address (default: 192.168.10.10)")
    parser.add_argument("--cam-b-ip", default=CONFIG["camera_b_ip"], help="Camera B IP address (default: 192.168.10.11)")
    parser.add_argument("--cam-b-rtsp", default=CONFIG["camera_b_rtsp"], help="Camera B RTSP sub-stream URL")
    parser.add_argument("--enable-cam-b", action="store_true", help="Enable Camera B YOLOv8 cargo tracking")

    args = parser.parse_args()

    CONFIG["cloud_url"] = args.cloud
    CONFIG["api_key"] = args.key
    CONFIG["camera_a_ip"] = args.cam_a_ip
    CONFIG["camera_b_ip"] = args.cam_b_ip
    CONFIG["camera_b_rtsp"] = args.cam_b_rtsp
    CONFIG["enable_camera_b"] = args.enable_cam_b

    print("\n🌲 ===================================================")
    print("🌲 FOREST GATE MONITORING — GATE BOX EDGE AGENT")
    print("🌲 ===================================================")
    print(f"📡 Camera A HTTP Push Port:  http://{args.host}:{args.port}/anpr/event")
    print(f"🌐 Cloud Backend Target:     {CONFIG['cloud_url']}")
    print(f"🔑 Device API Key:           {CONFIG['api_key'][:14]}... (GateBox Alpha)")
    print(f"📹 Camera A IP (ANPR):       {CONFIG['camera_a_ip']}:554")
    print(f"📹 Camera B IP (Cargo):      {CONFIG['camera_b_ip']}:554")
    print(f"💾 Persistent Queue:         {DB_PATH}")
    print(f"📁 Local Photos Cache:       {PHOTOS_DIR}")
    print("=" * 55 + "\n")

    # 1. Start Camera B tracker if requested
    init_camera_b()

    # 2. Start Heartbeat thread
    hb = threading.Thread(target=heartbeat_thread, daemon=True, name="HeartbeatThread")
    hb.start()

    # 3. Start background sender loop in asyncio
    loop = asyncio.new_event_loop()
    threading.Thread(target=lambda: loop.run_until_complete(sender_worker()), daemon=True, name="SenderWorker").start()

    # 4. Start FastAPI server for Camera A pushes
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
