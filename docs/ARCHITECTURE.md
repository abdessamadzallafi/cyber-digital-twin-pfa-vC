# Smart Port Security Platform Architecture

The project now has a canonical `smart_port/` industrial architecture while `backend/`, `simulation/`, `dashboard/`, `gazebo/`, and `attacks/` remain compatibility entry points.

```text
edge (drone, cameras, environmental/IoT sensors, RFID-ready registry, GPS, barriers)
  -> communication (MQTT listener, REST API, UDP adapter, device gateway)
  -> data (SQLite/PostgreSQL configuration, JSONL data lake, logs)
  -> analytics (ML anomaly models, SIEM rules, application-level IDS, correlation)
  -> mission (MQTT drone mission planner; optional ROS2/Gazebo boundary)
  -> application (FastAPI, REST, WebSocket, JWT authentication)
  -> presentation (React dashboard)
```

## Compatibility contract

- `python run.py`, `uvicorn backend.main:app`, all existing root API routes, WebSocket `/ws`, dashboard calls, MQTT topics, Gazebo world, and simulator scripts remain valid.
- New additive endpoints are `GET /api/v1/platform/health` and `GET /api/v1/edge/devices`.
- `smart_port.edge.device_registry` is the authoritative inventory. It supports both the current real-simulator identities (for example `grue_G01`) and legacy demo attack IDs (for example `temp_01`).
- `smart_port.communication.device_gateway` normalizes incoming transport payloads before legacy persistence and WebSocket delivery; the MQTT listener remains the live adapter.
- `smart_port.analytics.siem` is the canonical facade for device credential/topic policy and `correlation_engine` combines it with ML/network findings.

## Scope of the current network simulation

Network indicators are application-level simulated metadata: IP/MAC values are
provided by simulator payloads and the project does not capture live network
traffic. `NetworkFlow` is reserved for a later, explicit network-simulation
phase and is not currently populated.

The local demonstration broker uses MQTT on port 1883 without broker ACL or
strong authentication. TLS material exists for a later deployment phase but is
not active in the primary local path, and the API is currently served over HTTP.

## Deployment evolution

`SMART_PORT_DATABASE_URL` supports PostgreSQL once its SQLAlchemy driver is installed. `SMART_PORT_MQTT_HOST`, `SMART_PORT_MQTT_PORT`, `SMART_PORT_UDP_HOST`, `SMART_PORT_UDP_PORT`, and `SMART_PORT_DATA_LAKE_PATH` provide environment-based deployment configuration. Raw telemetry is persisted as daily append-only JSONL under `data_lake/`, separate from operational SQLite records.
