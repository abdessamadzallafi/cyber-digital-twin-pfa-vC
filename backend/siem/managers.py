"""Alert and incident lifecycle managers."""
from datetime import datetime
import time
from sqlalchemy.orm import Session

from backend.database.models import Alert, Incident, SiemEvent


class AlertManager:
    def create(self, db: Session, event: SiemEvent, severity: str, correlation: str | None) -> Alert | None:
        if severity in {"info", "low"}:
            return None
        message = correlation or event.message
        alert = Alert(device_id=event.device_id or "platform", alert_type=event.event_type,
                      message=message, timestamp=time.time(), severity=severity)
        db.add(alert)
        return alert


class IncidentManager:
    def create_or_update(self, db: Session, event: SiemEvent, severity: str, correlation: str | None) -> Incident | None:
        if severity not in {"high", "critical"}:
            return None
        incident = (db.query(Incident).filter(Incident.device_id == (event.device_id or "platform"))
                    .filter(Incident.anomaly_type == event.event_type).filter(Incident.status != "resolved").first())
        if incident:
            incident.severity = severity
            incident.description = correlation or event.message
            incident.last_seen = datetime.utcnow()
            incident.occurrence_count = (incident.occurrence_count or 1) + 1
            return incident
        incident = Incident(device_id=event.device_id or "platform", anomaly_type=event.event_type,
                            severity=severity, description=correlation or event.message,
                            last_seen=datetime.utcnow(), occurrence_count=1)
        db.add(incident)
        return incident

    def resolve(self, db: Session, incident_id: int) -> Incident | None:
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if incident:
            incident.status = "resolved"
            incident.resolved_at = datetime.utcnow()
        return incident
