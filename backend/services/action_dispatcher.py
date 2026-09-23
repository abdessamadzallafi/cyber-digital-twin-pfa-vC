"""Single controlled boundary between detections and operational actions."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.database.models import Incident
from backend.logger import logger




class ActionDispatcher:
    """Correlate repeated events and dispatch at most one inspection at a time."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def dedup_key(device_id: str, anomaly_type: str) -> str:
        return hashlib.sha256(f"{device_id}:{anomaly_type}".encode()).hexdigest()[:32]

    def create_or_update_incident(self, device_id: str, anomaly_type: str, severity: str, description: str) -> tuple[Incident, bool]:
        now = datetime.utcnow()
        key = self.dedup_key(device_id, anomaly_type)
        since = now - timedelta(seconds=settings.incident_dedup_window_seconds)
        incident = (self.db.query(Incident).filter(Incident.device_id == device_id)
                    .filter(Incident.anomaly_type == anomaly_type).filter(Incident.status != "resolved")
                    .filter((Incident.last_seen >= since) | (Incident.last_seen.is_(None)))
                    .order_by(Incident.created_at.desc()).first())
        if incident:
            incident.dedup_key = key
            incident.last_seen = now
            incident.occurrence_count = (incident.occurrence_count or 1) + 1
            if severity == "critical" or incident.severity not in {"critical", "high"}:
                incident.severity = severity
            incident.description = description
            self.db.commit()
            logger.debug("Duplicate anomaly correlated incident=%s device=%s type=%s", incident.id, device_id, anomaly_type)
            return incident, False
        incident = Incident(device_id=device_id, anomaly_type=anomaly_type, severity=severity,
                            description=description, dedup_key=key, first_seen=now, last_seen=now, occurrence_count=1)
        self.db.add(incident)
        self.db.commit()
        self.db.refresh(incident)
        logger.info("Incident created id=%s device=%s type=%s", incident.id, device_id, anomaly_type)
        return incident, True

    def handle_detection(
        self,
        device_id: str,
        anomaly_type: str,
        severity: str,
        description: str,
        dispatch_recommended: bool = False,
        *,
        create_incident: bool = True,
    ) -> dict:
        """
        Record/correlate a detection as a security incident.

        Operational drone dispatch is intentionally not part of SecurIoT-Port.
        ``dispatch_recommended`` remains accepted for backward compatibility
        with existing callers, but it has no operational effect.
        """
        incident = created = None

        if create_incident:
            incident, created = self.create_or_update_incident(
                device_id,
                anomaly_type,
                severity,
                description,
            )

        return {
            "incident_id": incident.id if incident else None,
            "incident_created": bool(created),
            "mission_id": None,
            "dispatch_reason": "not_applicable",
        }
