"""Drone telemetry publisher using the MQTT/ROS2 transport boundary."""
from typing import Callable
from backend.ros.drone_models import DroneState


class TelemetryPublisher:
    def __init__(self, publish: Callable[[str, dict], None] | None = None):
        self.publish = publish or (lambda _topic, _payload: None)

    def publish_state(self, state: DroneState) -> dict:
        payload = {"device_id": state.drone_id, "type": "drone", "x": state.x, "y": state.y,
                   "battery": state.battery, "altitude": state.altitude, "status": state.status,
                   "mission_id": state.mission_id, "timestamp": state.updated_at}
        self.publish("drone/telemetry", payload)
        return payload
