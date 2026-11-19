"""Non-blocking MQTT ingress for SecurIoT-Port telemetry."""
import asyncio
import json
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from backend.core.config import settings as backend_settings
from backend.database import Alert, SensorReading, SessionLocal
from backend.decision_engine import make_decision
from backend.logger import logger
from backend.network.network_monitor import process_network_data
from backend.services.action_dispatcher import ActionDispatcher
from backend.siem.platform import SmartPortSiem
from backend.schemas.siem import SiemEventIn
from smart_port.communication.device_gateway import DeviceGateway
from smart_port.data.data_lake import write_event
from smart_port.config import settings

update_queue: asyncio.Queue[dict[str, Any]] | None = None
ingress_queue: asyncio.Queue[dict[str, Any]] | None = None
loop: asyncio.AbstractEventLoop | None = None
mqtt_client: mqtt.Client | None = None
metrics = {
    "mqtt_messages_received": 0,
    "mqtt_messages_processed": 0,
    "mqtt_errors": 0,
    "websocket_dropped": 0,
    "mqtt_connected": False,
}


def on_connect(client, _userdata, _flags, reason_code, _properties=None):
    if reason_code == 0:
        metrics["mqtt_connected"] = True
        logger.info("MQTT connected host=%s port=%s", settings.mqtt_host, settings.mqtt_port)
        client.subscribe("port/#", qos=backend_settings.mqtt_qos)
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


async def process_message(raw_data: dict[str, Any]) -> None:
    data = DeviceGateway.normalize(raw_data, transport="mqtt")
    # Validate against the identity presented on the wire, then store/publish
    # under the canonical registry id so the dashboard inventory stays truthful.
    from smart_port.edge.device_registry import canonical_device_id

    original_id = data.get("device_id") or "unknown"
    db = SessionLocal()
    try:
        packet_size = len(json.dumps(data))
        net_info = process_network_data(
            original_id,
            data.get("ip_src", "unknown"),
            data.get("mac_src", "unknown"),
            packet_size,
        )
        decision = make_decision(data, net_info)
        device_id = canonical_device_id(original_id)
        data["device_id"] = device_id
        dev_type = data["type"]

        write_event("telemetry", data)
        db.add(SensorReading(device_id=device_id, type=dev_type, value=data.get("value"), unit=data.get("unit"),
                             status=data.get("status"), people_count=data.get("people_count"),
                             latitude=data.get("latitude"), longitude=data.get("longitude"),
                             timestamp=data.get("timestamp", time.time()), ip_src=data.get("ip_src", "unknown"),
                             mac_src=data.get("mac_src", "unknown"), port_src=data.get("port_src", 1883), packet_size=packet_size))
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
            action = ActionDispatcher(db).handle_detection(
                device_id,
                trigger,
                "critical" if decision["threat_level"] == "red" else "high",
                "; ".join(message for _, message in decision["alerts"])
                or f"Anomaly on {dev_type}",
                create_incident=trigger != "ml_anomaly",
            )
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
