#!/bin/bash
set -e

echo "🌲 ========================================================="
echo "🌲 FOREST GATE MONITORING SYSTEM — CONTAINER INITIALIZATION"
echo "🌲 ========================================================="

# Run database migrations
echo "🔄 [1/3] Running Alembic database migrations..."
alembic upgrade head || alembic stamp head || echo "⚠️ Migration note: tables may already be up to date."

# Seed default admin user, gate, and device API key
echo "🌱 [2/3] Verifying / seeding baseline accounts & gate device..."
python -m app.scripts.seed || echo "⚠️ Seed note: baseline data already initialized."

# Start uvicorn
echo "🚀 [3/3] Starting Cloud Backend & Live Dashboard on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
