"""Domain objects for autonomous-drone operations."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class DroneMissionStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    INSPECTING = "inspecting"
    RETURNING_HOME = "returning_home"
    COMPLETED = "completed"
    ABORTED = "aborted"


@dataclass(frozen=True)
class Waypoint:
    x: float
    y: float
    altitude: float = 10.0
    dwell_seconds: float = 0.0


@dataclass
class DroneMission:
    mission_id: str
    target_device: str
    mission_type: str
    waypoints: list[Waypoint]
    home: Waypoint
    priority: str = "medium"
    status: DroneMissionStatus = DroneMissionStatus.CREATED
    created_at: float = field(default_factory=time.time)
    current_waypoint: int = 0


@dataclass
class DroneState:
    drone_id: str = "drone_01"
    x: float = 0.0
    y: float = 0.0
    altitude: float = 0.0
    heading: float = 0.0
    battery: float = 100.0
    status: str = "idle"
    mission_id: Optional[str] = None
    camera_stream: Optional[str] = None
    updated_at: float = field(default_factory=time.time)
