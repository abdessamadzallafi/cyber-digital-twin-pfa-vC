"""Small deterministic correlation engine, suitable for edge/offline deployment."""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from backend.database.models import SiemEvent
from backend.siem.contracts import SeverityLevel


class CorrelationEngine:
    WINDOW = timedelta(minutes=5)

    # Deterministic security identities — never replace their specific messages
    # with a generic correlation label.
    SECURITY_TYPES = frozenset({
        "flood",
        "network_flood",
        "unknown_ip",
        "bad_token",
        "wrong_topic",
        "unknown_device",
    })
    # Only these network event types participate in cross-domain correlation.
    NETWORK_TYPES = frozenset({"network_flood", "unknown_ip"})
    # Sensor-side anomalies that can meaningfully correlate with network attacks.
    SENSOR_ANOMALY_TYPES = frozenset({
        "flood",
        "bad_token",
        "wrong_topic",
        "unknown_device",
        "ml_anomaly",
    })

    def correlate(self, db: Session, event: SiemEvent) -> tuple[str, str | None]:
        """Return an escalated severity and optional human-readable correlation.

        Specific security event messages are preserved: a correlation label is
        only attached when it adds information without erasing a confirmed
        security identity (flood, bad_token, unknown_ip, …).
        """
        since = datetime.utcnow() - self.WINDOW
        related = (
            db.query(SiemEvent)
            .filter(SiemEvent.occurred_at >= since)
            .filter(SiemEvent.device_id == event.device_id)
            .all()
        ) if event.device_id else []

        auth_failures = sum(
            item.source == "auth" and "fail" in (item.event_type or "").lower()
            for item in related
        )
        network_hits = sum(1 for item in related if item.event_type in self.NETWORK_TYPES)
        sensor_hits = sum(1 for item in related if item.event_type in self.SENSOR_ANOMALY_TYPES)
        preserve_message = event.event_type in self.SECURITY_TYPES
        current = event.severity or SeverityLevel.INFO.value

        if current == SeverityLevel.CRITICAL.value:
            # Keep critical severity; do not overwrite a precise source message.
            return SeverityLevel.CRITICAL.value, None

        if auth_failures >= 3:
            return SeverityLevel.HIGH.value, "Repeated authentication failures correlated"

        if network_hits and sensor_hits:
            # Escalate when a real network attack type coexists with a relevant
            # sensor anomaly — but keep confirmed security wording intact.
            if preserve_message:
                return SeverityLevel.HIGH.value, None
            return SeverityLevel.HIGH.value, "Network and sensor anomaly correlated"

        if len(related) >= 5:
            # Frequency is a weak signal: never downgrade high/critical and never
            # erase a specific security description.
            if current in {SeverityLevel.HIGH.value, SeverityLevel.CRITICAL.value} or preserve_message:
                return current, None
            return SeverityLevel.MEDIUM.value, "High event frequency correlated"

        return current, None
