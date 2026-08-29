"""MQTT autonomous-drone simulator used when ROS2/Gazebo is unavailable.

The Paho callbacks deliberately do only validation and worker scheduling.  The
mission worker owns all movement, so a QoS redelivery can never start a second
flight.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

BROKER = os.getenv("SMART_PORT_MQTT_HOST", "localhost")
PORT = int(os.getenv("SMART_PORT_MQTT_PORT", "1883"))
DRONE_ID = os.getenv("SMART_PORT_DRONE_ID", "drone_01")
TOKEN = os.getenv("SMART_PORT_DRONE_TOKEN", "tk_drone_secure_001")
INTERVAL = float(os.getenv("SMART_PORT_DRONE_TELEMETRY_INTERVAL", "2"))
STEP_SECONDS = float(os.getenv("SMART_PORT_DRONE_STEP_SECONDS", "0.5"))
LOW_BATTERY = float(os.getenv("SMART_PORT_DRONE_LOW_BATTERY", "15"))
MISSION_TOPIC = "drone/mission"

logging.basicConfig(level=os.getenv("SMART_PORT_LOG_LEVEL", "INFO"), format="%(asctime)s %(message)s")
logger = logging.getLogger("drone.simulator")

state: dict[str, Any] = {"x": 0.0, "y": 0.0, "altitude": 0.0, "battery": 100.0,
                         "status": "idle", "mission_id": None, "mission_status": None}
state_lock = threading.RLock()
mission_active = threading.Event()
stop_event = threading.Event()
connected_event = threading.Event()
subscribed_event = threading.Event()
worker_thread: threading.Thread | None = None
mqtt_loop_started = False
subscription_mid: int | None = None
last_progress_log = 0.0
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=os.getenv("SMART_PORT_DRONE_CLIENT_ID", "drone_simulator"))
except AttributeError:
    client = mqtt.Client(client_id=os.getenv("SMART_PORT_DRONE_CLIENT_ID", "drone_simulator"))


def _log_rejection(reason: str) -> None:
    logger.warning("[DRONE] mission rejected: reason=%s", reason)
    _publish_event("mission_rejected", reason=reason)


def _publish_event(event_type: str, **details: Any) -> None:
    """Publish operational evidence without making the callback do work."""
    if not connected_event.is_set():
        return
    payload = {"device_id": DRONE_ID, "type": "drone_event", "token": TOKEN,
               "event_type": event_type, "timestamp": time.time(), **details}
    result = client.publish("drone/event", json.dumps(payload), qos=1)
    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        logger.warning("[DRONE] event publish failed event=%s rc=%s", event_type, result.rc)


def _validate_mission(payload: bytes) -> tuple[str, list[dict[str, float]]] | None:
    try:
        mission = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _log_rejection(f"invalid JSON ({exc})")
        return None
    if not isinstance(mission, dict):
        _log_rejection("invalid JSON object")
        return None
    if mission.get("drone_id") != DRONE_ID:
        _log_rejection("wrong drone_id")
        return None
    if mission.get("token") != TOKEN:
        _log_rejection("invalid token")
        return None
    mission_id, waypoints = mission.get("mission_id"), mission.get("waypoints")
    if not isinstance(mission_id, str) or not mission_id.strip():
        _log_rejection("missing mission_id")
        return None
    if not isinstance(waypoints, list) or not waypoints:
        _log_rejection("invalid waypoints")
        return None
    validated: list[dict[str, float]] = []
    try:
        for point in waypoints:
            if not isinstance(point, dict):
                raise TypeError("waypoint is not an object")
            validated.append({"x": float(point["x"]), "y": float(point["y"]),
                              "altitude": max(0.0, float(point.get("altitude", 10))),
                              "dwell_seconds": max(0.0, float(point.get("dwell_seconds", 0)))})
    except (KeyError, TypeError, ValueError) as exc:
        _log_rejection(f"invalid waypoint format ({exc})")
        return None
    logger.info("[DRONE] mission validation OK: %s", mission_id)
    return mission_id, validated


def _move_to(target_x: float, target_y: float, altitude: float, *, enforce_low_battery: bool = True) -> bool:
    """Move in one-unit increments. Returns False when stopping/low battery."""
    while not stop_event.is_set():
        with state_lock:
            dx, dy = target_x - state["x"], target_y - state["y"]
            if abs(dx) <= 0.5 and abs(dy) <= 0.5:
                state.update(x=target_x, y=target_y, altitude=altitude)
                return True
            state["x"] += max(-1.0, min(1.0, dx))
            state["y"] += max(-1.0, min(1.0, dy))
            # Altitude changes gradually as well; this avoids a visual teleport.
            state["altitude"] += max(-1.0, min(1.0, altitude - state["altitude"]))
            state["battery"] = max(0.0, state["battery"] - 0.1)
            global last_progress_log
            now = time.monotonic()
            if now - last_progress_log >= 2:
                last_progress_log = now
                logger.info("[DRONE] position=(%.1f,%.1f,%.1f) battery=%.1f", state["x"], state["y"],
                            state["altitude"], state["battery"])
            if enforce_low_battery and state["battery"] <= LOW_BATTERY:
                logger.warning("[DRONE] battery low; returning home")
                return False
        time.sleep(STEP_SECONDS)
    return False


def _fly(mission_id: str, waypoints: list[dict[str, float]]) -> None:
    aborted = False
    try:
        for index, waypoint in enumerate(waypoints, start=1):
            logger.info("[DRONE] flying -> waypoint %s/%s", index, len(waypoints))
            if not _move_to(waypoint["x"], waypoint["y"], waypoint["altitude"]):
                aborted = stop_event.is_set()
                break
            with state_lock:
                state.update(status="inspecting", mission_status="inspecting")
            logger.info("[DRONE] waypoint %s reached", index)
            logger.info("[DRONE] inspection started")
            if stop_event.wait(waypoint["dwell_seconds"]):
                aborted = True
                break
        with state_lock:
            state.update(status="returning_home", mission_status="returning_home")
        logger.info("[DRONE] returning HOME")
        reached_home = _move_to(0.0, 0.0, 0.0, enforce_low_battery=False)
        with state_lock:
            if reached_home:
                state.update(x=0.0, y=0.0, altitude=0.0)
            state.update(status="idle", mission_status="aborted" if aborted or not reached_home else "completed",
                         mission_id=None)
        if reached_home:
            logger.info("[DRONE] HOME reached")
        logger.info("[DRONE] mission %s %s", mission_id, "aborted" if aborted else "completed")
        _publish_event("mission_aborted" if aborted or not reached_home else "mission_completed", mission_id=mission_id)
    except Exception:
        logger.exception("[DRONE] mission worker failed id=%s", mission_id)
        with state_lock:
            state.update(status="idle", mission_status="aborted", mission_id=None)
    finally:
        mission_active.clear()


def on_message(_client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
    global worker_thread
    if message.topic != MISSION_TOPIC:
        logger.debug("[DRONE] message ignored: wrong topic=%s", message.topic)
        return
    mission_hint = "unknown"
    try:
        mission_hint = json.loads(message.payload.decode("utf-8")).get("mission_id", "unknown")
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        pass
    logger.info("[DRONE] mission received: %s", mission_hint)
    validated = _validate_mission(message.payload)
    if validated is None:
        return
    mission_id, waypoints = validated
    with state_lock:
        if mission_active.is_set():
            _log_rejection("mission already active")
            return
        mission_active.set()
        state.update(mission_id=mission_id, status="flying", mission_status="active")
        worker_thread = threading.Thread(target=_fly, args=(mission_id, waypoints), daemon=True,
                                         name=f"drone-mission-{mission_id}")
    worker_thread.start()
    logger.info("[DRONE] mission started: %s", mission_id)
    _publish_event("mission_started", mission_id=mission_id)


def on_connect(mqtt_client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any = None) -> None:
    global subscription_mid
    if reason_code != 0:
        logger.error("[DRONE] MQTT connection refused: %s", reason_code)
        return
    connected_event.set()
    client_id = mqtt_client._client_id.decode("utf-8", errors="replace")
    logger.info("[DRONE] MQTT connected host=%s port=%s client_id=%s", BROKER, PORT, client_id)
    result, subscription_mid = mqtt_client.subscribe(MISSION_TOPIC, qos=1)
    if result == mqtt.MQTT_ERR_SUCCESS:
        logger.info("[DRONE] subscription requested: %s", MISSION_TOPIC)
    else:
        logger.error("[DRONE] subscription failed topic=%s rc=%s", MISSION_TOPIC, result)


def on_disconnect(_client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any = None) -> None:
    connected_event.clear()
    subscribed_event.clear()
    logger.warning("[DRONE] MQTT disconnected reason=%s", reason_code)


def on_subscribe(_client: mqtt.Client, _userdata: Any, mid: int, reason_codes: list[Any], _properties: Any = None) -> None:
    if mid != subscription_mid or not reason_codes or any(getattr(code, "is_failure", False) for code in reason_codes):
        logger.error("[DRONE] subscription rejected topic=%s mid=%s reasons=%s", MISSION_TOPIC, mid, reason_codes)
        return
    subscribed_event.set()
    logger.info("[DRONE] subscribed: %s", MISSION_TOPIC)


def publish_loop() -> None:
    logger.info("[DRONE] telemetry started interval=%ss", INTERVAL)
    last_wait_log = 0.0
    while not stop_event.is_set():
        with state_lock:
            snapshot = state.copy()
        now = time.time()
        payload = {"device_id": DRONE_ID, "type": "drone", "token": TOKEN, **snapshot, "timestamp": now}
        for topic, body in (("drone/telemetry", payload),
                            ("drone/gps", {"device_id": DRONE_ID, "type": "drone_gps", "token": TOKEN,
                                           "latitude": snapshot["y"], "longitude": snapshot["x"], "altitude": snapshot["altitude"], "timestamp": now}),
                            ("drone/camera", {"device_id": DRONE_ID, "type": "camera_stream", "token": TOKEN,
                                              "stream_id": f"{DRONE_ID}_camera", "active": True, "timestamp": now})):
            result = client.publish(topic, json.dumps(body), qos=1 if topic == "drone/telemetry" else 0)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                logger.warning("[DRONE] telemetry publish failed topic=%s rc=%s", topic, result.rc)
        if not mission_active.is_set() and time.monotonic() - last_wait_log >= 30:
            last_wait_log = time.monotonic()
            logger.info("[DRONE] waiting for mission...")
        stop_event.wait(INTERVAL)


def start() -> None:
    """Start Paho first, then wait briefly for the broker subscription."""
    global mqtt_loop_started
    stop_event.clear()
    connected_event.clear()
    subscribed_event.clear()
    client.on_connect, client.on_disconnect, client.on_message, client.on_subscribe = on_connect, on_disconnect, on_message, on_subscribe
    logger.info("[DRONE] starting simulator")
    logger.info("[DRONE] broker=%s:%s", BROKER, PORT)
    logger.info("[DRONE] drone_id=%s", DRONE_ID)
    logger.info("[DRONE] connecting MQTT...")
    client.connect_async(BROKER, PORT, 60)
    client.loop_start()
    mqtt_loop_started = True
    logger.info("[DRONE] MQTT loop started")
    if not subscribed_event.wait(timeout=10):
        raise RuntimeError("Drone MQTT subscription was not confirmed within 10 seconds")
    logger.info("[DRONE] simulator ready")
    publish_loop()


def shutdown() -> None:
    global mqtt_loop_started
    stop_event.set()
    if worker_thread is not None and worker_thread.is_alive():
        worker_thread.join(timeout=2)
    if mqtt_loop_started:
        client.disconnect()
        client.loop_stop()
        mqtt_loop_started = False


if __name__ == "__main__":
    try:
        start()
    except KeyboardInterrupt:
        logger.info("[DRONE] shutdown requested")
    finally:
        shutdown()
