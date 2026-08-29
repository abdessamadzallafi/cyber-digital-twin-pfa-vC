"""Mission planning policy for inspection flights."""
from dataclasses import dataclass
import time
from backend.ros.drone_models import DroneMission, Waypoint


INSPECTION_ZONES = {
    "grue_G01": (2.0, 10.0), "portique_P01": (4.5, 10.0), "camera_Q01": (9.0, 10.0),
    "entrepot_E01": (18.0, 14.0), "station_H01": (14.0, 3.0), "portail_N01": (22.0, 6.0),
    "camion_C12": (26.0, 8.0), "parking_P01": (26.0, 10.0),
}


class MissionPlanner:
    def __init__(self, home: Waypoint | None = None):
        self.home = home or Waypoint(0.0, 0.0, altitude=0.0)

    def plan_inspection(self, target_device: str, mission_type: str = "inspection", priority: str = "medium") -> DroneMission:
        x, y = INSPECTION_ZONES.get(target_device, (5.0, 5.0))
        mission_id = f"drone_miss_{int(time.time() * 1000)}"
        # Approach and orbit-style inspection waypoints provide safe camera coverage.
        waypoints = [Waypoint(x - 2, y - 2, 10), Waypoint(x, y, 12, dwell_seconds=3), Waypoint(x + 2, y + 2, 10)]
        return DroneMission(mission_id, target_device, mission_type, waypoints, self.home, priority)
