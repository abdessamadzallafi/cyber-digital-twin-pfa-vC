# Autonomous Drone Architecture

The MQTT virtual drone is the canonical autonomous inspection path. The former
TurtleBot/robot assets are retained as legacy references and are not connected
to the active MQTT pipeline.

```text
FastAPI /api/v1/drone          MQTT drone/mission
             \                  /
              DroneManager
       ┌────────┼─────────┬─────────┐
 MissionPlanner  WaypointNavigator  BatteryMonitor  InspectionMission
       │                 │                 │
 ROS2Interface    GPSPublisher      TelemetryPublisher  CameraStream
```

## Components

- `MissionPlanner` converts a target device into safe approach, inspection and
  departure waypoints.
- `WaypointNavigator` advances one bounded navigation step and supports explicit
  return-home behavior.
- `InspectionMission` owns the inspection lifecycle and observation result.
- `BatteryMonitor` requests automatic return-home at 25% and marks critical state
  at 10%.
- `CameraStream` exposes stream metadata and lifecycle without coupling the domain
  to RTSP, WebRTC or Gazebo.
- `GPSPublisher` publishes `drone/gps`; `TelemetryPublisher` publishes
  `drone/telemetry` through an injected transport.
- `ROS2Interface` is an optional experimental action/topic boundary. The
  application remains usable when `rclpy` is not installed.
- `DroneMQTTInterface` publishes canonical `drone/mission` messages.

## API

All endpoints retain the existing JWT authentication dependency:

- `GET /api/v1/drone/status`
- `POST /api/v1/drone/missions`
- `POST /api/v1/drone/missions/start`
- `POST /api/v1/drone/missions/return-home`
- `POST /api/v1/drone/telemetry`
- `POST /api/v1/drone/camera/start`
- `POST /api/v1/drone/tick`

Existing `/missions` and `/force_mission/{device_id}` remain compatibility
routes for the drone workflow. ROS2/Gazebo and TurtleBot assets are optional
legacy/experimental material; the demonstrable path uses `drone_id`, waypoints,
and `drone/*` topics.

Run `simulation/drone_sim.py` for a local MQTT drone emulator that consumes
missions and publishes telemetry, GPS, and camera-stream metadata.
