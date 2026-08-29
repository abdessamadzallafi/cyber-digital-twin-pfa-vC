"""Battery policy; low battery requests an automatic return-home mission state."""
from dataclasses import dataclass
from backend.ros.drone_models import DroneMission, DroneState


@dataclass(frozen=True)
class BatteryDecision:
    level: float
    return_home: bool
    critical: bool


class BatteryMonitor:
    def __init__(self, return_threshold: float = 25.0, critical_threshold: float = 10.0):
        self.return_threshold = return_threshold
        self.critical_threshold = critical_threshold

    def evaluate(self, state: DroneState, mission: DroneMission | None = None) -> BatteryDecision:
        decision = BatteryDecision(state.battery, state.battery <= self.return_threshold, state.battery <= self.critical_threshold)
        if decision.return_home and mission:
            from backend.ros.waypoint_navigation import WaypointNavigator
            WaypointNavigator().return_home(mission)
        return decision
