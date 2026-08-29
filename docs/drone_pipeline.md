# Drone pipeline

The local simulator keeps the platform demonstrable without ROS2 or Gazebo:

`IoT anomaly -> ActionDispatcher -> drone/mission -> drone_sim -> drone telemetry -> MQTT listener -> database/WebSocket/API`.

## MQTT contract

- `drone/mission` (QoS 1): `mission_id`, `drone_id`, `token`, and a non-empty
  `waypoints` array. Every waypoint needs numeric `x` and `y`; `altitude` and
  `dwell_seconds` are optional.
- `drone/telemetry`: `x`, `y`, `altitude`, `battery`, `status`, `mission_id`,
  `mission_status`, and `timestamp`.
- `drone/gps` and `drone/camera` are companion evidence streams.

The simulator uses Paho MQTT VERSION2. It subscribes from `on_connect` and
only reports itself subscribed once it receives the broker `SUBACK` in
`on_subscribe`; this repeats after a broker reconnect. It logs every rejection
instead of silently returning. The client ID defaults to `drone_simulator` and
can be overridden with `SMART_PORT_DRONE_CLIENT_ID` (only run one simulator
with a given client ID).

`drone/event` is an additive operational-evidence topic (`mission_started`,
`mission_completed`, and `mission_rejected` with its reason). It lets an
integration test prove negative cases without parsing terminal output. The
existing dashboard remains compatible because the backend already handles
`drone_event` separately from anomaly detection.

## State machine

`idle -> flying -> inspecting -> returning_home -> completed -> idle`.

The completed state is reported in `mission_status` while the operational
status returns to `idle` and `mission_id` becomes `null`; therefore a finished
mission is never presented as active. A lock and `mission_active` gate ensure
only one worker can own a mission, including QoS duplicate deliveries. The
return home movement and descent are incremental; low battery triggers the
same return path.

The simulator prints startup evidence immediately and then a concise
`[DRONE] waiting for mission...` every 30 seconds while idle. Position logs
are rate-limited to once per two seconds; detailed telemetry belongs on MQTT,
the API and the WebSocket.

## Run locally (six terminals)

1. Broker: `mosquitto -v -p 1883`
2. API: `venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000`
3. Simulator: `venv/bin/python simulation/drone_sim.py`
4. MQTT monitor: `mosquitto_sub -h 127.0.0.1 -p 1883 -v -t 'drone/#'`
5. API monitor: `watch -n 1 'curl -s http://127.0.0.1:8000/api/v1/drone/status'`
6. Pipeline test: `venv/bin/python scripts/test_drone_pipeline.py`

For a manual mission, publish:

```bash
mosquitto_pub -h 127.0.0.1 -p 1883 -q 1 -t drone/mission -m '{"mission_id":"TEST_001","drone_id":"drone_01","token":"tk_drone_secure_001","waypoints":[{"x":8,"y":5,"altitude":8,"dwell_seconds":3}]}'
```

Use the same `SMART_PORT_MQTT_HOST`, `SMART_PORT_MQTT_PORT`,
`SMART_PORT_DRONE_ID`, and `SMART_PORT_DRONE_TOKEN` environment values in all
three processes. `scripts/test_drone_pipeline.py` checks receipt, movement,
inspection, incremental return, completion, telemetry, invalid token/drone ID/
waypoint handling, duplicate rejection, monitor reconnection and (when API is
up) health/status synchronization. With an explicit `SMART_PORT_DATABASE_URL`
pointing at the test SQLite database it also validates 50-event incident
deduplication and mission cooldown.

## Backend, dashboard and security

- `/api/v1/drone/status` is intentionally demo-readable; mission-control
  endpoints remain protected by the existing authentication dependency.
- `/api/v1/platform/health` reports database, MQTT, WebSocket, simulator-seen
  and ROS2 availability without failing when an optional dependency is absent.
- Drone `telemetry`, GPS and camera streams are evidence-only in the MQTT
  worker. They update the database, API and WebSocket but never enter the
  Decision Engine or ActionDispatcher.
- Sensor detections enter the ActionDispatcher exactly once. It correlates by
  `device_id + anomaly_type`, maintains `first_seen`, `last_seen` and
  `occurrence_count`, blocks active missions, and applies cooldown before a
  new drone dispatch.

## Demonstration sequence

1. Wait for terminal 3 to show `MQTT connected`, `subscribed` and `simulator ready`.
2. Run terminal 6, or publish the manual `TEST_001` command below.
3. Watch `drone/#` in terminal 4 for telemetry, event evidence and progressive
   coordinates; terminal 5 shows the backend state at the same time.
4. For rejection evidence, resend the mission while it flies or publish a bad
   token. Terminal 3 logs the reason and `drone/event` carries it to monitoring.

## Troubleshooting

- No `[DRONE] MQTT connected`: verify host/port and that another simulator is
  not using the same client ID.
- No `[DRONE] subscribed`: inspect the subscribe return code and broker log.
- `mission rejected`: the simulator prints the exact validation reason
  (invalid JSON, drone ID, token, mission ID, waypoint, or active mission).
- Status API stale: check the backend MQTT listener log and that it is
  subscribed to `drone/#`.
