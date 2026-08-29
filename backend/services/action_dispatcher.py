"""Single controlled boundary between detections and operational actions."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.database.models import Incident, Mission
from backend.logger import logger
from backend.ros.drone_manager import DroneManager, drone_manager

ACTIVE_MISSION_STATUSES = {"created", "sent", "active", "flying", "inspecting", "returning_home", "in_progress"}
DISPATCHABLE_TRIGGERS = {"sensor_anomaly", "security_incident", "network_attack", "ml_anomaly", "drone_anomaly", "manual"}


class ActionDispatcher:
    """Correlate repeated events and dispatch at most one inspection at a time."""

    def __init__(self, db: Session, manager: DroneManager = drone_manager):
        self.db = db
        self.manager = manager

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

    def should_dispatch_drone(self, device_id: str, anomaly_type: str, severity: str) -> tuple[bool, str]:
        if anomaly_type not in DISPATCHABLE_TRIGGERS:
            return False, "unsupported_trigger"
        active = (self.db.query(Mission).filter(Mission.drone_id == settings.drone_id)
                  .filter(Mission.status.in_(ACTIVE_MISSION_STATUSES)).first())
        if active:
            return False, f"active_mission:{active.mission_id}"
        if self.manager.mission and self.manager.mission.status.value in ACTIVE_MISSION_STATUSES:
            return False, f"manager_active:{self.manager.mission.mission_id}"
        cutoff = datetime.utcnow() - timedelta(seconds=settings.drone_mission_cooldown_seconds)
        recent = (self.db.query(Mission).filter(Mission.device_id == device_id)
                  .filter(Mission.created_at >= cutoff).order_by(Mission.created_at.desc()).first())
        if recent:
            return False, "cooldown"
        return True, "accepted"

    def handle_detection(self, device_id: str, anomaly_type: str, severity: str, description: str,
                         dispatch_recommended: bool) -> dict:
        incident, created = self.create_or_update_incident(device_id, anomaly_type, severity, description)
        result = {"incident_id": incident.id, "incident_created": created, "mission_id": None, "dispatch_reason": None}
        if not dispatch_recommended:
            result["dispatch_reason"] = "not_recommended"
            return result
        allowed, reason = self.should_dispatch_drone(device_id, anomaly_type, severity)
        if not allowed:
            result["dispatch_reason"] = reason
            logger.debug("Drone dispatch skipped device=%s reason=%s", device_id, reason)
            return result
        try:
            mission = self.manager.create_inspection(device_id, mission_type=anomaly_type,
                                                     priority="high" if severity in {"high", "critical"} else "medium")
        except Exception:
            logger.exception("Drone dispatch failed device=%s incident=%s", device_id, incident.id)
            result["dispatch_reason"] = "dispatch_failed"
            return result
        incident.drone_mission_id = mission.mission_id
        self.db.commit()
        result.update(mission_id=mission.mission_id, dispatch_reason="dispatched")
        return result
