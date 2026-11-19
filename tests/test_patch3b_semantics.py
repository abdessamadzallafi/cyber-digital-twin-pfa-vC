"""PATCH 3B regression tests for alert, ML and dashboard semantics."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Alert, Base, Incident, SensorReading, SiemEvent
from backend.schemas.siem import SiemEventIn
from backend.services.action_dispatcher import ActionDispatcher
from backend.services.platform_service import PlatformService
from backend.siem.platform import SmartPortSiem


def make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_same_logical_siem_event_creates_one_primary_alert():
    db = make_db()
    siem = SmartPortSiem(db)
    payload = SiemEventIn(
        source="sensor", event_type="ml_anomaly", device_id="temp_01",
        message="AI anomaly: temperature (score=0.91)", severity="high",
        correlation_id="same-logical-event",
    )

    siem.collect(payload)
    siem.collect(payload)

    assert db.query(SiemEvent).count() == 2
    assert db.query(Alert).count() == 1
    db.close()


def test_two_different_contexts_remain_two_alerts():
    db = make_db()
    siem = SmartPortSiem(db)

    for message in ("AI anomaly: temperature (score=0.91)", "AI anomaly: temperature (score=0.97)"):
        siem.collect(SiemEventIn(
            source="sensor", event_type="ml_anomaly", device_id="temp_01",
            message=message, severity="high",
        ))

    assert db.query(Alert).count() == 2
    db.close()


def test_network_flood_keeps_security_network_classification():
    db = make_db()
    siem = SmartPortSiem(db)
    siem.collect(SiemEventIn(
        source="network", event_type="network_flood", device_id="temp_01",
        message="Flood réseau temp_01", severity="high",
    ))

    event = db.query(SiemEvent).one()
    alert = db.query(Alert).one()
    assert event.source == "network"
    assert event.event_type == "network_flood"
    assert alert.alert_type == "network_flood"
    db.close()


def test_existing_sqlite_files_are_read_only_for_audit_probe():
    """Integrity probe must open existing DBs read-only without requiring a quiet writer."""
    import shutil
    import tempfile

    paths = [Path("data/digital_twin.db"), Path("digital_twin.db")]
    with tempfile.TemporaryDirectory() as tmp:
        for path in paths:
            if not path.exists():
                continue
            copy = Path(tmp) / path.name
            shutil.copy2(path, copy)
            connection = sqlite3.connect(f"file:{copy.resolve()}?mode=ro", uri=True)
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            connection.close()


def test_dashboard_uses_factual_security_event_label():
    source = Path("dashboard/src/App.jsx").read_text()
    assert "Menaces détectées" not in source
    assert "Événements de sécurité" in source


def test_legacy_temp_alias_counts_as_registered_online_device():
    from smart_port.edge.device_registry import canonical_device_id, device_identity_keys

    assert canonical_device_id("temp_01") == "grue_G01"
    assert "temp_01" in device_identity_keys("grue_G01")

    db = make_db()
    db.add(SensorReading(
        device_id="temp_01", type="temperature", value=22.5,
        timestamp=datetime.utcnow().timestamp(),
        received_at=datetime.utcnow(),
    ))
    db.commit()
    service = PlatformService(db)
    devices = {item.device_id: item for item in service.list_devices()}
    assert devices["grue_G01"].online is True
    assert service.count_online_devices() == 1
    db.close()


def test_action_dispatcher_does_not_duplicate_open_incidents():
    db = make_db()
    dispatcher = ActionDispatcher(db)
    first, created = dispatcher.create_or_update_incident(
        "temp_01", "network_attack", "critical", "Flood MQTT"
    )
    assert created is True
    second, created_again = dispatcher.create_or_update_incident(
        "temp_01", "network_attack", "high", "Flood MQTT again"
    )
    assert created_again is False
    assert second.id == first.id
    assert db.query(Incident).filter(Incident.status != "resolved").count() == 1
    assert second.occurrence_count == 2
    db.close()


def test_collapse_duplicate_open_incidents():
    db = make_db()
    for _ in range(3):
        db.add(Incident(
            device_id="temp_01", anomaly_type="network_attack",
            severity="critical", status="open", description="dup",
            occurrence_count=1,
        ))
    db.commit()
    siem = SmartPortSiem(db)
    assert siem.count_open_incidents() == 1
    assert db.query(Incident).filter(Incident.status == "resolved").count() == 2
    db.close()
