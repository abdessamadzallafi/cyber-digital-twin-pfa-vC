"""Use-case services. API handlers delegate here and never build SQL queries."""
import time
from sqlalchemy.orm import Session

from backend.database.models import Alert, SensorReading
from backend.database.repositories import TelemetryRepository
from backend.datalake import DataLakeWriter
from backend.events.normalizer import EventNormalizer
from backend.events.contracts import Transport as EventTransport
from backend.siem import SiemService
from backend.siem.platform import SmartPortSiem
from backend.schemas import TelemetryIn
from backend.schemas.siem import SiemEventIn


class PlatformService:
    def __init__(self, db: Session, lake: DataLakeWriter | None = None, siem: SiemService | None = None):
        self.db = db
        self.repository = TelemetryRepository(db)
        self.lake = lake or DataLakeWriter()
        self.siem = siem or SiemService()

    def ingest_telemetry(self, payload: TelemetryIn, transport: str = "http") -> dict:
        # --- Additive CommonEvent envelope -----------------------------------
        # Built from the original Pydantic payload dict BEFORE any mutation.
        # All existing consumers (lake, DB, siem) continue to use `event` dict
        # unchanged.  The CommonEvent is purely additive at this stage.
        _raw_http = payload.model_dump()
        _common_event = EventNormalizer.normalize(
            _raw_http,
            EventTransport.HTTP if transport == "http" else EventTransport(transport),
        )
        # --- Existing pipeline (unchanged) -----------------------------------
        event = payload.model_dump()
        event["timestamp"] = event["timestamp"] or time.time()
        event["transport"] = transport
        self.lake.append("telemetry", event)
        self.lake.append("network", {"device_id": payload.device_id, "transport": transport,
                                      "ip_src": payload.ip_src, "timestamp": event["timestamp"]})
        reading = SensorReading(
            device_id=payload.device_id, type=payload.type, value=payload.value,
            status=str(payload.status) if isinstance(payload.status, bool) else payload.status,
            people_count=payload.people_count,
            latitude=payload.latitude, longitude=payload.longitude,
            timestamp=event["timestamp"], ip_src=payload.ip_src, mac_src=payload.mac_src,
            port_src=payload.port_src,
        )
        self.db.add(reading)
        result = self.siem.evaluate(payload.device_id, payload.token, payload.mqtt_topic)
        for kind, message in result["alerts"]:
            self.db.add(Alert(device_id=payload.device_id, alert_type=kind, message=message,
                              timestamp=time.time(), severity=result["correlation"]["severity"]))
            self.lake.append("security", {"device_id": payload.device_id, "alert_type": kind, "message": message})
        self.db.commit()
        SmartPortSiem(self.db).collect(SiemEventIn(source="http", event_type="telemetry_ingested",
                                                    message=f"HTTP telemetry accepted from {payload.device_id}",
                                                    device_id=payload.device_id, payload={"type": payload.type}))
        self.lake.append("logs", {"level": "info", "source": "gateway",
                                  "message": f"{transport.upper()} telemetry accepted", "device_id": payload.device_id})
        return {"accepted": True, "alerts": len(result["alerts"]), "severity": result["correlation"]["severity"]}

    def device_history(self, device_id: str, limit: int):
        return self.repository.recent_readings(device_id, limit)

    def alerts(self, limit: int):
        return self.repository.recent_alerts(limit)
