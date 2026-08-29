# 🧪 Smart Port Security Platform - Testing Guide

## Quick Setup Tests

### 1. Run Automated Tests
```bash
cd /home/abdo/Downloads/cyber-digital-twin
./test_setup.sh
```

This will verify:
- ✅ Python imports
- ✅ Database connectivity
- ✅ Data lake integrity
- ✅ Device registry
- ✅ FastAPI application
- ✅ Authentication system
- ✅ Configuration loading

---

## 2. Unit Tests

### Run pytest
```bash
python3 -m pytest -v
```

### Run specific test file
```bash
python3 -m pytest tests/test_mqtt_listener_event.py -v
python3 -m pytest tests/test_event_normalizer.py -v
python3 -m pytest tests/test_action_dispatcher.py -v
```

### Run with coverage
```bash
python3 -m pytest --cov=backend --cov=smart_port -v
```

---

## 3. API Integration Tests

### Start the app in one terminal
```bash
source .env
python3 run.py
```

### Test health endpoints (new terminal)

#### Basic health check
```bash
curl http://localhost:8000/health | jq .
```

#### Platform health
```bash
curl http://localhost:8000/api/v1/platform/health | jq .
```

#### List devices
```bash
curl http://localhost:8000/api/v1/edge/devices | jq .
```

#### Get statistics
```bash
curl http://localhost:8000/statistics | jq .
```

---

## 4. Authentication Tests

### Get JWT token
```bash
TOKEN=$(curl -X POST http://localhost:8000/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=$(grep DEMO_ADMIN_PASSWORD .env | cut -d= -f2)" | jq -r '.access_token')

echo "Token: $TOKEN"
```

### Use token in requests
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/edge/devices | jq .
```

---

## 5. Database Tests

### Check database content
```bash
python3 << 'EOF'
from backend.database import SessionLocal
from backend.database.models import SensorReading, Alert, Mission, Incident

db = SessionLocal()

print("📊 Database Statistics:")
print(f"  Sensor Readings: {db.query(SensorReading).count()}")
print(f"  Alerts: {db.query(Alert).count()}")
print(f"  Missions: {db.query(Mission).count()}")
print(f"  Incidents: {db.query(Incident).count()}")

# Show recent readings
readings = db.query(SensorReading).order_by(SensorReading.received_at.desc()).limit(5).all()
print(f"\n📈 Latest Sensor Readings:")
for r in readings:
    print(f"  {r.device_id}: {r.value} ({r.type})")

db.close()
EOF
```

---

## 6. Data Lake Tests

### Check data lake events
```bash
python3 << 'EOF'
from smart_port.data.data_lake import lake_summary

summary = lake_summary()
print("📂 Data Lake Summary:")
for stream, stats in summary.items():
    print(f"  {stream}: {stats['files']} files, {stats['events']} events")
EOF
```

### Read recent telemetry events
```bash
tail -5 data_lake/telemetry/*.jsonl | jq .
```

### Count events by type
```bash
wc -l data_lake/*/*.jsonl
```

---

## 7. Device Registry Tests

### Verify devices
```bash
python3 << 'EOF'
from smart_port.edge.device_registry import DEVICE_REGISTRY

print("🔧 Device Registry:")
for dev_id, profile in DEVICE_REGISTRY.items():
    print(f"  {dev_id}: {profile.device_type} at {profile.zone}")
EOF
```

### Test device validation
```bash
python3 << 'EOF'
from smart_port.edge.device_registry import DEVICE_REGISTRY, validate_identity

device = DEVICE_REGISTRY["drone_01"]
alerts = validate_identity("drone_01", device.token, "drone/telemetry")

print("✅ Valid token and topic:")
if alerts:
    print(f"  Alerts: {alerts}")
else:
    print("  No security issues")

# Test invalid token
alerts = validate_identity("drone_01", "wrong_token", "drone/telemetry")
print(f"\n❌ Invalid token:")
print(f"  Alerts: {alerts}")
EOF
```

---

## 8. WebSocket Tests

### Connect via wscat (install first)
```bash
npm install -g wscat

# Connect to WebSocket
wscat -c ws://localhost:8000/ws
```

### Test via Python
```bash
python3 << 'EOF'
import asyncio
import json
from websockets import connect

async def test_websocket():
    uri = "ws://localhost:8000/ws"
    async with connect(uri) as websocket:
        print("✅ Connected to WebSocket")
        # Wait for messages
        try:
            msg = await asyncio.wait_for(websocket.recv(), timeout=5)
            print(f"📨 Received: {msg}")
        except asyncio.TimeoutError:
            print("⏱ No messages (timeout)")

asyncio.run(test_websocket())
EOF
```

---

## 9. Simulation Tests

### Start drone simulator
```bash
python3 simulation/drone_sim.py
```

### Seed data lake
```bash
python3 simulation/data_lake_seed.py
```

### Run attack simulator
```bash
python3 attacks/flood_attack.py
python3 attacks/spoofing_attack.py
python3 attacks/unknown_device_attack.py
python3 attacks/impossible_value_attack.py
```

---

## 10. Performance Tests

### Load test with Apache Bench
```bash
# Install ab (Apache Bench)
# Ubuntu/Debian: sudo apt-get install apache2-utils
# macOS: brew install httpd

