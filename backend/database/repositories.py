"""Repository layer: query details are isolated from API handlers."""
from sqlalchemy.orm import Session

from backend.database.models import Alert, SensorReading


class TelemetryRepository:
    def __init__(self, db: Session):
        self.db = db

    def recent_readings(self, device_id: str, limit: int = 100):
        return (self.db.query(SensorReading).filter(SensorReading.device_id == device_id)
                .order_by(SensorReading.received_at.desc()).limit(min(limit, 1000)).all())

    def recent_alerts(self, limit: int = 100):
        return self.db.query(Alert).order_by(Alert.created_at.desc()).limit(min(limit, 1000)).all()
