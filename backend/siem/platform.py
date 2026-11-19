"""SIEM orchestration service: collect -> correlate -> alert -> incident -> risk."""
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from backend.database.models import Incident, SiemEvent
from backend.datalake import DataLakeWriter
from backend.reports.siem_report import SiemReportService
from backend.schemas.siem import SiemEventIn
from backend.siem.correlation import CorrelationEngine
from backend.siem.managers import AlertManager, IncidentManager
from backend.siem.risk import RiskScoreService


class SmartPortSiem:
    def __init__(self, db: Session, lake: DataLakeWriter | None = None):
        self.db = db
        self.lake = lake or DataLakeWriter()
        self.correlation = CorrelationEngine()
        self.alerts = AlertManager()
        self.incidents = IncidentManager()
        self.risk = RiskScoreService()

    def collect(self, payload: SiemEventIn, *, manage_incident: bool = True) -> dict:
        event = SiemEvent(source=payload.source, event_type=payload.event_type, device_id=payload.device_id,
                          severity=payload.severity.value, message=payload.message,
                          payload=json.dumps(payload.payload, default=str), occurred_at=payload.occurred_at or datetime.utcnow(),
                          correlation_id=payload.correlation_id)
        if not event.correlation_id:
            event.correlation_id = AlertManager.functional_dedup_key(event)
        self.db.add(event)
        self.db.flush()  # makes this event visible to correlation before commit
        severity, correlation = self.correlation.correlate(self.db, event)
        event.severity = severity
        alert = self.alerts.create(self.db, event, severity, correlation)
        incident = self.incidents.create_or_update(self.db, event, severity, correlation) if manage_incident else None
        self.lake.append("siem", {"event_id": event.id, "source": event.source, "event_type": event.event_type,
                                  "severity": severity, "device_id": event.device_id, "message": event.message,
                                  "payload": payload.payload, "correlation": correlation})
        self.db.commit()
        return {"event_id": event.id, "severity": severity, "correlation": correlation,
                "alert_id": alert.id if alert else None, "incident_id": incident.id if incident else None,
                "risk": self.risk.calculate(self.db)}

    def events(self, limit: int = 100):
        return self.db.query(SiemEvent).order_by(SiemEvent.occurred_at.desc()).limit(limit).all()

    def open_incidents(self):
        self.collapse_duplicate_open_incidents()
        return (
            self.db.query(Incident)
            .filter(Incident.status != "resolved")
            .order_by(Incident.last_seen.desc())
            .all()
        )

    def collapse_duplicate_open_incidents(self) -> int:
        """Keep one open incident per (device_id, anomaly_type); resolve older clones.

        Historical ActionDispatcher windowing left many open duplicates that
        inflated supervision KPIs. Also auto-resolves stale open incidents that
        have not been refreshed for 24h so the dashboard reflects live threats.
        """
        now = datetime.utcnow()
        stale_before = now - timedelta(hours=24)
        resolved = 0

        stale_rows = (
            self.db.query(Incident)
            .filter(Incident.status != "resolved")
            .filter(Incident.last_seen < stale_before)
            .all()
        )
        for incident in stale_rows:
            incident.status = "resolved"
            incident.resolved_at = now
            resolved += 1

        open_rows = (
            self.db.query(Incident)
            .filter(Incident.status != "resolved")
            .order_by(Incident.last_seen.desc(), Incident.id.desc())
            .all()
        )
        seen: set[tuple[str, str]] = set()
        for incident in open_rows:
            key = (incident.device_id or "platform", incident.anomaly_type or "")
            if key in seen:
                incident.status = "resolved"
                incident.resolved_at = now
                resolved += 1
            else:
                seen.add(key)
        if resolved:
            self.db.commit()
        return resolved

    def resolve_incident(self, incident_id: int):
        result = self.incidents.resolve(self.db, incident_id)
        if result:
            self.db.commit()
        return result

    def count_open_incidents(self) -> int:
        self.collapse_duplicate_open_incidents()
        return self.db.query(Incident).filter(Incident.status != "resolved").count()

    def report(self, window_minutes: int) -> str:
        return SiemReportService().generate(self.db, window_minutes)
