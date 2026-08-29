"""Inspection mission lifecycle and result contract."""
from dataclasses import dataclass, field
import time
from backend.ros.drone_models import DroneMission, DroneMissionStatus


@dataclass
class InspectionResult:
    mission_id: str
    target_device: str
    observations: list[dict] = field(default_factory=list)
    completed_at: float = field(default_factory=time.time)


class InspectionMission:
    def begin(self, mission: DroneMission) -> None:
        mission.status = DroneMissionStatus.ACTIVE

    def inspect(self, mission: DroneMission, observations: list[dict] | None = None) -> InspectionResult:
        mission.status = DroneMissionStatus.INSPECTING
        return InspectionResult(mission.mission_id, mission.target_device, observations or [])
