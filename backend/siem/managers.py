"""Alert and incident lifecycle managers."""
from datetime import datetime, timezone
import hashlib
import re
import time
from sqlalchemy.orm import Session

from backend.database.models import Alert, Incident, SiemEvent


class AlertManager:
    DEDUP_WINDOW_SECONDS = 5

    @staticmethod
    def _utc_timestamp(value: datetime) -> float:
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).timestamp()

    @classmethod
    def functional_dedup_key(cls, event: SiemEvent) -> str:
        """Build a stable key for one logical event, never using SQLite ids."""
        occurred_at = event.occurred_at or datetime.utcnow()
        bucket = int(cls._utc_timestamp(occurred_at) // cls.DEDUP_WINDOW_SECONDS)
        message = re.sub(r"\s+", " ", (event.message or "").strip()).lower()
        raw = "|".join((event.source or "", event.device_id or "", event.event_type or "",
                        str(bucket), message))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def create(self, db: Session, event: SiemEvent, severity: str, correlation: str | None) -> Alert | None:
        if severity in {"info", "low"}:
            return None
        message = correlation or event.message
        prior_event = (db.query(SiemEvent.id)
                       .filter(SiemEvent.correlation_id == event.correlation_id)
                       .filter(SiemEvent.id != event.id)
                       .first()) if event.correlation_id else None
        if prior_event:
            occurred_at = self._utc_timestamp(event.occurred_at or datetime.utcnow())
            prior_alert = (db.query(Alert.id)
                           .filter(Alert.device_id == (event.device_id or "platform"))
                           .filter(Alert.alert_type == event.event_type)
                           .filter(Alert.timestamp >= occurred_at - self.DEDUP_WINDOW_SECONDS)
                           .filter(Alert.timestamp <= occurred_at + self.DEDUP_WINDOW_SECONDS)
                           .first())
            if prior_alert:
                return None
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
