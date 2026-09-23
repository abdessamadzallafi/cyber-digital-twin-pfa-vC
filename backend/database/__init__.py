"""Canonical database package and backwards-compatible model exports."""
from sqlalchemy import inspect, text

from backend.database.session import SessionLocal, engine
from backend.database.models import Base, SensorReading, Alert, NetworkFlow, Mission, Incident, SiemEvent, Device, Drone, Report, LogEntry

db_engine = engine
DatabaseBase = Base

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


def initialize_schema() -> None:
    """Explicitly create/upgrade the schema for a controlled setup operation."""
    Base.metadata.create_all(bind=engine)
    _upgrade_legacy_schema()


def verify_schema(bind=engine) -> None:
    """Verify that the existing runtime database has the required tables."""
    required = {
        "alerts", "devices", "drones", "incidents", "logs", "missions",
        "network_flows", "reports", "sensor_readings", "siem_events",
    }
    actual = set(inspect(bind).get_table_names())
    missing = sorted(required - actual)
    if missing:
        raise RuntimeError(f"Database schema is incomplete; missing tables: {', '.join(missing)}")

__all__ = ["SessionLocal", "engine", "db_engine", "Base", "DatabaseBase", "SensorReading", "Alert", "NetworkFlow", "Mission", "Incident", "SiemEvent", "Device", "Drone", "Report", "LogEntry", "initialize_schema", "verify_schema"]
