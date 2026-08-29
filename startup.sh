#!/bin/bash
# Smart Port Security Platform - Startup Script

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "════════════════════════════════════════════════════════════════"
echo "  Smart Port Security Platform - Initialization"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Load environment
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found!"
    echo "Please run: cp .env.example .env and configure it."
    exit 1
fi

echo "📋 Loading configuration from .env..."
set -a
source .env
set +a
echo "✓ Environment loaded"
echo ""

# Check dependencies
echo "🔍 Checking dependencies..."
python3 -m pip show fastapi &>/dev/null && echo "✓ FastAPI installed" || {
    echo "❌ FastAPI not found. Running: pip install -r requirements.txt"
    pip install -r requirements.txt
}
echo ""

# Initialize database
echo "💾 Initializing database..."
python3 << 'PYEOF'
from backend.database import Base, engine
Base.metadata.create_all(bind=engine)
print("✓ Database tables created/verified")
PYEOF
echo ""

# Verify data lake
echo "📂 Verifying data lake structure..."
mkdir -p data_lake/{telemetry,security,missions,network,logs}
echo "✓ Data lake directories ready"
echo ""

# Startup options
echo "════════════════════════════════════════════════════════════════"
echo "  Ready to Start! Choose an option:"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "1) Start with Uvicorn (recommended for development)"
echo "   Command: uvicorn backend.main:app --host 0.0.0.0 --port 8000"
echo ""
echo "2) Start with Python run.py"
echo "   Command: python3 run.py"
echo ""
echo "3) Start with Docker Compose (requires Docker)"
echo "   Command: docker compose up --build"
echo ""
echo "4) Just verify setup (don't start)"
echo ""
echo "════════════════════════════════════════════════════════════════"
echo ""

if [ $# -eq 0 ]; then
    echo "Usage: ./startup.sh [1|2|3|4]"
    echo "Example: ./startup.sh 1"
    exit 1
fi

case "$1" in
    1)
        echo "🚀 Starting with Uvicorn..."
        echo ""
        uvicorn backend.main:app --host 0.0.0.0 --port 8000
        ;;
    2)
        echo "🚀 Starting with Python run.py..."
        echo ""
        python3 run.py
        ;;
    3)
        echo "🚀 Starting with Docker Compose..."
        echo ""
        docker compose up --build
        ;;
    4)
        echo "✅ Setup verified. Ready to launch!"
        echo ""
        echo "To start the application, run one of:"
        echo "  uvicorn backend.main:app --host 0.0.0.0 --port 8000"
        echo "  python3 run.py"
        echo "  docker compose up --build"
        ;;
    *)
        echo "❌ Invalid option: $1"
        echo "Please use 1, 2, 3, or 4"
        exit 1
        ;;
esac
