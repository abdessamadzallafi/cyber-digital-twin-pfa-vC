"""Transport-neutral edge gateway normalization boundary."""
from typing import Mapping
import time


class DeviceGateway:
    @staticmethod
    def normalize(payload: Mapping, transport: str = "mqtt") -> dict:
        """Create a safe canonical envelope without discarding legacy fields."""
        event = dict(payload)
        event.setdefault("timestamp", time.time())
        event.setdefault("transport", transport)
        event.setdefault("device_id", "unknown")
        event.setdefault("type", "unknown")
        return event
