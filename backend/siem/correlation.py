"""Small deterministic correlation engine, suitable for edge/offline deployment."""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from backend.database.models import SiemEvent
from backend.siem.contracts import SeverityLevel


class CorrelationEngine:
    WINDOW = timedelta(minutes=5)

    def correlate(self, db: Session, event: SiemEvent) -> tuple[str, str | None]:
        """Return an escalated severity and optional human-readable correlation."""
        since = datetime.utcnow() - self.WINDOW
        related = (db.query(SiemEvent).filter(SiemEvent.occurred_at >= since)
                   .filter(SiemEvent.device_id == event.device_id).all()) if event.device_id else []
        auth_failures = sum(item.source == "auth" and "fail" in item.event_type.lower() for item in related)
        network_events = sum(item.source == "network" for item in related)
        sensor_events = sum(item.source == "sensor" for item in related)

        if event.severity == SeverityLevel.CRITICAL.value:
            return SeverityLevel.CRITICAL.value, "Critical source event"
        if auth_failures >= 3:
            return SeverityLevel.HIGH.value, "Repeated authentication failures correlated"
        if network_events and sensor_events:
            return SeverityLevel.HIGH.value, "Network and sensor anomaly correlated"
        if len(related) >= 5:
            return SeverityLevel.MEDIUM.value, "High event frequency correlated"
        return event.severity, None
