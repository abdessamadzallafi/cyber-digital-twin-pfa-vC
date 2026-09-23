"""Non-blocking MQTT ingress for sensor and autonomous-drone messages."""
import asyncio
import json
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from backend.core.config import settings as backend_settings
from backend.database import Alert, Mission, SensorReading, SessionLocal
from backend.decision_engine import make_decision
from backend.logger import logger
from backend.network.network_monitor import process_network_data
from backend.ros.drone_manager import drone_manager
from backend.ros.drone_models import is_valid_mission_transition
from backend.services.action_dispatcher import ActionDispatcher
from backend.siem.platform import SmartPortSiem
from backend.schemas.siem import SiemEventIn
from smart_port.communication.device_gateway import DeviceGateway
from smart_port.data.data_lake import write_event
from smart_port.config import settings
from backend.events.normalizer import EventNormalizer
from backend.events.contracts import Transport as EventTransport

update_queue: asyncio.Queue[dict[str, Any]] | None = None
ingress_queue: asyncio.Queue[dict[str, Any]] | None = None
loop: asyncio.AbstractEventLoop | None = None
mqtt_client: mqtt.Client | None = None
metrics = {"mqtt_messages_received": 0, "mqtt_messages_processed": 0, "mqtt_errors": 0,
           "drone_telemetry_received": 0, "websocket_dropped": 0, "mqtt_connected": False}


def on_connect(client, _userdata, _flags, reason_code, _properties=None):
    if reason_code == 0:
        metrics["mqtt_connected"] = True
        logger.info("MQTT connected host=%s port=%s", settings.mqtt_host, settings.mqtt_port)
        client.subscribe("port/#", qos=backend_settings.mqtt_qos)
        client.subscribe("drone/#", qos=backend_settings.mqtt_qos)
    else:
        logger.error("MQTT connection refused reason=%s", reason_code)


def on_disconnect(_client, _userdata, *args):
    metrics["mqtt_connected"] = False
    logger.warning("MQTT disconnected; reconnecting automatically")


def _enqueue_message(data: dict[str, Any]) -> None:
    if ingress_queue is None:
        return
    try:
        ingress_queue.put_nowait(data)
    except asyncio.QueueFull:
        metrics["mqtt_errors"] += 1
        logger.warning("MQTT ingress queue full; message dropped topic=%s", data.get("mqtt_topic"))


def on_message(_client, _userdata, msg):
    """Paho network-thread callback: decode and enqueue only, never access DB/ML."""
    metrics["mqtt_messages_received"] += 1
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("payload must be a JSON object")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        metrics["mqtt_errors"] += 1
        logger.warning("Invalid MQTT payload topic=%s error=%s", msg.topic, exc)
        return
    data["mqtt_topic"] = msg.topic
    if loop is None or loop.is_closed():
        logger.error("MQTT message discarded: application loop unavailable")
        return
    loop.call_soon_threadsafe(_enqueue_message, data)


async def mqtt_worker() -> None:
    assert ingress_queue is not None
    while True:
        data = await ingress_queue.get()
        try:
            await process_message(data)
            metrics["mqtt_messages_processed"] += 1
        except Exception:
            metrics["mqtt_errors"] += 1
            logger.exception("MQTT message processing failed topic=%s", data.get("mqtt_topic"))
        finally:
            ingress_queue.task_done()


async def _publish_dashboard(message: dict[str, Any]) -> None:
    if update_queue is None:
        return
    try:
        update_queue.put_nowait(message)
    except asyncio.QueueFull:
        metrics["websocket_dropped"] += 1
        logger.warning("WebSocket queue full; update dropped device=%s", message.get("device_id"))


def _drone_dashboard_payload(data: dict[str, Any], state: dict[str, Any] | None = None,
                            status: str | None = None) -> dict[str, Any]:
    state = state if isinstance(state, dict) else {}
    position = {
        "x": data.get("x", state.get("x")),
        "y": data.get("y", state.get("y")),
        "altitude": data.get("altitude", state.get("altitude")),
    }
    mission_id = data.get("mission_id", state.get("mission_id"))
    return {
        "type": "drone_telemetry",
        "event": "drone_telemetry",  # compatibility alias for existing consumers
        "mission_id": mission_id,
        "drone_id": data.get("device_id", state.get("drone_id")),
        "status": status or data.get("mission_status") or data.get("status") or state.get("status"),
        "position": position,
        "battery": data.get("battery", state.get("battery")),
        "timestamp": data.get("timestamp", time.time()),
    }


def _update_mission_from_telemetry(db, data: dict[str, Any]) -> None:
    mission_id = data.get("mission_id")
    status = data.get("mission_status")
    if mission_id and status:
        mission = db.query(Mission).filter(Mission.mission_id == mission_id).first()
        if mission and is_valid_mission_transition(mission.status, status):
            mission.status = status
    elif data.get("status") == "idle":
        active = (db.query(Mission).filter(Mission.drone_id == settings.drone_id)
                  .filter(Mission.status.in_(("created", "active", "flying", "inspecting", "returning_home"))).first())
        if active:
            active.status = "completed"


def _update_mission_from_event(db, data: dict[str, Any]) -> str | None:
    status_by_event = {
        "mission_started": "active",
        "mission_completed": "completed",
        "mission_aborted": "aborted",
    }
    status = status_by_event.get(data.get("event_type"))
    mission_id = data.get("mission_id")
    mission = None
    if status and mission_id:
        mission = db.query(Mission).filter(Mission.mission_id == mission_id).first()
        if mission and is_valid_mission_transition(mission.status, status):
            mission.status = status
            return status
    return None


