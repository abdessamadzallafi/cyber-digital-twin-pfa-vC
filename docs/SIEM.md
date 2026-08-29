# Lightweight Smart Port SIEM

The SIEM is intentionally lightweight: it runs in the FastAPI process, uses the
existing SQLAlchemy operational store, mirrors normalized evidence to the JSONL
data lake, and requires no external SIEM product for the local/edge deployment.

## Collection sources

| Source | Integration point |
|---|---|
| MQTT alerts | MQTT payloads are stored as telemetry evidence; detected security, IDS, or ML alerts are collected as SIEM events. Normal MQTT messages do not necessarily create SIEM events. |
| Sensor logs | Environmental and IoT detections are normalized as SIEM sensor/network events. |
| Drone logs | Drone telemetry is stored as operational evidence and delivered to the dashboard; it does not enter the current SIEM decision path. |
| Network events | Existing IDS alerts are mirrored as `network` SIEM events. |
| HTTP logs | FastAPI middleware records every completed HTTP request; HTTP telemetry also records `telemetry_ingested`. |
| Authentication logs | Login success/failure is best-effort audited without affecting login availability. |
| ROS2 logs | The ROS2 bridge is an optional extension; its audit adapter is not part of the active MQTT drone workflow. |

## Detection and response

`CorrelationEngine` uses a five-minute window per device. It escalates repeated
authentication failures, combined network/sensor signals, high event frequency,
and critical source events. `AlertManager` creates alerts for medium+ events;
`IncidentManager` creates or updates deduplicated high/critical incidents.

Risk is deterministic and explainable: recent severity points are summed and
bounded to 100. Levels are low (<25), medium (<60), high (<85), critical (>=85).

## REST API

All endpoints need the existing Bearer token.

- `POST /api/v1/siem/events` collects a normalized event.
- `GET /api/v1/siem/events` lists event evidence.
- `GET /api/v1/siem/risk` returns the current 60-minute risk score.
- `GET /api/v1/siem/incidents` lists open incidents.
- `POST /api/v1/siem/incidents/{id}/resolve` resolves an incident.
- `POST /api/v1/siem/reports` generates a PDF report. Body: `{"window_minutes": 1440}`.

Example event body:

```json
{
  "source": "network",
  "event_type": "unknown_ip",
  "device_id": "grue_G01",
  "severity": "high",
  "message": "Traffic observed from an untrusted address",
  "payload": {"ip": "10.0.0.12"}
}
```
