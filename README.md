# Forest Gate Vehicle Monitoring System - Cloud Backend

Cloud backend for real-time edge vehicle gate monitoring. Ingests ANPR (Camera A) and vehicle load classifier (Camera B) telemetry from forest gate mini PCs over 4G connections, guarantees idempotent ingestion and gap-free serials, stores media objects in S3/MinIO, and streams live detections to web dashboards over WebSockets.

---

## 1. Quickstart

### Prerequisites
- Python 3.12+ (or Docker & Docker Compose)
- Docker & Docker Compose (for production stack: API + PostgreSQL 16 + MinIO)

### Option A: Running with Docker Compose (Recommended)
```bash
# 1. Clone repository
cd /Users/mohitbaghel/Desktop/ANPR

# 2. Start services (PostgreSQL 16, MinIO, FastAPI backend)
make up
# or: docker compose up -d

# 3. Apply database migrations
make migrate

# 4. Seed default gate, admin user, and generate gate device API key
make seed
```

### Option B: Running Locally with Python 3.12 & React
```bash
# 1. Start Python Backend
source .venv/bin/activate
uv pip install -e ".[dev]"
python -m app.scripts.seed
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 2. In another terminal, start React Live Dashboard
cd frontend
npm install
npm run dev
# Dashboard opens on http://localhost:5173
```

---

## 2. Running Tests

The test suite covers idempotency, 200 parallel concurrent serial allocations, 30s deduplication windows, out-of-order uploads, role permissions, WebSocket latency, login lockout, and media retention:

```bash
# Run full pytest suite
make test
# or: pytest tests/ -v
```

### Running Load Test
```bash
# Simulates 5 events/s edge traffic for 10 minutes
python scripts/load_test.py --url http://localhost:8000 --rate 5 --duration 600 --api-key <YOUR_DEVICE_API_KEY>
```

---

## 3. Real Camera Setup & Testing Guide

You can test vehicle ingress in 3 different ways:

### Method 1: Instant Browser Test (No Hardware Needed)
1. Open the dashboard at `http://localhost:5173/`.
2. Click **`+ Simulate Gate Crossing`** in the top navigation bar.
3. A real vehicle pass is generated, stored in PostgreSQL, and pushed via WebSocket to your screen in `< 100ms`.