# Simple health check load test
ab -n 100 -c 10 http://localhost:8000/health

# API endpoints
ab -n 100 -c 10 http://localhost:8000/statistics
```

### Load test with wrk
```bash
# Install wrk: https://github.com/wg/wrk

wrk -t12 -c400 -d30s http://localhost:8000/health
```

---

## 11. Security Tests

### Test JWT expiration
```bash
python3 << 'EOF'
from backend.auth import create_access_token, decode_access_token
from datetime import timedelta

# Create token with 1 second expiration
token = create_access_token(
    {"sub": "test"}, 
    timedelta(seconds=1)
)

print(f"Token: {token[:30]}...")

# Try to decode immediately
result = decode_access_token(token)
print(f"✅ Valid: {result}")

# Wait and try again
import time
time.sleep(2)

try:
    result = decode_access_token(token)
    print(f"❌ Should have expired!")
except Exception as e:
    print(f"✅ Expired as expected: {type(e).__name__}")
EOF
```

### Test invalid credentials
```bash
curl -X POST http://localhost:8000/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=wrong_password"
```

---

## 12. Integration Test Suite

Run the complete integration test:
```bash
python3 << 'EOF'
import requests
import json
from time import sleep

BASE_URL = "http://localhost:8000"

print("🔍 Running Integration Tests...\n")

# 1. Health check
print("1️⃣  Health Check:")
resp = requests.get(f"{BASE_URL}/health")
print(f"   Status: {resp.status_code}")
print(f"   Response: {resp.json()}\n")

# 2. Get statistics
print("2️⃣  Get Statistics:")
resp = requests.get(f"{BASE_URL}/statistics")
if resp.status_code == 200:
    stats = resp.json()
    print(f"   Total devices: {stats.get('total_devices', 'N/A')}")
    print(f"   Active devices: {stats.get('active_devices', 'N/A')}")
    print(f"   Total alerts: {stats.get('total_alerts', 'N/A')}\n")

# 3. Get devices
print("3️⃣  Get Devices:")
resp = requests.get(f"{BASE_URL}/devices")
if resp.status_code == 200:
    devices = resp.json()
    print(f"   Found {len(devices)} devices\n")

# 4. Platform health (v1)
print("4️⃣  Platform Health (v1):")
resp = requests.get(f"{BASE_URL}/api/v1/platform/health")
if resp.status_code == 200:
    health = resp.json()
    print(f"   Status: {health.get('status', 'N/A')}")
    print(f"   Database: {health.get('database_available', 'N/A')}\n")

# 5. Edge devices
print("5️⃣  Edge Devices:")
resp = requests.get(f"{BASE_URL}/api/v1/edge/devices")
if resp.status_code == 200:
    edge_devices = resp.json()
    print(f"   Found {len(edge_devices)} edge devices\n")

print("✅ Integration tests completed!")
EOF
```

---

## Testing Checklist

- [ ] Run `./test_setup.sh` - all 7 tests pass
- [ ] Run `pytest -v` - all unit tests pass
- [ ] Start app: `python3 run.py`
- [ ] Check health endpoints
- [ ] Verify JWT authentication
- [ ] Test database connectivity
- [ ] Verify data lake events
- [ ] Test device registry
- [ ] Test WebSocket connection
- [ ] Run simulation scenarios
- [ ] Load test endpoints
- [ ] Security validation
- [ ] Integration tests

---

## Troubleshooting

### Tests fail with "ModuleNotFoundError"
```bash
# Install dependencies
pip install -r requirements.txt
```

### Database locked error
```bash
# Remove old database and recreate
rm digital_twin.db
python3 run.py  # Auto-creates tables
```

### Port already in use
```bash
# Kill process on port 8000
lsof -i :8000
kill -9 <PID>

# Or change port in .env
echo "SMART_PORT_API_PORT=8001" >> .env
```

### MQTT connection failed
```bash
# Start MQTT broker
mosquitto -p 1883

# Or Docker
docker run -d -p 1883:1883 eclipse-mosquitto
```

---

## Continuous Testing

### Run tests on file changes
```bash
# Install pytest-watch
pip install pytest-watch

# Auto-run tests on changes
ptw -- -v
```

### Pre-commit testing
```bash
# Install pre-commit
pip install pre-commit

# Create .pre-commit-config.yaml
cat > .pre-commit-config.yaml << 'EOF'
repos:
  - repo: local
    hooks:
      - id: pytest
        name: pytest
        entry: pytest
        language: system
        types: [python]
        pass_filenames: false
        always_run: true
EOF

# Install hook
pre-commit install
```

---

## Performance Baselines

After running performance tests, record baseline metrics:

```
Health endpoint:   ~10 ms
Statistics endpoint: ~50 ms
Devices endpoint:    ~30 ms
Platform health:     ~100 ms
```

---

## Summary

Your Smart Port Security Platform includes:
- ✅ 7-step setup test suite
- ✅ Full pytest unit tests
- ✅ API integration tests
- ✅ Database verification
- ✅ Data lake validation
- ✅ WebSocket testing
- ✅ Security tests
- ✅ Performance testing tools

**Start testing now**: `./test_setup.sh`
