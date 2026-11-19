"""Controlled boundary between detections and security incidents."""
from __future__ import annotations

from datetime import datetime
import hashlib

from sqlalchemy.orm import Session

from backend.database.models import Incident
from backend.logger import logger


class ActionDispatcher:
    """Correlate repeated detections into security incidents."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def dedup_key(device_id: str, anomaly_type: str) -> str:
        return hashlib.sha256(
            f"{device_id}:{anomaly_type}".encode()
        ).hexdigest()[:32]

    def create_or_update_incident(
        self,
        device_id: str,
        anomaly_type: str,
        severity: str,
        description: str,
    ) -> tuple[Incident, bool]:
        now = datetime.utcnow()
        key = self.dedup_key(device_id, anomaly_type)

        # Always reopen/update the existing open incident for this
        # (device, type). A time window here previously created unbounded
        # duplicate "open" rows and inflated dashboard KPIs.
        incident = (
            self.db.query(Incident)
            .filter(Incident.device_id == device_id)
            .filter(Incident.anomaly_type == anomaly_type)
            .filter(Incident.status != "resolved")
            .order_by(Incident.last_seen.desc())
            .first()
        )

        if incident:
            incident.dedup_key = key
            incident.last_seen = now
            incident.occurrence_count = (
                incident.occurrence_count or 1
            ) + 1

            if severity == "critical" or incident.severity not in {
                "critical",
                "high",
            }:
                incident.severity = severity

            incident.description = description
            self.db.commit()

            logger.debug(
                "Duplicate anomaly correlated incident=%s device=%s type=%s",
                incident.id,
                device_id,
                anomaly_type,
            )
            return incident, False

        incident = Incident(
            device_id=device_id,
            anomaly_type=anomaly_type,
            severity=severity,
            description=description,
            dedup_key=key,
            first_seen=now,
            last_seen=now,
            occurrence_count=1,
        )

        self.db.add(incident)
        self.db.commit()
        self.db.refresh(incident)

        logger.info(
            "Incident created id=%s device=%s type=%s",
            incident.id,
            device_id,
            anomaly_type,
        )

        return incident, True

    def handle_detection(
        self,
        device_id: str,
        anomaly_type: str,
        severity: str,
        description: str,
        *,
        create_incident: bool = True,
    ) -> dict:
        """Record or correlate a detection as a security incident."""

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
        }
