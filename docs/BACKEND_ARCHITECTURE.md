# Backend clean architecture

`backend/` is organized around dependency direction: framework adapters call
application services; services use repositories and ports; database, MQTT, ROS2,
UDP, HTTP, report generation, and data-lake modules are infrastructure adapters.
No service imports FastAPI request objects.

```text
backend/api       HTTP routes and versioned contracts
       │ Depends(get_platform_service)
backend/core      configuration, application composition, dependency providers
backend/services  telemetry and operational use cases
       ├── database/repositories   SQLAlchemy query boundary
       ├── datalake                append-only evidence port
       ├── siem                    security/correlation application service
       └── models, schemas         persistence/domain exports and API contracts

backend/mqtt | udp | http | ros | reports | utils
       infrastructure transport/integration adapters
backend/security | ml
       security controls and trained-model inference
```

## Dependency injection

`backend.core.dependencies.get_db` creates exactly one SQLAlchemy session per
request and closes it after the response. `get_platform_service` injects that
session into `PlatformService`. Route handlers in `backend/api/v1.py` only parse
contracts, authorize requests and call services.

To unit test a use case, construct `PlatformService(test_session, lake=fake_lake,
siem=fake_siem)`. No FastAPI server or MQTT broker is needed.

## API migration and compatibility

New production routes are namespaced below `/api/v1`:

- `GET /api/v1/devices` — canonical edge inventory.
- `POST /api/v1/telemetry` — authenticated HTTP ingestion.
- `GET /api/v1/devices/{device_id}/telemetry` — authenticated history.
- `GET /api/v1/alerts` — authenticated SIEM alerts.

The historic root routes, dashboard contract, WebSocket endpoint and MQTT worker
remain in `backend/main.py` as a compatibility surface. They can be migrated one
at a time to API handlers without a breaking release.

Python resolves the new package directories (`backend.database`, `backend.models`
and `backend.schemas`) before same-named legacy files. Those legacy files are
retained on disk only to avoid a destructive migration in the existing working
tree; all current imports resolve to the package contracts described here.

## Production configuration

Copy `.env.example` to `.env` and set `SMART_PORT_JWT_SECRET`,
`SMART_PORT_DEMO_ADMIN_PASSWORD` and `SMART_PORT_DEMO_OPERATOR_PASSWORD` for
every runtime, then set `SMART_PORT_ENV=production`, a PostgreSQL
`SMART_PORT_DATABASE_URL`, and restricted `SMART_PORT_CORS_ORIGINS` for a
deployment. The API refuses startup when any required secret is absent.
Database driver installation, TLS broker credentials/secrets management and
migrations remain deployment responsibilities. The environment-backed demo
accounts are intended only for a local PFA presentation; use a hashed user
repository or identity provider for a real deployment.

Logs rotate at 5 MB with five retained files. Raw evidence is append-only through
the data-lake port and therefore persists independently from the operational
database.

## Current ingestion scope

MQTT IoT messages use the complete security, application-level IDS, ML, and
decision path. HTTP and UDP telemetry currently use the ingestion service and
SIEM audit path, but do not yet execute the complete MQTT decision pipeline.
Drone telemetry is operational state/evidence and is intentionally excluded
from live ML and mission dispatch. These differences are explicit until a later
common-ingestion refactor.
