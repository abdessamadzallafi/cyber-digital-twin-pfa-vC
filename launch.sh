#!/bin/bash
# Smart Port Security Platform - Launch Script

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "🚀 Smart Port Security Platform Launcher"
echo "=========================================="
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found!"
    echo "Please create .env from .env.example"
    exit 1
fi

echo "📋 Loading environment configuration..."

# IMPORTANT: Use set -a / set +a to export all variables
# This ensures environment variables are available to the Python process
set -a
source .env
set +a

echo "✓ Environment loaded"
echo ""

# Verify required variables
REQUIRED_VARS=(
    "SMART_PORT_JWT_SECRET"
    "SMART_PORT_DEMO_ADMIN_PASSWORD"
    "SMART_PORT_DEMO_OPERATOR_PASSWORD"
    "SMART_PORT_DRONE_TOKEN"
)

echo "🔍 Verifying required variables..."
MISSING=()
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        MISSING+=("$var")
        echo "  ❌ $var NOT SET"
    else
        echo "  ✓ $var configured"
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo ""
    echo "❌ Missing variables: ${MISSING[*]}"
    exit 1
fi

echo ""
echo "✅ All required variables configured"
echo ""

# Show configuration summary
echo "📊 Configuration Summary:"
echo "  Environment: $SMART_PORT_ENV"
echo "  API: $SMART_PORT_API_HOST:$SMART_PORT_API_PORT"
echo "  MQTT: $SMART_PORT_MQTT_HOST:$SMART_PORT_MQTT_PORT"
echo "  UDP: $SMART_PORT_UDP_HOST:$SMART_PORT_UDP_PORT"
echo "  Database: ${SMART_PORT_DATABASE_URL:0:30}..."
echo ""

# Show launch options
echo "🎯 Launch Options:"
echo ""
echo "1) Start with python3 run.py (default):"
echo "   python3 run.py"
echo ""
echo "2) Start with uvicorn directly:"
echo "   uvicorn backend.main:app --host 0.0.0.0 --port 8000"
echo ""
echo "3) Start with Docker:"
echo "   docker compose up --build"
echo ""

# Auto-start if argument provided
if [ "$1" = "start" ] || [ "$1" = "auto" ]; then
    echo "🚀 Starting application..."
    echo ""
    python3 run.py
elif [ "$1" = "uvicorn" ]; then
    echo "🚀 Starting with uvicorn..."
    echo ""
    uvicorn backend.main:app --host 0.0.0.0 --port 8000
elif [ "$1" = "docker" ]; then
    echo "🚀 Starting with Docker Compose..."
    echo ""
    docker compose up --build
elif [ -z "$1" ]; then
    echo "To start the application, run:"
    echo "  $0 start    # or python3 run.py"
    echo "  $0 uvicorn  # or uvicorn backend.main:app ..."
    echo "  $0 docker   # or docker compose up --build"
else
    echo "❌ Unknown option: $1"
    echo "Use: $0 [start|uvicorn|docker]"
    exit 1
fi
