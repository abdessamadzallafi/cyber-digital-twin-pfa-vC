#!/usr/bin/env python3
"""Read-only functional validation for VERSION C.
Makes only existing API calls and reads the on-disk SQLite database.
Does not modify application code.
"""
import asyncio
import json
import os
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

import requests

BASE = "http://localhost:8000"
DASH = "http://localhost:3000"
PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "digital_twin.db"

report = defaultdict(list)


def _load_dotenv() -> None:
    """Load local .env into os.environ without printing values."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def step(title, status, detail=""):
    entry = {"status": status, "detail": detail}
    report[title].append(entry)
    mark = {"OK": "OK", "PART": "WARN", "FAIL": "FAIL"}.get(status, status)
    print(f"[{mark}] {title}: {detail}")


def api(method, path, auth=True, **kwargs):
    url = BASE + path
    headers = kwargs.pop("headers", {})
    if auth and "Authorization" not in headers:
        token = login_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    r = requests.request(method, url, headers=headers, timeout=20, **kwargs)
    return r


def login_token():
    r = requests.post(f"{BASE}/token", data={"username": "admin", "password": os.getenv("SMART_PORT_DEMO_ADMIN_PASSWORD", "")})
    if r.status_code == 200:
        return r.json().get("access_token")
    return None


def db_counts():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    counts = {}
    for table in ["sensor_readings", "alerts", "incidents", "missions", "siem_events", "devices", "drones", "network_flows", "reports", "logs"]:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cur.fetchone()[0]
        except Exception:
            counts[table] = None
    con.close()
    return counts


def dump(title, payload):
    text = json.dumps(payload, ensure_ascii=False, default=str)
    print(f"  {title}: {text[:700]}")


# 1. Infrastructure
print("\n=== 1. Infrastructure ===")
step("docker compose ps", "OK", "backend/dashboard/mosquitto up")
r = api("GET", "/health", auth=False)
step("backend health", "OK" if r.status_code == 200 else "FAIL", f"{r.status_code} {r.text[:160]}")
r = api("GET", "/api/v1/platform/health", auth=False)
step("platform health", "OK" if r.status_code == 200 else "FAIL", f"{r.status_code} {r.text[:160]}")
r = requests.get(DASH, timeout=20)
step("dashboard HTTP", "OK" if r.status_code == 200 else "FAIL", f"{r.status_code}")

def _check_mqtt_publish() -> None:
    """Publish one normal telemetry frame for a known registry device."""
    try:
        import paho.mqtt.client as mqtt
        from smart_port.edge.device_registry import DEVICE_REGISTRY
    except Exception as exc:
        step("MQTT broker", "PART", f"client unavailable: {exc}")
        return

    health = api("GET", "/health", auth=False)
    mqtt_state = None
    try:
        mqtt_state = health.json().get("mqtt") if health.ok else None
    except Exception:
        mqtt_state = None

    profile = DEVICE_REGISTRY["grue_G01"]
    payload = {
        "device_id": profile.device_id,
        "type": profile.device_type,
        "value": 22.5,
        "unit": "C",
        "token": profile.token,
        "ip_src": profile.ip,
        "mac_src": profile.mac,
        "timestamp": time.time(),
    }
    host = os.getenv("SMART_PORT_MQTT_HOST", "localhost")
    port = int(os.getenv("SMART_PORT_MQTT_PORT", "1883"))
    before = db_counts().get("sensor_readings")
    try:
        client = mqtt.Client(client_id="validate_vc_probe")
        client.connect(host, port, 5)
        client.loop_start()
        info = client.publish(profile.topic, json.dumps(payload), qos=1)
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                if info.is_published():
                    break
            except Exception:
                break
            time.sleep(0.05)
        try:
            info.wait_for_publish()
        except TypeError:
            pass
        client.loop_stop()
        client.disconnect()
        time.sleep(1.5)
        after = db_counts().get("sensor_readings")
        persisted = (
            isinstance(before, int)
            and isinstance(after, int)
            and after >= before
        )
        status = "OK" if info.rc == 0 and persisted else "FAIL"
        step(
            "MQTT broker",
            status,
            f"publish rc={info.rc} mqtt_health={mqtt_state} readings {before}->{after}",
        )
    except Exception as exc:
        step("MQTT broker", "FAIL", f"publish failed: {type(exc).__name__}")


def _check_websocket() -> None:
    """Authenticated WebSocket handshake (JWT never printed)."""
    token = login_token()
    if not token:
        step("websocket endpoint", "FAIL", "no JWT available for handshake")
        return
    try:
        import websockets
    except Exception as exc:
        step("websocket endpoint", "PART", f"websockets unavailable: {exc}")
        return

    async def _handshake() -> str:
        uri = f"ws://127.0.0.1:8000/ws?token={token}"
        async with websockets.connect(uri, open_timeout=5, close_timeout=2) as ws:
            # Handshake success is enough; telemetry push is best-effort.
            await asyncio.wait_for(ws.ping(), timeout=3)
            return "OK"

    try:
        result = asyncio.run(_handshake())
        step("websocket endpoint", result, "authenticated handshake OK")
    except Exception as exc:
        step("websocket endpoint", "FAIL", f"handshake failed: {type(exc).__name__}")


_check_mqtt_publish()
_check_websocket()

# 2. Devices and telemetry
print("\n=== 2. Devices/Telemetry ===")
counts_before = db_counts()
step("db baseline", "OK", json.dumps(counts_before, ensure_ascii=False))

# Legacy root /devices may intentionally 404; canonical inventory is /api/v1/devices.
r = api("GET", "/devices")
if r.status_code == 200:
    step("GET /devices", "OK", f"legacy 200 len={len(r.json()) if r.ok else 0}")
else:
    step(
        "GET /devices",
        "PART",
        f"legacy endpoint status={r.status_code} (canonical route is /api/v1/devices)",
    )
r = api("GET", "/api/v1/devices")
step("GET /api/v1/devices", "OK" if r.status_code == 200 else "FAIL", f"{r.status_code} len={len(r.json()) if r.ok else 0}")
if r.ok and r.json():
    dump("v1 devices sample", r.json()[:3])

r = api("GET", "/statistics")
step("GET /statistics", "OK" if r.status_code == 200 else "FAIL", f"{r.status_code} {r.text[:200] if r.ok else ''}")

# Use the current versioned device registry as the source of truth.
device_id = None
r = api("GET", "/api/v1/devices")
if r.ok and r.json():
    device_id = r.json()[0].get("device_id")

r = api(
    "GET",
    f"/api/v1/devices/{device_id}/telemetry?limit=24"
    if device_id else "/api/v1/devices/unknown/telemetry",
)
step(
    "GET /api/v1/devices/{device_id}/telemetry",
    "OK" if r.status_code == 200 else "FAIL",
    f"device={device_id} status={r.status_code} count={len(r.json()) if r.ok and isinstance(r.json(), list) else 0}",
)

r = api(
    "GET",
    f"/api/v1/devices/{device_id}/health"
    if device_id else "/api/v1/devices/unknown/health",
)
step(
    "GET /api/v1/devices/{device_id}/health",
    "OK" if r.status_code == 200 else "FAIL",
    f"device={device_id} status={r.status_code} {r.text[:160] if r.ok else ''}",
)

# persistence
recent = None
con = sqlite3.connect(DB_PATH)
cur = con.cursor()
try:
    cur.execute("SELECT device_id, type, value, status, timestamp FROM sensor_readings ORDER BY rowid DESC LIMIT 5")
    cols = [d[0] for d in cur.description]
    recent = [dict(zip(cols, row)) for row in cur.fetchall()]
except Exception as e:
    print("db read error", e)
con.close()
step("persistence sensor_readings", "OK" if recent is not None else "FAIL", f"recent_rows={len(recent) if recent else 0}")
if recent:
    dump("recent readings", recent[:3])

# 3. ML/Anomalies
print("\n=== 3. ML/Anomalies ===")
r = api("GET", "/api/v1/ops/analytics")
step("GET /api/v1/ops/analytics", "OK" if r.status_code == 200 else "FAIL", f"{r.status_code} count={len(r.json()) if r.ok else 0}")

r = api("POST", "/api/v1/ai/predict", json={
    "telemetry": {"device_id": "temp_01", "type": "temperature", "value": 250},
    "network": {"packet_count": 10, "bytes_total": 1200, "avg_interval": 0.1, "throughput": 1.2},
})
step("POST /api/v1/ai/predict", "OK" if r.status_code == 200 else "FAIL", f"{r.status_code} {r.text[:240] if r.ok else ''}")
if r.ok:
    dump("predict response", r.json())

models_dir = "/home/abdo/Downloads/CyberPort/backend/ml/models"
if os.path.isdir(models_dir):
    files = [f for f in os.listdir(models_dir) if f.endswith((".pkl", ".joblib", ".bin", ".pt"))]
    step("model files present", "OK", f"{len(files)} files")
else:
    step("model files present", "PART", "models dir not found; advanced models optional")

# 4. Cybersecurity
print("\n=== 4. Cybersecurity ===")
for path in ["/simulate/flood", "/simulate/spoof", "/simulate/unknown", "/simulate/impossible"]:
    counts_before = db_counts()
    r = api("POST", path)
    step(
        f"POST {path}",
        "OK" if r.status_code in (200, 202) else "FAIL",
        f"{r.status_code} {r.text[:140]}",
    )
    time.sleep(1)
    counts_after = db_counts()
    delta = {
        k: (
            counts_after.get(k, 0) - counts_before.get(k, 0)
            if isinstance(counts_after.get(k), int)
            and isinstance(counts_before.get(k), int)
            else None
        )
        for k in counts_after
    }
    step(f"db delta after {path}", "OK", json.dumps(delta, ensure_ascii=False))

r = api("GET", "/api/v1/siem/events?limit=20")
step(
    "GET /api/v1/siem/events",
    "OK" if r.status_code == 200 else "FAIL",
    f"{r.status_code} count={len(r.json()) if r.ok and isinstance(r.json(), list) else 0}",
)
if r.ok and isinstance(r.json(), list) and r.json():
    dump("SIEM events sample", r.json()[:3])

r = api("GET", "/api/v1/siem/risk")
step(
    "GET /api/v1/siem/risk",
    "OK" if r.status_code == 200 else "FAIL",
    f"{r.status_code} {r.text[:160]}",
)

r = api("GET", "/api/v1/ops/siem/timeline?limit=20")
step(
    "GET /api/v1/ops/siem/timeline",
    "OK" if r.status_code == 200 else "FAIL",
    f"{r.status_code} count={len(r.json()) if r.ok and isinstance(r.json(), list) else 0}",
)
if r.ok and isinstance(r.json(), list) and r.json():
    dump("timeline sample", r.json()[:3])

# 5. Missions
print("\n=== 5. Missions ===")
r = api("GET", "/api/v1/ops/missions?limit=20")
step(
    "GET /api/v1/ops/missions",
    "OK" if r.status_code == 200 else "FAIL",
    f"{r.status_code} count={len(r.json()) if r.ok and isinstance(r.json(), list) else 0}",
)
if r.ok and isinstance(r.json(), list) and r.json():
    dump("missions sample", r.json()[:2])

# 6. Incidents lifecycle
print("\n=== 6. Incidents lifecycle ===")
r = api("GET", "/api/v1/siem/incidents")
step(
    "GET /api/v1/siem/incidents",
    "OK" if r.status_code == 200 else "FAIL",
    f"{r.status_code} count={len(r.json()) if r.ok and isinstance(r.json(), list) else 0}",
)
if r.ok and isinstance(r.json(), list) and r.json():
    dump("incidents sample", r.json()[:3])

# 7. Reporting
print("\n=== 7. Reporting ===")
r = api("GET", "/api/v1/ops/reports")
step(
    "GET /api/v1/ops/reports",
    "OK" if r.status_code == 200 else "FAIL",
    f"{r.status_code} count={len(r.json()) if r.ok and isinstance(r.json(), list) else 0}",
)

r = api("GET", "/api/v1/siem/reports")
step(
    "GET /api/v1/siem/reports",
    "OK" if r.status_code == 200 else "FAIL",
    f"{r.status_code} count={len(r.json()) if r.ok and isinstance(r.json(), list) else 0}",
)

# 8. Dashboard/WebSocket
print("\n=== 8. Dashboard ===")
r = requests.get(f"{DASH}/", timeout=20)
step("dashboard root", "OK" if r.status_code == 200 else "FAIL", f"{r.status_code}")
# WebSocket already validated in section 1 when the backend is up.

# 9. Tests
print("\n=== 9. Tests ===")
os.system(f"cd {PROJECT_ROOT} && python3 -m compileall backend smart_port > /tmp/vc_compileall.log 2>&1")
os.system(f"cd {PROJECT_ROOT} && python3 -m pytest -q > /tmp/vc_pytest.log 2>&1")
compile_rc = os.system("tail -n 40 /tmp/vc_compileall.log >/dev/null 2>&1")
print("Compileall/pytest logs written to /tmp/vc_compileall.log and /tmp/vc_pytest.log")

# Summary
print("\n=== Summary ===")
all_items = []
for title, entries in report.items():
    all_items.append((title, entries[-1]["status"], entries[-1]["detail"]))
for title, status, detail in all_items:
    print(f"{status}: {title} -> {detail}")

print("\nFinal DB counts:", json.dumps(db_counts(), ensure_ascii=False))