async def _process_drone_telemetry(db, data: dict[str, Any]) -> None:
    """Telemetry is state/evidence only. It is intentionally not sent to ML dispatch."""
    metrics["drone_telemetry_received"] += 1
    device_id = data.get("device_id", settings.drone_id)
    reading = SensorReading(device_id=device_id, type=data.get("type", "drone"), value=data.get("x"),
                            latitude=data.get("y"), longitude=data.get("battery"), status=data.get("status"),
                            timestamp=data.get("timestamp", time.time()), ip_src=data.get("ip_src", "unknown"),
                            mac_src=data.get("mac_src", "unknown"), port_src=data.get("port_src", 1883),
                            packet_size=len(json.dumps(data)))
    db.add(reading)
    _update_mission_from_telemetry(db, data)
    db.commit()
    state = drone_manager.update_telemetry(data)
    await _publish_dashboard(_drone_dashboard_payload(data, state))


async def process_message(raw_data: dict[str, Any]) -> None:
    data = DeviceGateway.normalize(raw_data, transport="mqtt")
    common_event = EventNormalizer.normalize(raw_data, EventTransport.MQTT)
    device_id, dev_type, topic = data["device_id"], data["type"], data.get("mqtt_topic", "")
    db = SessionLocal()
    try:
        write_event("telemetry", data)
        if dev_type in {"drone", "drone_gps", "camera_stream"}:
            await _process_drone_telemetry(db, data)
            return
        if dev_type == "drone_event":
            status = _update_mission_from_event(db, data)
            state = drone_manager.update_mission_event(data)
            db.add(Alert(device_id=device_id, alert_type=f"drone_{data.get('event_type', 'event')}",
                         message=data.get("message", "Drone event"), timestamp=time.time(), severity="info"))
            db.commit()
            if status:
                await _publish_dashboard(_drone_dashboard_payload(data, state, status))
            return

        packet_size = len(json.dumps(data))
        db.add(SensorReading(device_id=device_id, type=dev_type, value=data.get("value"), unit=data.get("unit"),
                             status=data.get("status"), people_count=data.get("people_count"),
                             latitude=data.get("latitude"), longitude=data.get("longitude"),
                             timestamp=data.get("timestamp", time.time()), ip_src=data.get("ip_src", "unknown"),
                             mac_src=data.get("mac_src", "unknown"), port_src=data.get("port_src", 1883), packet_size=packet_size))
        net_info = process_network_data(device_id, data.get("ip_src", "unknown"), data.get("mac_src", "unknown"), packet_size)
        decision = make_decision(data, net_info)
        for alert_type, message in decision["alerts"]:
            SmartPortSiem(db).collect(SiemEventIn(source="network" if alert_type in {"network_flood", "unknown_ip"} else "sensor",
                                                   event_type=alert_type, message=message, device_id=device_id,
                                                   severity="high" if decision["threat_level"] == "red" else "medium"),
                                      manage_incident=False)
        db.commit()
        action = None
        if decision["anomaly"] or decision["threat_level"] == "red":
            security_types = {"flood", "network_flood", "unknown_ip", "bad_token", "wrong_topic", "unknown_device"}
            trigger = "network_attack" if any(kind in security_types for kind, _ in decision["alerts"]) else "ml_anomaly"
            action = ActionDispatcher(db).handle_detection(device_id, trigger,
                "critical" if decision["threat_level"] == "red" else "high",
                "; ".join(message for _, message in decision["alerts"]) or f"Anomaly on {dev_type}",
                decision.get("dispatch_recommended", False),
                create_incident=trigger != "ml_anomaly")
        await _publish_dashboard({"event": "telemetry", "device_id": device_id, "type": dev_type,
                                  "status": decision["threat_level"], "last_value": data.get("value") or data.get("status"),
                                  "alerts": [message for _, message in decision["alerts"]], "anomaly_score": decision["anomaly_score"],
                                  "network": net_info, "action": action, "timestamp": data["timestamp"]})
    finally:
        db.close()


def start_mqtt(loop_ref: asyncio.AbstractEventLoop, queue: asyncio.Queue[dict[str, Any]]) -> None:
    global loop, update_queue, ingress_queue, mqtt_client
    loop, update_queue = loop_ref, queue
    ingress_queue = asyncio.Queue(maxsize=backend_settings.websocket_queue_size)
    loop.call_soon_threadsafe(lambda: asyncio.create_task(mqtt_worker()))
    try:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="smart_port_listener")
    except AttributeError:
        mqtt_client = mqtt.Client(client_id="smart_port_listener")
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message
    mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)

    if settings.mqtt_tls:
        mqtt_client.tls_set(
            ca_certs=settings.mqtt_ca_file
        )
    try:
        mqtt_client.connect_async(settings.mqtt_host, settings.mqtt_port, 60)
        mqtt_client.loop_start()
    except Exception:
        logger.exception("MQTT listener failed to start")


def stop_mqtt() -> None:
    if mqtt_client is not None and mqtt_client._thread is not None and mqtt_client._thread.is_alive():
        try:
            mqtt_client.disconnect()
        except Exception:
            logger.debug("MQTT disconnect during shutdown raised", exc_info=True)
        try:
            mqtt_client.loop_stop()
        except RuntimeError:
            logger.debug("MQTT loop_stop skipped: thread not started")
