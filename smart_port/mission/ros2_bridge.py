"""ROS2 boundary adapter; MQTT simulation remains available when ROS2 is absent."""
from typing import Mapping


class Ros2Bridge:
    def __init__(self):
        try:
            import rclpy  # noqa: F401
            self.available = True
        except ImportError:
            self.available = False

    def dispatch(self, mission: Mapping) -> bool:
        """Extension point for a ROS2 action client; never breaks demo operation."""
        return self.available
