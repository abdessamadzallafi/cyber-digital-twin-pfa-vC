"""Bounded, transparent risk scoring over recent SIEM evidence."""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from backend.database.models import SiemEvent
from backend.siem.contracts import SEVERITY_POINTS


class RiskScoreService:
    def calculate(self, db: Session, minutes: int = 60) -> dict:
        since = datetime.utcnow() - timedelta(minutes=minutes)
        events = db.query(SiemEvent).filter(SiemEvent.occurred_at >= since).all()
        score = min(100, sum(SEVERITY_POINTS.get(event.severity, 1) for event in events))
        level = "low" if score < 25 else "medium" if score < 60 else "high" if score < 85 else "critical"
        return {"score": score, "level": level, "window_minutes": minutes, "event_count": len(events)}
