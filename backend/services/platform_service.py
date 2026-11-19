"""Use-case services. API handlers delegate here and never build SQL queries."""
import time
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from backend.database.models import Alert, SensorReading
from backend.database.repositories import TelemetryRepository
from backend.datalake import DataLakeWriter
from backend.schemas import DeviceOut, TelemetryIn
from backend.schemas.siem import SiemEventIn
from backend.siem import SiemService
from backend.siem.platform import SmartPortSiem
from smart_port.edge.device_registry import (
    DEVICE_REGISTRY,
    canonical_device_id,
    device_identity_keys,
)


class PlatformService:
    HEALTH_WINDOW = timedelta(hours=24)
    FRESHNESS_WINDOW = timedelta(minutes=30)
    ONLINE_WINDOW = timedelta(minutes=5)

    def __init__(self, db: Session, lake: DataLakeWriter | None = None, siem: SiemService | None = None):
        self.db = db
        self.repository = TelemetryRepository(db)
        self.lake = lake or DataLakeWriter()
        self.siem = siem or SiemService()

    def ingest_telemetry(self, payload: TelemetryIn, transport: str = "http") -> dict:
        # --- Existing pipeline (unchanged) -----------------------------------
        event = payload.model_dump()
        event["timestamp"] = event["timestamp"] or time.time()
        event["transport"] = transport
        original_id = payload.device_id
        device_id = canonical_device_id(original_id)
        event["device_id"] = device_id
        self.lake.append("telemetry", event)
        self.lake.append("network", {"device_id": device_id, "transport": transport,
                                      "ip_src": payload.ip_src, "timestamp": event["timestamp"]})
        reading = SensorReading(
            device_id=device_id, type=payload.type, value=payload.value,
            unit=payload.unit,
            status=str(payload.status) if isinstance(payload.status, bool) else payload.status,
            people_count=payload.people_count,
            latitude=payload.latitude, longitude=payload.longitude,
            timestamp=event["timestamp"], ip_src=payload.ip_src, mac_src=payload.mac_src,
            port_src=payload.port_src,
        )
        self.db.add(reading)
        # Identity checks use the wire identity (legacy or canonical).
        result = self.siem.evaluate(original_id, payload.token, payload.mqtt_topic)
        for kind, message in result["alerts"]:
            self.db.add(Alert(device_id=device_id, alert_type=kind, message=message,
                              timestamp=time.time(), severity=result["correlation"]["severity"]))
            self.lake.append("security", {"device_id": device_id, "alert_type": kind, "message": message})
        self.db.commit()
        SmartPortSiem(self.db).collect(SiemEventIn(source=transport, event_type="telemetry_ingested",
                                                    message=f"{transport.upper()} telemetry accepted from {device_id}",
                                                    device_id=device_id, payload={"type": payload.type}))
        self.lake.append("logs", {"level": "info", "source": "gateway",
                                  "message": f"{transport.upper()} telemetry accepted", "device_id": device_id})
        return {"accepted": True, "alerts": len(result["alerts"]), "severity": result["correlation"]["severity"]}

    def list_devices(self) -> list[DeviceOut]:
        """Registry inventory enriched with live online / last_seen status."""
        online_since = datetime.utcnow() - self.ONLINE_WINDOW
        devices: list[DeviceOut] = []
        for item in DEVICE_REGISTRY.values():
            keys = device_identity_keys(item.device_id)
            last = (
                self.db.query(SensorReading)
                .filter(SensorReading.device_id.in_(keys))
                .order_by(SensorReading.received_at.desc())
                .first()
            )
            online = bool(last and last.received_at and last.received_at >= online_since)
            last_value = None
            if last is not None:
                if last.value is not None:
                    last_value = last.value
                elif last.people_count is not None:
                    last_value = last.people_count
                elif last.status is not None:
                    last_value = last.status
                elif last.latitude is not None and last.longitude is not None:
                    last_value = f"{last.latitude:.5f},{last.longitude:.5f}"
            devices.append(DeviceOut(
                device_id=item.device_id,
                type=item.device_type,
                zone=item.zone,
                topic=item.topic,
                online=online,
                status="online" if online else ("stale" if last else "offline"),
                last_seen=last.received_at.isoformat() if last and last.received_at else None,
                last_value=last_value,
            ))
        return devices

    def count_online_devices(self) -> int:
        return sum(1 for device in self.list_devices() if device.online)

    def device_history(self, device_id: str, limit: int):
        keys = device_identity_keys(device_id)
        return self.repository.recent_readings_for_ids(keys, limit)

    def device_health(self, device_id: str) -> dict:
        """Live health only when fresh telemetry exists — never invent 100%."""
        now = datetime.utcnow()
        fresh_since = now - self.FRESHNESS_WINDOW
        window_since = now - self.HEALTH_WINDOW
        keys = device_identity_keys(device_id)

        fresh = (
            self.db.query(SensorReading)
            .filter(SensorReading.device_id.in_(keys))
            .filter(SensorReading.received_at >= fresh_since)
            .count()
        )
        if fresh == 0:
            any_recent = (
                self.db.query(SensorReading)
                .filter(SensorReading.device_id.in_(keys))
                .filter(SensorReading.received_at >= window_since)
                .count()
            )
            status = "stale" if any_recent else "unknown"
            return {"device_id": device_id, "health_score": None, "status": status}

        # Fresh readings may arrive via legacy aliases; health penalties only
        # use the canonical id to avoid historical attack aliases poisoning score.
        anomalies = (
            self.db.query(Alert)
            .filter(Alert.device_id == canonical_device_id(device_id))
            .filter(Alert.alert_type == "ml_anomaly")
            .filter(Alert.created_at >= fresh_since)
            .count()
        )
        ratio = anomalies / fresh
        score = max(0, 100 - int(ratio * 200))
        return {"device_id": device_id, "health_score": score, "status": "ok"}

    def alerts(self, limit: int):
        return self.repository.recent_alerts(limit)
