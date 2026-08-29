# Smart Port Security Platform — Terminal Tanger Med

Industrial Smart Port Security Platform combining IoT supervision, cybersecurity,
AI anomaly detection, autonomous inspection missions, a digital twin and a React
command dashboard. The original working prototype remains fully compatible.

## Layered architecture

```text
smart_port/
├── edge/              # trusted device inventory: drone, cameras, sensors, GPS, barrier
├── communication/     # MQTT ingestion, REST and UDP telemetry adapters
├── data/              # operational DB configuration and append-only data lake sink
├── analytics/         # ML, SIEM correlation and decision support
├── mission/           # mission planning and ROS2/Gazebo integration boundary
└── application/       # versioned FastAPI platform API

backend/                # compatibility facade: existing FastAPI API, MQTT worker, ML and security code
simulation/             # edge device and autonomous-drone simulators
gazebo/                 # Gazebo world and launch assets
dashboard/              # React presentation layer
data_lake/              # daily JSONL telemetry/security/mission evidence
logs/                   # application logs
reports/                # generated incident PDFs
```

The complete component responsibilities and compatibility contract are documented
in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
The backend implementation, dependency injection and API migration contract are
documented in [docs/BACKEND_ARCHITECTURE.md](docs/BACKEND_ARCHITECTURE.md).
SIEM collection, correlation, incident response and reporting are documented in
[docs/SIEM.md](docs/SIEM.md).
The Isolation Forest training and prediction pipeline is documented in
[docs/AI_ANOMALY_DETECTION.md](docs/AI_ANOMALY_DETECTION.md).
Autonomous drone planning, ROS2, MQTT, navigation and compatibility behavior are
documented in [docs/DRONE_ARCHITECTURE.md](docs/DRONE_ARCHITECTURE.md).

The MQTT virtual drone is the canonical demonstration path. ROS2/Gazebo assets
remain optional experimental extensions. Network indicators are simulated at the
application level; the platform does not yet capture live network traffic.

## Run locally

```bash
git clone <repository-url>
cd cyber-digital-twin
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and replace every placeholder, then load it for a local run
set -a; source .env; set +a
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Start Mosquitto on port `1883`, then start the React dashboard with
`cd dashboard && npm start`. Edge simulators in `simulation/` (including
`drone_sim.py`) are optional demo inputs. `simulation/data_lake_seed.py` can
preload local demonstration evidence.

The public readiness endpoint is `GET /health`; the detailed platform view is
`GET /api/v1/platform/health`. API documentation is available at `/docs` and
`/openapi.json`.

### Docker demo stack

The self-contained development stack starts the MQTT broker, API and dashboard:

```bash
docker compose up --build
```

Before the first Docker launch, copy `.env.example` to `.env` and replace its
placeholders. The backend consumes this file through Compose; it is ignored by
Git and must never be committed.

Open the dashboard at `http://localhost:3000` and the API documentation at
`http://localhost:8000/docs`. The compose profile is intentionally a local demo
profile: anonymous MQTT is allowed only inside this isolated environment. Do not
deploy it as-is; enable credentials and TLS first.

### Regression tests

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

`pytest` is constrained to the ROS2 Humble-compatible 7.x series, so its
system `launch_testing` plugin can load normally. This preserves ROS2 while
making the command reproducible without disabling plugin autoloading.

Existing API paths (such as `/statistics`, `/ws`, `/simulate/*`, `/missions`) are
unchanged. The additive industrial API provides:

- `GET /api/v1/platform/health` — platform/layer readiness.
- `GET /api/v1/edge/devices` — safe edge asset inventory.

## Configuration

The defaults preserve local operation. Deployment values are environment driven:
`SMART_PORT_MQTT_HOST`, `SMART_PORT_MQTT_PORT`, `SMART_PORT_DATABASE_URL`,
`SMART_PORT_DATA_LAKE_PATH`, `SMART_PORT_API_HOST`, `SMART_PORT_API_PORT`,
`SMART_PORT_UDP_HOST`, and `SMART_PORT_UDP_PORT`.

Use a PostgreSQL SQLAlchemy URL in `SMART_PORT_DATABASE_URL` for production (and
install the matching database driver). ROS2/Gazebo is optional and experimental;
the MQTT drone simulator remains the operational local demonstration path.
