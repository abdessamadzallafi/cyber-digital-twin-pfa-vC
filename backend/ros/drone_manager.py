"""Autonomous drone orchestration facade."""
from threading import RLock
import time
from backend.database import SessionLocal, Mission
from backend.mqtt.drone import DroneMQTTInterface
from backend.ros.battery_monitor import BatteryMonitor
from backend.ros.camera_stream import CameraStream
from backend.ros.drone_models import DroneMission, DroneState
from backend.ros.inspection_mission import InspectionMission
from backend.ros.interface import ROS2Interface
from backend.ros.mission_planner import MissionPlanner
from backend.ros.gps_publisher import GPSPublisher
from backend.ros.telemetry_publisher import TelemetryPublisher
from backend.ros.waypoint_navigation import WaypointNavigator
from smart_port.data.data_lake import write_event
from backend.core.config import settings
from backend.logger import logger


class DroneManager:
    def __init__(self, mqtt_interface=None, ros_interface=None):
        self.state = DroneState(drone_id=settings.drone_id)
        self.planner = MissionPlanner()
        self.navigator = WaypointNavigator()
        self.inspection = InspectionMission()
        self.battery = BatteryMonitor()
        self.camera = CameraStream()
        self.mqtt = mqtt_interface or DroneMQTTInterface()
        self.ros = ros_interface or ROS2Interface()
        self.mission: DroneMission | None = None
        self.lock = RLock()
        self.telemetry = TelemetryPublisher(self.mqtt.publish)
        self.gps = GPSPublisher(self.mqtt.publish)

    def create_inspection(self, target_device: str, mission_type: str = "inspection", priority: str = "medium") -> DroneMission:
        with self.lock:
            if self.mission and self.mission.status.value in {"created", "active", "inspecting", "returning_home"}:
                raise RuntimeError(f"Drone already has an active mission {self.mission.mission_id}")
            mission = self.planner.plan_inspection(target_device, mission_type, priority)
            payload = {"mission_id": mission.mission_id, "drone_id": self.state.drone_id,
                       "device_id": target_device, "mission_type": mission_type,
                       "target": {"x": mission.waypoints[1].x, "y": mission.waypoints[1].y},
                       "waypoints": [point.__dict__ for point in mission.waypoints], "token": settings.drone_token,
                       "timestamp": time.time()}
            db = SessionLocal()
            try:
                target = mission.waypoints[1]
                record = Mission(mission_id=mission.mission_id, device_id=target_device, drone_id=self.state.drone_id,
                                 target_x=target.x, target_y=target.y, status="created")
                db.add(record)
                db.commit()
                if not self.mqtt.publish_mission(payload):
                    record.status = "aborted"
                    db.commit()
                    raise RuntimeError("Drone mission was not published to MQTT")
            finally:
                db.close()
            self.ros.send_mission(payload)
            self.mission = mission
            self.state.mission_id = mission.mission_id
            self.state.status = "created"
            write_event("missions", payload)
            logger.info("Drone mission dispatched id=%s target=%s type=%s", mission.mission_id, target_device, mission_type)
            return mission

    def start(self) -> dict:
        with self.lock:
            if not self.mission:
                raise ValueError("No drone mission has been created")
            self.inspection.begin(self.mission)
            self.state.status = "flying"
            return self.status()

    def tick(self, step: float = 1.0) -> dict:
        with self.lock:
            if self.mission and self.mission.status.value in {"active", "returning_home"}:
                self.navigator.update(self.state, self.mission, step)
            self.state.updated_at = time.time()
            battery_decision = self.battery.evaluate(self.state, self.mission)
            if battery_decision.return_home and self.mission:
                self.state.status = "returning_home"
            self.telemetry.publish_state(self.state)
            self.gps.publish_position(self.state)
            return self.status()

    def return_home(self) -> dict:
        with self.lock:
            if self.mission:
                self.navigator.return_home(self.mission)
                self.state.status = "returning_home"
            return self.status()

    def update_telemetry(self, payload: dict) -> dict:
        """Idempotently mirror simulator telemetry; it never dispatches work."""
        with self.lock:
            reported_mission_id = payload.get("mission_id")
            reported_status = payload.get("mission_status")
            for field in ("x", "y", "altitude", "heading", "battery", "status", "mission_id"):
                if field in payload and (payload[field] is not None or field == "mission_id"):
                    setattr(self.state, field, payload[field])
            self.state.updated_at = payload.get("timestamp", time.time())
            if self.mission and (reported_mission_id == self.mission.mission_id or reported_status == "completed"):
                if reported_status == "completed" or (payload.get("status") == "idle" and reported_mission_id is None):
                    self.mission.status = self.mission.status.COMPLETED
                elif reported_status in {"active", "inspecting", "returning_home"}:
                    self.mission.status = self.mission.status.__class__(reported_status)
            decision = self.battery.evaluate(self.state, self.mission)
            return {**self.status(), "battery_return_home": decision.return_home}

    def camera_start(self, url: str | None = None) -> dict:
        with self.lock:
            self.state.camera_stream = self.camera.start(url).get("url")
            return self.camera.as_dict()

    def status(self) -> dict:
        result = self.state.__dict__.copy()
        result["mission_status"] = self.mission.status.value if self.mission else None
        active = self.mission and self.mission.status.value in {"created", "active", "inspecting", "returning_home"}
        result["next_waypoint"] = self.navigator.next_target(self.mission).__dict__ if active else None
        result["ros2_available"] = self.ros.available
        result["camera"] = self.camera.as_dict()
        return result


drone_manager = DroneManager()
