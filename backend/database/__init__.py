"""Canonical database package and backwards-compatible model exports."""
from sqlalchemy import inspect, text

from backend.database.session import SessionLocal, engine
from backend.database.models import Base, SensorReading, Alert, NetworkFlow, Mission, Incident, SiemEvent, Device, Drone, Report, LogEntry

db_engine = engine
DatabaseBase = Base

Base.metadata.create_all(bind=engine)


def _upgrade_legacy_schema() -> None:
    """Add non-destructive fields required by the correlation lifecycle."""
    columns = {column["name"] for column in inspect(engine).get_columns("incidents")}
    additions = {
        "first_seen": "DATETIME",
        "last_seen": "DATETIME",
        "occurrence_count": "INTEGER NOT NULL DEFAULT 1",
        "dedup_key": "VARCHAR",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE incidents ADD COLUMN {name} {definition}"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_incidents_dedup_key ON incidents (dedup_key)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_incidents_last_seen ON incidents (last_seen)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_incidents_first_seen ON incidents (first_seen)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_missions_status ON missions (status)"))


_upgrade_legacy_schema()

__all__ = ["SessionLocal", "engine", "db_engine", "Base", "DatabaseBase", "SensorReading", "Alert", "NetworkFlow", "Mission", "Incident", "SiemEvent", "Device", "Drone", "Report", "LogEntry"]
