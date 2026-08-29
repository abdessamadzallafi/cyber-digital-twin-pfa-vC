"""Deterministic waypoint navigation independent of ROS2 transport."""
from math import hypot
from backend.ros.drone_models import DroneMission, DroneMissionStatus, DroneState, Waypoint


class WaypointNavigator:
    def __init__(self, arrival_tolerance: float = 0.75):
        self.arrival_tolerance = arrival_tolerance

    def next_target(self, mission: DroneMission) -> Waypoint:
        if mission.current_waypoint >= len(mission.waypoints):
            return mission.home
        return mission.waypoints[mission.current_waypoint]

    def update(self, state: DroneState, mission: DroneMission, step: float = 1.0) -> DroneState:
        """Move one bounded simulation step and advance mission state."""
        target = self.next_target(mission)
        distance = hypot(target.x - state.x, target.y - state.y)
        if distance <= self.arrival_tolerance:
            if mission.current_waypoint < len(mission.waypoints):
                mission.current_waypoint += 1
                if mission.current_waypoint == len(mission.waypoints):
                    mission.status = DroneMissionStatus.INSPECTING
            else:
                mission.status = DroneMissionStatus.COMPLETED
                state.status = "idle"
                state.mission_id = None
            return state
        ratio = min(step / distance, 1.0)
        state.x += (target.x - state.x) * ratio
        state.y += (target.y - state.y) * ratio
        state.altitude = target.altitude
        state.status = "returning_home" if mission.status == DroneMissionStatus.RETURNING_HOME else "flying"
        return state

    def return_home(self, mission: DroneMission) -> None:
        mission.status = DroneMissionStatus.RETURNING_HOME
        mission.current_waypoint = len(mission.waypoints)
