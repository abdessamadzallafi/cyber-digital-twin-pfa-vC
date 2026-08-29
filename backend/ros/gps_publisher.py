"""GPS publisher using an injected transport callback."""
from typing import Callable
from backend.ros.drone_models import DroneState


class GPSPublisher:
    def __init__(self, publish: Callable[[str, dict], None] | None = None):
        self.publish = publish or (lambda _topic, _payload: None)

    def publish_position(self, state: DroneState) -> dict:
        payload = {"device_id": state.drone_id, "type": "drone_gps", "latitude": state.y, "longitude": state.x,
                   "altitude": state.altitude, "timestamp": state.updated_at}
        self.publish("drone/gps", payload)
        return payload
