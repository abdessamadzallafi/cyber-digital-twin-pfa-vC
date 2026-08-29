"""Optional ROS2 interface; domain code remains usable without rclpy/Gazebo."""
from typing import Mapping


class ROS2Interface:
    def __init__(self):
        try:
            import rclpy  # noqa: F401
            self.available = True
        except ImportError:
            self.available = False

    def send_mission(self, mission: Mapping) -> bool:
        # A real deployment maps this to a ROS2 action client (NavigateToPose).
        return self.available

    def publish(self, topic: str, payload: Mapping) -> bool:
        return self.available