### Method 2: Test via Edge Camera Gateway CLI Script
Use the included [`scripts/edge_camera_gateway.py`](file:///Users/mohitbaghel/Desktop/ANPR/scripts/edge_camera_gateway.py):

```bash
# A. Send a single test pass with custom plate:
.venv/bin/python scripts/edge_camera_gateway.py --plate "KA 05 MN 4821"

# B. Run continuous background simulator (sends pass every 8s + 30s heartbeats):
.venv/bin/python scripts/edge_camera_gateway.py --simulate
```

### Method 3: Connect a Real USB Webcam or Laptop Camera
To capture from your laptop camera or a USB camera at the gate:
```bash
# 1. Install OpenCV in your environment
uv pip install opencv-python

# 2. Run gateway pointing to camera device 0 (default USB webcam):
.venv/bin/python scripts/edge_camera_gateway.py --camera 0
```
* **Controls**: A live camera window opens. Press **`[SPACEBAR]`** to snap a passing vehicle photo and instantly broadcast it to the cloud dashboard!

### Method 4: High-Speed 60 km/h Road & Gate Camera ANPR Tracker
When vehicles traverse the gate or roadway at speeds up to 60+ km/h (16.7 m/s):
```bash
# A. Run High-Speed Tracker with default 6.0m trap calibration and 60 km/h radar:
make camera-highspeed
# or:
.venv/bin/python scripts/edge_camera_gateway.py --camera 0 --trap-distance 6.0 --speed-limit 60

# B. Connect High-Speed RTSP PoE IP Camera (Hikvision / Dahua / Hanwha):
.venv/bin/python scripts/edge_camera_gateway.py \
  --camera "rtsp://admin:Password123@192.168.10.10:554/Streaming/Channels/101" \
  --trap-distance 6.0 \
  --speed-limit 60
```
#### ⚡ How the 60 km/h Tracking Engine Works:
1. **Zero-Lag Threaded Video Grabber (`ZeroLagVideoStream`)**: Continuous background thread drains RTSP hardware buffer to guarantee **0 ms queue latency**.
2. **Sub-millisecond Motion Tracker (`HighSpeedVehicleTracker`)**: Downsampled grayscale motion differencing (< 2 ms) localizes vehicles and tracks centroids across virtual trap lines (Approach, Sweet Spot, Departure).
3. **Spectrico MobileNet Vehicle Color Classifier (`VehicleFeatureExtractor`)**: Powered by OpenCV DNN; analyzes vehicle crops in < 15ms to classify color (White, Silver, Black, Red, Blue, Grey, Yellow, etc.) with probability rankings.
4. **Spectrico MobileNet Make & Model Recognition (MMR)**: Identifies car and truck brands and models (e.g. Tata, Mahindra, Ashok Leyland, Toyota, Hyundai, Ford, etc.) with confidence scoring.
5. **8-Direction Compass Heading & Calibrated Velocity**: Measures motion angles and categorizes trajectories into 8 compass headings (Top Left, Right, etc.) with multi-sample reliability scoring.
6. **Laplacian Variance Sharpness (Anti-Motion-Blur)**: Buffers sweet-spot burst frames, evaluates edge definition via $\text{Var}(\nabla^2 I)$, and isolates the crispest unblurred plate crop.
7. **Plate Consensus & Syntax Fusion**: Normalizes Indian RTO / BH syntax and repairs optical confusion characters (`fix_optical_plate_confusion`).
8. **Track-Based Debouncing**: Replaces blind timer locks with track IDs. Once Vehicle 1 departs, Vehicle 2 (trailing 1.2s behind) is captured immediately without dropping!

### Upstream Tracker Integration & Upgrades
The external tracker is safely isolated in `modules/vehicle_detection_tracker` with its own git remote:
```bash
# Pull the latest commits from upstream vehicle_detection_tracker at any time:
make upgrade-tracker
```

### Method 5: Direct On-Chip ANPR Camera Webhook
For smart cameras with on-chip ANPR (Hikvision / Dahua / Hanwha LPR):
1. Open the camera's web management interface (`http://192.168.1.X`).
2. Navigate to **Configuration -> Event -> Smart Event / Road Traffic -> HTTP Post / Alarm Host**.
3. Set **Destination URL**: `http://<YOUR_SERVER_IP>:8000/api/v1/events`
4. Set **Header**: `X-API-Key: gate_key_DSxf-AxjAI8bWripHPjFqrv13oVsoolwxwDV_wTmpB4`
5. The camera will automatically post license plate JSON directly whenever a car or truck passes through the gate.

---

## 4. Production Deployment Guide

### Option 1: Complete 1-Command Docker Deployment (Full Stack)
```bash
# 1. Start all containers (PostgreSQL 16, MinIO S3, API + React Dashboard, Caddy TLS Proxy)
docker compose up -d

# That's it!
# - Container entrypoint automatically executes database migrations ('alembic upgrade head')
# - Baseline accounts (admin, reviewer, viewer) and gate device are auto-seeded
# - Live Dashboard opens on http://localhost (port 80) or http://localhost:8000
```

### Option 2: Linux Edge Gate Box Systemd Service (Mini PC / Raspberry Pi / Jetson)
Pre-configured systemd service units are provided under `deploy/systemd/`:
```bash
# Copy and enable Gate Box agent service
sudo cp deploy/systemd/gatebox-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gatebox-gateway.service

# Check live service status & logs:
sudo systemctl status gatebox-gateway.service
sudo journalctl -u gatebox-gateway.service -f
```

---

## 5. Environment Variables Reference

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `PROJECT_NAME` | `Vehicle Gate Monitoring Cloud` | Application service title |
| `API_V1_PREFIX` | `/api/v1` | URL prefix for REST routes |
| `DEBUG` | `false` | Enable SQL query logging and debug mode |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/anpr` | Async SQLAlchemy database connection string |
| `STORAGE_DRIVER` | `local` (or `s3`) | Object storage backend (`s3` for MinIO/AWS, `local` for disk) |
| `STORAGE_LOCAL_DIR`| `./media_storage` | Local directory for uploaded photos in local storage mode |
| `S3_ENDPOINT_URL` | `http://localhost:9000` | MinIO or AWS S3 endpoint URL |
| `S3_ACCESS_KEY` | `minioadmin` | S3 Access Key |
| `S3_SECRET_KEY` | `minioadmin` | S3 Secret Key |
| `S3_BUCKET_NAME` | `anpr-media` | S3 bucket name for images |
| `PRESIGNED_URL_EXPIRE_SECONDS` | `600` | Expiration for presigned photo URLs (10 min) |
| `JWT_SECRET` | `super-secret-key-forest-gate-change-me` | Secret key for signing JWT tokens |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | JWT access token expiration |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | JWT refresh token expiration |
| `MAX_FAILED_LOGINS` | `5` | Maximum failed login attempts before account lockout |
| `LOCKOUT_MINUTES` | `15` | Duration of account lockout in minutes |
| `CONF_THRESHOLD_LOAD` | `0.60` | Minimum load classification confidence before flagging for review |
| `CONF_THRESHOLD_PLATE` | `0.85` | Minimum ANPR plate confidence before flagging for review |
| `MEDIA_RETENTION_DAYS` | `90` | Days to keep media objects before running daily retention purge |
| `DEFAULT_TIMEZONE` | `Asia/Kolkata` | Local timezone used for gate `day_serial` resets |
| `CLIP_BASE_URL` | `""` | Base URL for gate box video clip tunnel proxy |
| `CORS_ORIGINS` | `["*"]` | Allowed CORS origins for dashboard browsers |

---

## 4. Edge Gate Box API Examples (curl)

All edge endpoints authenticate using the `X-API-Key` header generated by `make seed`.

### 1. Stage 1: Ingest Recognition Event
Fast ingestion (< 100 ms) triggered as vehicle passes:
```bash
curl -X POST "http://localhost:8000/api/v1/events" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_GATE_DEVICE_API_KEY" \
  -d '{
    "event_uid": "gate1-20261018-001234",
    "camera_id": "cam-a-anpr",
    "captured_at": "2026-10-18T14:30:00Z",
    "plate_raw": "KA 05 M 5678",
    "plate_conf": 0.94,
    "vehicle_type": "truck",
    "vehicle_color": "white",
    "load_type": "timber_logs",
    "load_conf": 0.88,
    "clip_ref": {
      "camera": "cam-b-load",
      "segment": "seg_20261018_143000.mp4",
      "start": "00:00:05",
      "end": "00:00:20"
    }
  }'
```

### 2. Stage 2: Upload Media Files (Multipart)
Uploads plate, scene, and load classification photos (any subset):
```bash
curl -X PUT "http://localhost:8000/api/v1/detections/DETECTION_UUID_HERE/media" \
  -H "X-API-Key: YOUR_GATE_DEVICE_API_KEY" \
  -F "plate=@/path/to/plate_crop.jpg" \
  -F "scene=@/path/to/gate_scene.jpg" \
  -F "load_thumb=@/path/to/load_thumbnail.jpg" \
  -F "load_full=@/path/to/load_highres.jpg"
```

### 3. Late Load Classification Update
When Camera B finishes deep load classification asynchronously:
```bash
curl -X PATCH "http://localhost:8000/api/v1/detections/DETECTION_UUID_HERE/load" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_GATE_DEVICE_API_KEY" \
  -d '{
    "load_type": "timber_logs",
    "load_conf": 0.92
  }'
```

### 4. Edge Heartbeat Telemetry (Every 30s)
Reports gate box camera, disk, and power health:
```bash
curl -X POST "http://localhost:8000/api/v1/heartbeat" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_GATE_DEVICE_API_KEY" \
  -d '{
    "camera_a_ok": true,
    "camera_b_ok": true,
    "disk_used_pct": 54.2,
    "queue_depth": 1,
    "ups_on_battery": false,
    "raw": {
      "cpu_temp_c": 49.5,
      "cellular_signal_dbm": -72
    }
  }'
```

---

## 5. Dashboard API Examples

### 1. User Login
```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "AdminGatePassword2026!"
  }'
```

### 2. Live WebSocket Connection
```bash
# Connect using JWT access token
wscat -c "ws://localhost:8000/ws/live?token=JWT_ACCESS_TOKEN_HERE"
```

### 3. Query Detections with Keyset Pagination
```bash
curl -X GET "http://localhost:8000/api/v1/detections?limit=20&status=needs_review" \
  -H "Authorization: Bearer JWT_ACCESS_TOKEN_HERE"
```

### 4. Reviewer Correction
```bash
curl -X PATCH "http://localhost:8000/api/v1/detections/DETECTION_UUID_HERE" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer REVIEWER_OR_ADMIN_JWT_TOKEN" \
  -d '{
    "plate": "KA05M5678",
    "load_type": "timber_logs"
  }'
```

### 5. Export Detections CSV (Audited)
```bash
curl -X GET "http://localhost:8000/api/v1/detections/export.csv" \
  -H "Authorization: Bearer REVIEWER_OR_ADMIN_JWT_TOKEN" \
  --output detections_export.csv
```
# ANPR
