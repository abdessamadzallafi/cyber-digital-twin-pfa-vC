"""Legacy mission-planner facade.

Existing imports and `/force_mission/{device_id}` remain valid, while all new
missions are planned and dispatched by the autonomous DroneManager.
"""
from backend.ros.drone_manager import drone_manager
from backend.core.config import settings


def create_mission(device_id: str, anomaly_type: str):
    mission = drone_manager.create_inspection(device_id, mission_type=anomaly_type,
                                              priority="high" if anomaly_type == "security" else "medium")
    target = mission.waypoints[1]
    return {
        "mission_id": mission.mission_id,
        "drone_id": drone_manager.state.drone_id,
        "device_id": device_id,
        "anomaly_type": anomaly_type,
        "target": {"x": target.x, "y": target.y},
        "waypoints": [point.__dict__ for point in mission.waypoints],
        "priority": mission.priority,
        "timestamp": mission.created_at,
        "token": settings.drone_token,
    }
