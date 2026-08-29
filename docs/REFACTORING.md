# Refactoring record

This refactoring is additive by design. The existing prototype modules are not
deleted or renamed, so imports, scripts, dashboard calls and deployed runbooks
continue to work.

| Existing capability | Industrial placement | Modification |
|---|---|---|
| `simulation/`, robot simulator, Gazebo | Edge / Mission | The MQTT drone simulator is the active path; robot/TurtleBot and Gazebo assets remain legacy or optional experimental references. |
| `backend/mqtt_listener.py` | Communication / Data | Payloads are normalized by the Device Gateway and raw MQTT evidence is appended to the data lake before normal persistence. |
| `backend/security/engine.py` | Analytics / SIEM | Device and topic validation now delegates to the shared registry; current simulator IDs and old demo IDs are both authorized. |
| `backend/ml/`, `network/`, `decision_engine.py` | Analytics | Existing ML and IDS behavior remains; correlation classifies combined AI/security signals and can request autonomous inspection. |
| `backend/database.py` | Data | The SQLite default is unchanged; `SMART_PORT_DATABASE_URL` enables a PostgreSQL SQLAlchemy URL. |
| `backend/mission_planner.py` | Mission | MQTT uses central configuration, mission evidence enters the data lake, and the ROS2 bridge is called opportunistically. |
| `backend/main.py` | Application | All existing routes are unchanged; versioned platform endpoints are mounted under `/api/v1`. |
| `dashboard/` | Presentation | No source behavior changed; it continues to consume the existing root API and WebSocket contract. |
| `config/setting.py`, `run.py` | Cross-cutting | Both now use central environment-aware settings while preserving their old exported names and local defaults. |

New canonical modules are in `smart_port/`; the legacy directories intentionally
act as compatibility facades during an incremental migration. This avoids a risky
big-bang move while providing stable target locations for all new work.
