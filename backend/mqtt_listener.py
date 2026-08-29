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


def _update_mission_from_telemetry(db, data: dict[str, Any]) -> None:
    mission_id = data.get("mission_id")
    status = data.get("mission_status") or data.get("status")
    if mission_id and status:
        mission = db.query(Mission).filter(Mission.mission_id == mission_id).first()
        if mission:
            mission.status = status
    elif data.get("status") == "idle":
        active = (db.query(Mission).filter(Mission.drone_id == settings.drone_id)
                  .filter(Mission.status.in_(("created", "active", "flying", "inspecting", "returning_home"))).first())
        if active:
            active.status = "completed"


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
    await _publish_dashboard({"event": "drone_telemetry", "device_id": device_id, "type": data.get("type"),
                              "status": data.get("status"), "x": data.get("x"), "y": data.get("y"),
                              "altitude": data.get("altitude"), "battery": data.get("battery"),
                              "mission_id": data.get("mission_id"), "mission_status": data.get("mission_status"),
                              "telemetry": data, "drone": state, "timestamp": data.get("timestamp", time.time())})


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
            db.add(Alert(device_id=device_id, alert_type=f"drone_{data.get('event_type', 'event')}",
                         message=data.get("message", "Drone event"), timestamp=time.time(), severity="info"))
            db.commit()
            await _publish_dashboard({"event": "drone_event", "device_id": device_id, "payload": data})
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
            db.add(Alert(device_id=device_id, alert_type=alert_type, message=message, timestamp=time.time(), severity=decision["threat_level"]))
            SmartPortSiem(db).collect(SiemEventIn(source="network" if alert_type in {"network_flood", "unknown_ip"} else "sensor",
                                                   event_type=alert_type, message=message, device_id=device_id,
                                                   severity="high" if decision["threat_level"] == "red" else "medium"),
                                      manage_incident=False)
        db.commit()
        action = None
        if decision["anomaly"] or decision["threat_level"] == "red":
            trigger = "ml_anomaly" if any(kind == "ml_anomaly" for kind, _ in decision["alerts"]) else "network_attack"
            action = ActionDispatcher(db).handle_detection(device_id, trigger,
                "critical" if decision["threat_level"] == "red" else "high",
                "; ".join(message for _, message in decision["alerts"]) or f"Anomaly on {dev_type}",
                decision.get("dispatch_recommended", False))
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
    if mqtt_client is not None:
        mqtt_client.disconnect()
        mqtt_client.loop_stop()
