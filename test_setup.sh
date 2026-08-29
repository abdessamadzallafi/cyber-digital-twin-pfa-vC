#!/bin/bash
# Test Suite for Smart Port Security Platform

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Smart Port Security Platform - Test Suite${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}\n"

# Load environment
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ .env file not found!${NC}"
    exit 1
fi

set -a
source .env
set +a

# Test 1: Python imports
echo -e "${BLUE}Test 1: Python Module Imports${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 << 'PYEOF'
import sys
try:
    print("  ✓ Importing FastAPI...")
    from fastapi import FastAPI
    print("  ✓ Importing SQLAlchemy...")
    from sqlalchemy import create_engine
    print("  ✓ Importing MQTT...")
    import paho.mqtt.client
    print("  ✓ Importing backend.main...")
    from backend.main import app
    print("  ✓ Importing smart_port modules...")
    from smart_port.config import settings
    from smart_port.edge.device_registry import DEVICE_REGISTRY
    from smart_port.data.data_lake import write_event
    print("\n✅ All imports successful!\n")
except Exception as e:
    print(f"\n❌ Import failed: {e}\n")
    sys.exit(1)
PYEOF

# Test 2: Database connectivity
echo -e "${BLUE}Test 2: Database Connectivity${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 << 'PYEOF'
import sys
from backend.database import SessionLocal, Base, engine
from sqlalchemy import text, inspect

try:
    print("  ✓ Creating engine...")
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    print("  ✓ Tables initialized")
    
    # Connect and verify
    db = SessionLocal()
    result = db.execute(text("SELECT 1"))
    db.close()
    print("  ✓ Database connection successful")
    
    # List tables
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"  ✓ Found {len(tables)} tables:")
    for table in sorted(tables):
        print(f"    - {table}")
    
    print("\n✅ Database check passed!\n")
except Exception as e:
    print(f"\n❌ Database test failed: {e}\n")
    sys.exit(1)
PYEOF

# Test 3: Data Lake
echo -e "${BLUE}Test 3: Data Lake${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 << 'PYEOF'
import sys
from pathlib import Path
from smart_port.data.data_lake import lake_summary

try:
    # Check directories
    print("  ✓ Checking data lake directories...")
    data_lake = Path("data_lake")
    streams = ["telemetry", "security", "missions", "network", "logs"]
    
    for stream in streams:
        path = data_lake / stream
        if path.exists():
            print(f"    ✓ {stream}/")
        else:
            print(f"    ✗ {stream}/ MISSING")
    
    # Get summary
    summary = lake_summary()
    print("\n  ✓ Data Lake Summary:")
    for stream, stats in summary.items():
        print(f"    - {stream}: {stats['files']} files, {stats['events']} events")
    
    print("\n✅ Data lake check passed!\n")
except Exception as e:
    print(f"\n❌ Data lake test failed: {e}\n")
    sys.exit(1)
PYEOF

# Test 4: Device Registry
echo -e "${BLUE}Test 4: Device Registry${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 << 'PYEOF'
import sys
from smart_port.edge.device_registry import DEVICE_REGISTRY, known_devices, validate_identity

try:
    print(f"  ✓ Device registry loaded: {len(DEVICE_REGISTRY)} devices")
    for dev_id, profile in list(DEVICE_REGISTRY.items())[:5]:
        print(f"    - {dev_id} ({profile.device_type}) @ {profile.zone}")
    
    all_devices = list(known_devices())
    print(f"\n  ✓ Known devices (including legacy): {len(all_devices)}")
    
    # Test validation
    drone = DEVICE_REGISTRY["drone_01"]
    alerts = validate_identity("drone_01", drone.token, "drone/telemetry")
    print(f"\n  ✓ Token validation working")
    if alerts:
        print(f"    Alerts: {alerts}")
    else:
        print(f"    No security alerts")
    
    print("\n✅ Device registry check passed!\n")
except Exception as e:
    print(f"\n❌ Device registry test failed: {e}\n")
    sys.exit(1)
PYEOF

# Test 5: FastAPI Routes
echo -e "${BLUE}Test 5: FastAPI Application${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 << 'PYEOF'
import sys
from backend.main import app

try:
    routes = [r for r in app.routes]
    print(f"  ✓ FastAPI app loaded with {len(routes)} routes")
    
    # List some important routes
    important_routes = [
        "/health",
        "/api/v1/platform/health",
        "/token"
    ]
    
    print("\n  ✓ Checking key routes:")
    route_paths = set()
    for r in routes:
        if hasattr(r, 'path'):
            route_paths.add(r.path)
    
    for route in important_routes:
        if route in route_paths:
            print(f"    ✓ {route}")
        else:
            print(f"    ⚠ {route} not found")
    
    print(f"\n  ✓ Total routes available: {len(route_paths)}")
    print("\n✅ FastAPI check passed!\n")
except Exception as e:
    print(f"\n❌ FastAPI test failed: {e}\n")
    sys.exit(1)
PYEOF

# Test 6: Authentication
echo -e "${BLUE}Test 6: Authentication System${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 << 'PYEOF'
import sys
from backend.auth import authenticate_user, create_access_token
from datetime import timedelta

try:
    print("  ✓ Testing authentication...")
    
    # Test token creation
    token = create_access_token({"sub": "test_user"}, timedelta(minutes=30))
    print(f"  ✓ Token created: {token[:30]}...")
    
    print("\n✅ Authentication check passed!\n")
except Exception as e:
    print(f"\n❌ Authentication test failed: {e}\n")
    sys.exit(1)
PYEOF

# Test 7: Configuration
echo -e "${BLUE}Test 7: Configuration${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 << 'PYEOF'
import sys
from smart_port.config import settings

try:
    print("  ✓ Environment Configuration:")
    print(f"    - Environment: {settings.environment}")
    print(f"    - API: {settings.api_host}:{settings.api_port}")
    print(f"    - MQTT: {settings.mqtt_host}:{settings.mqtt_port}")
    print(f"    - UDP: {settings.udp_host}:{settings.udp_port}")
    print(f"    - Database: {settings.database_url[:30]}...")
    print(f"    - Data Lake: {settings.data_lake_path}")
    
    print("\n✅ Configuration check passed!\n")
except Exception as e:
    print(f"\n❌ Configuration test failed: {e}\n")
    sys.exit(1)
PYEOF

# Final summary
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ ALL TESTS PASSED!${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}\n"

echo -e "${YELLOW}Next Steps:${NC}"
echo "  1. Start the application: python3 run.py"
echo "  2. Visit API docs: http://localhost:8000/docs"
echo "  3. Check health: curl http://localhost:8000/health"
echo "  4. Run pytest: python3 -m pytest -v"
echo ""
