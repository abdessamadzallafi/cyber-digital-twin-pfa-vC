"""Bounded, transparent risk scoring over recent SIEM evidence."""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from backend.database.models import SiemEvent
from backend.siem.contracts import SEVERITY_POINTS


class RiskScoreService:
    # Operational/audit noise must never drive the supervision risk gauge.
    EXCLUDED_TYPES = frozenset({
        "http_request",
        "login_success",
        "telemetry_ingested",
        # Non-authoritative ML soft-signal — kept in the lake, not the risk gauge.
        "ml_signal",
    })
    # Info/low are retained in the lake for audit, but do not score risk.
    EXCLUDED_SEVERITIES = frozenset({"info", "low"})
    # Only confirmed security identities drive the live risk percentage.
    # Generic ml_anomaly remains visible in alerts/timeline without forcing 100%.
    SCORED_TYPES = frozenset({
        "flood",
        "network_flood",
        "unknown_ip",
        "bad_token",
        "wrong_topic",
        "unknown_device",
        "login_failed",
    })

    def calculate(self, db: Session, minutes: int = 15) -> dict:
        """Score recent security evidence without letting floods numerically explode.

        Each (device_id, event_type) contributes at most once — its highest
        severity in the window — so a MQTT flood cannot force 100% forever.
        """
        since = datetime.utcnow() - timedelta(minutes=minutes)
        events = (
            db.query(SiemEvent)
            .filter(SiemEvent.occurred_at >= since)
            .filter(SiemEvent.severity.notin_(self.EXCLUDED_SEVERITIES))
            .filter(SiemEvent.event_type.notin_(self.EXCLUDED_TYPES))
            .filter(SiemEvent.event_type.in_(self.SCORED_TYPES))
            .all()
        )
        best: dict[tuple[str | None, str | None], int] = {}
        for event in events:
            key = (event.device_id, event.event_type)
            points = SEVERITY_POINTS.get(event.severity, 1)
            if points > best.get(key, 0):
                best[key] = points
        score = min(100, sum(best.values()))
        level = "low" if score < 25 else "medium" if score < 60 else "high" if score < 85 else "critical"
        return {
            "score": score,
            "level": level,
            "window_minutes": minutes,
            "event_count": len(events),
            "signal_count": len(best),
        }
