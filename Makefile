.PHONY: help up down build logs test migrate seed retention load-test clean

PYTHON ?= .venv/bin/python
PYTEST ?= .venv/bin/pytest
ALEMBIC ?= .venv/bin/alembic

help:
	@echo "Available commands:"
	@echo "  make up          - Start all docker containers (api, postgres, minio)"
	@echo "  make down        - Stop all docker containers"
	@echo "  make test        - Run pytest test suite"
	@echo "  make migrate     - Run database migrations"
	@echo "  make seed        - Seed admin user, default gate, and device API key"
	@echo "  make retention   - Run media retention cleanup job"
	@echo "  make load-test   - Run 5 events/s load test"
	@echo "  make camera      - Start laptop/USB webcam monitor (ANPR only)"
	@echo "  make camera-highspeed - 60 km/h optimized camera (ANPR only)"
	@echo "  make camera-record    - Start webcam with 24/7 HDD recording + ANPR (--record)"
	@echo "  make edge-raw    - Run raw camera capture listener on port 5000 (bench test)"
	@echo "  make edge-agent  - Run production gate box adapter on port 5000"
	@echo "  make edge-simulate - Run live background vehicle feeder"
	@echo "  make upgrade-tracker - Pull latest updates from upstream vehicle_detection_tracker"
	@echo "  make frontend-dev - Run Vite React dashboard dev server"
	@echo "  make frontend-build - Build production React dashboard bundle"
	@echo "  make reset-data  - Clear test detections and reset daily pass register"
	@echo "  make clean       - Remove cache and temporary test files"

upgrade-tracker:
	@echo "🔄 Pulling latest upstream updates for vehicle_detection_tracker..."
	@git -C modules/vehicle_detection_tracker pull origin main 2>/dev/null || git -C modules/vehicle_detection_tracker pull origin master
	@echo "✅ Upstream vehicle_detection_tracker is up to date!"

camera:
	$(PYTHON) scripts/edge_camera_gateway.py --camera 0

camera-highspeed:
	$(PYTHON) scripts/edge_camera_gateway.py --camera 0 --trap-distance 6.0 --speed-limit 60

camera-record:
	$(PYTHON) scripts/edge_camera_gateway.py --camera 0 --trap-distance 6.0 --speed-limit 60 --record --record-dir ./recordings --record-segment 10 --record-min-free-gb 5

camera-dual-record:
	$(PYTHON) scripts/edge_camera_gateway.py --camera 0 --cargo-camera 1 --trap-distance 6.0 --speed-limit 60 --record --record-dir ./recordings --record-segment 10 --record-min-free-gb 5

reset-data:
	@$(PYTHON) -c "import httpx; \
r = httpx.post('http://localhost:8000/api/v1/auth/login', json={'username':'admin','password':'AdminGatePassword2026!'}); \
token = r.json()['access_token']; \
clr = httpx.post('http://localhost:8000/api/v1/detections/clear-all', headers={'Authorization': f'Bearer {token}'}); \
print('✅ Operational Register Cleared & Reset: Day Serial is now #001')"


edge-raw:
	$(PYTHON) edge/raw_listener.py --port 5000

edge-agent:
	$(PYTHON) edge/gatebox_agent.py --port 5000

edge-simulate:
	$(PYTHON) scripts/edge_camera_gateway.py --simulate

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f api

test:
	$(PYTEST) tests/ -v

migrate:
	$(ALEMBIC) upgrade head

seed:
	$(PYTHON) -m app.scripts.seed

retention:
	$(PYTHON) -m app.scripts.retention

load-test:
	$(PYTHON) scripts/load_test.py --url http://localhost:8000 --rate 5 --duration 600

clean:
	rm -rf .pytest_cache .coverage htmlcov __pycache__ */__pycache__ */*/__pycache__ media_storage/*
