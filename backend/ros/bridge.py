"""ROS2/Gazebo mission boundary with SIEM audit logging."""
from smart_port.mission.ros2_bridge import Ros2Bridge

def dispatch_mission(mission: dict) -> bool:
    dispatched = Ros2Bridge().dispatch(mission)
    try:
        from backend.database import SessionLocal
        from backend.schemas.siem import SiemEventIn
        from backend.siem.platform import SmartPortSiem
        db = SessionLocal()
        try:
            SmartPortSiem(db).collect(SiemEventIn(source="ros2", event_type="mission_dispatch",
                message="ROS2 mission dispatched" if dispatched else "ROS2 unavailable; MQTT fallback active",
                device_id=mission.get("drone_id"), payload={"mission_id": mission.get("mission_id")}))
        finally:
            db.close()
    except Exception:
        pass
    return dispatched

__all__ = ["Ros2Bridge", "dispatch_mission"]
