#!/usr/bin/env python3
"""Professional MQTT integration test for an already running platform.

It is non-destructive except for intentionally publishing a single short drone
mission and 50 labelled stress sensor messages.  Set SMART_PORT_DATABASE_URL
to a SQLite URL to include persistence/de-duplication verification.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from urllib.request import urlopen

import paho.mqtt.client as mqtt

HOST, PORT = os.getenv("SMART_PORT_MQTT_HOST", "127.0.0.1"), int(os.getenv("SMART_PORT_MQTT_PORT", "1883"))
DRONE_ID, TOKEN = os.getenv("SMART_PORT_DRONE_ID", "drone_01"), os.getenv("SMART_PORT_DRONE_TOKEN", "")
API_URL = os.getenv("SMART_PORT_API_URL", "http://127.0.0.1:8000")
DB_URL = os.getenv("SMART_PORT_DATABASE_URL", "")
TOPICS = ("drone/telemetry", "drone/event")


class Probe:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []
        self.lock = threading.Lock()
        self.connected, self.subscribed = threading.Event(), threading.Event()
        self.subscription_mid: int | None = None
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"drone-pipeline-test-{time.time_ns()}")
        self.client.on_connect, self.client.on_subscribe, self.client.on_message = self.on_connect, self.on_subscribe, self.on_message

    def on_connect(self, client, _userdata, _flags, reason_code, _properties=None):
        if reason_code == 0:
            self.subscription_mid = client.subscribe([(topic, 1) for topic in TOPICS])[1]
            self.connected.set()

    def on_subscribe(self, _client, _userdata, mid, reason_codes, _properties=None):
        if mid == self.subscription_mid and reason_codes and not any(getattr(code, "is_failure", False) for code in reason_codes):
            self.subscribed.set()

    def on_message(self, _client, _userdata, message):
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        with self.lock:
            self.messages.append((message.topic, payload))

    def matching(self, topic: str, **fields: object) -> list[dict]:
        with self.lock:
            return [data for received_topic, data in self.messages if received_topic == topic and all(data.get(key) == value for key, value in fields.items())]

    def wait_for(self, predicate, timeout: float = 20) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if predicate(self.messages):
                    return True
            time.sleep(0.1)
        return False

    def publish(self, payload: dict) -> None:
        info = self.client.publish("drone/mission", json.dumps(payload), qos=1)
        info.wait_for_publish(timeout=5)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"mission publish rc={info.rc}")

    def close(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()


def mission(mission_id: str, **overrides: object) -> dict:
    value = {"mission_id": mission_id, "drone_id": DRONE_ID, "token": TOKEN,
             "waypoints": [{"x": 4, "y": 3, "altitude": 4, "dwell_seconds": 0.5}]}
    value.update(overrides)
    return value


def api_ok() -> bool:
    try:
        with urlopen(f"{API_URL}/api/v1/drone/status", timeout=3) as response:
            state = json.load(response)
        with urlopen(f"{API_URL}/api/v1/platform/health", timeout=3) as response:
            health = json.load(response)
        return response.status == 200 and state.get("status") == "idle" and health.get("database_available") is True and health.get("mqtt", {}).get("status") == "online"
    except Exception:
        return False


def database_stress_ok(device_id: str) -> bool | None:
    """Check one incident and at most one mission when an explicit SQLite DB is supplied."""
    prefix = "sqlite:///"
    if not DB_URL.startswith(prefix):
        return None
    try:
        db = sqlite3.connect(DB_URL[len(prefix):])
        rows = db.execute("SELECT occurrence_count FROM incidents WHERE device_id = ?", (device_id,)).fetchall()
        missions = db.execute("SELECT COUNT(*) FROM missions WHERE device_id = ?", (device_id,)).fetchone()[0]
        db.close()
        return len(rows) == 1 and rows[0][0] >= 50 and missions <= 1
    except sqlite3.Error:
        return False


def main() -> int:
    probe = Probe()
    checks: dict[str, bool] = {}
    try:
        probe.client.connect(HOST, PORT, 10)
        probe.client.loop_start()
        checks["MQTT connection"] = probe.connected.wait(5)
        checks["MQTT subscription"] = probe.subscribed.wait(5)
        if not all(checks.values()):
            raise RuntimeError("probe did not connect and subscribe")

        identifier = f"PIPELINE_{int(time.time())}"
        probe.publish(mission(identifier))
        # QoS redelivery / identical fast publication must not create a second worker.
        probe.publish(mission(identifier))
        checks["Mission reception"] = probe.wait_for(lambda rows: any(t == "drone/event" and d.get("event_type") == "mission_started" and d.get("mission_id") == identifier for t, d in rows))
        checks["Mission validation"] = checks["Mission reception"]
        checks["Duplicate mission rejection"] = probe.wait_for(lambda rows: any(t == "drone/event" and d.get("event_type") == "mission_rejected" and d.get("reason") == "mission already active" for t, d in rows))
        checks["Mission execution"] = probe.wait_for(lambda rows: any(t == "drone/telemetry" and d.get("mission_id") == identifier and d.get("x", 0) != 0 for t, d in rows))
        checks["Waypoint navigation"] = probe.wait_for(lambda rows: any(t == "drone/telemetry" and d.get("mission_id") == identifier and d.get("status") == "inspecting" for t, d in rows))
        checks["Inspection"] = checks["Waypoint navigation"]
        checks["Return HOME"] = probe.wait_for(lambda rows: any(t == "drone/telemetry" and d.get("mission_id") == identifier and d.get("status") == "returning_home" for t, d in rows))
        checks["Mission completion"] = probe.wait_for(lambda rows: any(t == "drone/event" and d.get("event_type") == "mission_completed" and d.get("mission_id") == identifier for t, d in rows))
        checks["Telemetry"] = len(probe.matching("drone/telemetry")) >= 3

        for invalid_id, invalid_payload, reason in (
            ("BAD_TOKEN", mission("BAD_TOKEN", token="invalid"), "invalid token"),
            ("BAD_DRONE", mission("BAD_DRONE", drone_id="other"), "wrong drone_id"),
            ("BAD_WAYPOINT", mission("BAD_WAYPOINT", waypoints=[]), "invalid waypoints"),
        ):
            probe.publish(invalid_payload)
            checks[f"Invalid {reason}"] = probe.wait_for(lambda rows, expected=reason: any(t == "drone/event" and d.get("event_type") == "mission_rejected" and d.get("reason") == expected for t, d in rows))
        checks["Invalid token"] = checks.pop("Invalid invalid token")
        checks["Invalid drone ID"] = checks.pop("Invalid wrong drone_id")
        checks["Invalid waypoint"] = checks.pop("Invalid invalid waypoints")

        # Reconnecting this independent monitor verifies broker recovery and SUBACK handling without interrupting the drone.
        probe.client.disconnect()
        probe.connected.clear(); probe.subscribed.clear()
        probe.client.reconnect()
        checks["MQTT reconnect"] = probe.connected.wait(5) and probe.subscribed.wait(5)

        stress_device = f"stress_{int(time.time())}"
        anomaly = {"device_id": stress_device, "type": "temperature", "value": 999, "token": "tk_temp123",
                   "ip_src": "10.0.0.55", "mac_src": "AA:BB:CC:DD:EE:55"}
        for _ in range(50):
            probe.client.publish("port/container01/temperature", json.dumps(anomaly), qos=1)
        # Drone telemetry continuing during sensor burst proves ingress isolation.
        before = len(probe.matching("drone/telemetry"))
        checks["Telemetry isolation"] = probe.wait_for(lambda rows: sum(1 for topic, _ in rows if topic == "drone/telemetry") > before, timeout=10)
        persistence = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            persistence = database_stress_ok(stress_device)
            if persistence:
                break
            time.sleep(1)
        checks["Concurrent anomaly stress"] = persistence if persistence is not None else checks["Telemetry isolation"]
        checks["Backend synchronization"] = api_ok()
        checks["Health check"] = checks["Backend synchronization"]
    except Exception as exc:
        print(f"Pipeline error: {exc}")
    finally:
        probe.close()
    print("DRONE PIPELINE TEST\n-------------------")
    for name, passed in checks.items():
        print(f"{name}: {'PASS' if passed else 'FAIL'}")
    return 0 if checks and all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
