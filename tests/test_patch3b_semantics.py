"""PATCH 3B regression tests for alert, ML and dashboard semantics."""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Alert, Base, Incident, SiemEvent
from backend.schemas.siem import SiemEventIn
from backend.services.action_dispatcher import ActionDispatcher
from backend.siem.platform import SmartPortSiem


class FakeMission:
    mission_id = "inspection-1"


class FakeManager:
    mission = None

    def __init__(self):
        self.calls = 0

    def create_inspection(self, *_args, **_kwargs):
        self.calls += 1
        return FakeMission()


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


def test_ml_anomaly_is_not_automatically_a_cyber_incident_but_can_dispatch_inspection():
    db = make_db()
    manager = FakeManager()
    dispatcher = ActionDispatcher(db, manager)

    result = dispatcher.handle_detection(
        "temp_01", "ml_anomaly", "high", "behavioral anomaly", True,
        create_incident=False,
    )

    assert result["incident_id"] is None
    assert db.query(Incident).count() == 0
    assert result["mission_id"] == "inspection-1"
    assert result["dispatch_reason"] == "dispatched"
    assert manager.calls == 1
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
    paths = [Path("data/digital_twin.db"), Path("digital_twin.db")]
    before = {p: hashlib.sha256(p.read_bytes()).digest() for p in paths}
    for path in paths:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        connection.close()
    after = {p: hashlib.sha256(p.read_bytes()).digest() for p in paths}
    assert before == after


def test_dashboard_uses_factual_security_event_label():
    source = Path("dashboard/src/App.jsx").read_text()
    assert "Menaces détectées" not in source
    assert "Événements de sécurité" in source
