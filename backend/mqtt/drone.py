"""MQTT command/telemetry adapter for the autonomous drone."""
import json
import threading
import paho.mqtt.client as mqtt
from smart_port.config import settings
from backend.core.config import settings as backend_settings


class DroneMQTTInterface:
    def __init__(self, client=None):
        self.client = client
        self.lock = threading.Lock()

    def _client(self):
        if self.client is None:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="drone_manager")
            client.connect(settings.mqtt_host, settings.mqtt_port, 60)
            client.loop_start()
            self.client = client
        return self.client

    def publish(self, topic: str, payload: dict) -> bool:
        try:
            with self.lock:
                result = self._client().publish(topic, json.dumps(payload), qos=backend_settings.mqtt_qos if topic == "drone/mission" else 0)
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    raise RuntimeError(f"MQTT publish failed: rc={result.rc}")
            return True
        except Exception:
            # The caller owns the action lifecycle and can record a rejected dispatch.
            return False

    def publish_mission(self, payload: dict) -> bool:
        return self.publish("drone/mission", payload)
