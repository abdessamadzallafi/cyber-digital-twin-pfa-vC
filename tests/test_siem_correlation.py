"""Targeted SIEM correlation regressions — preserve specific security identity."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Alert, Base, Incident, SiemEvent
from backend.schemas.siem import SiemEventIn
from backend.siem.contracts import SeverityLevel
from backend.siem.correlation import CorrelationEngine
from backend.siem.platform import SmartPortSiem


def make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(db, *, source, event_type, device_id, message, severity="medium", minutes_ago=0):
    event = SiemEvent(
        source=source,
        event_type=event_type,
        device_id=device_id,
        severity=severity,
        message=message,
        payload="{}",
        occurred_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
    )
    db.add(event)
    db.flush()
    return event


def test_repeated_login_failed_correlates_high():
    db = make_db()
    for _ in range(2):
        _seed(db, source="auth", event_type="login_failed", device_id="admin",
              message="Authentication failed for admin", severity="medium")
    engine = CorrelationEngine()
    current = _seed(db, source="auth", event_type="login_failed", device_id="admin",
                    message="Authentication failed for admin", severity="medium")
    severity, correlation = engine.correlate(db, current)
    assert severity == SeverityLevel.HIGH.value
    assert correlation == "Repeated authentication failures correlated"
    db.close()


def test_network_flood_alone_keeps_specific_message():
    db = make_db()
    siem = SmartPortSiem(db)
    result = siem.collect(SiemEventIn(
        source="network", event_type="network_flood", device_id="grue_G01",
        message="Flood réseau grue_G01", severity="high",
    ))
    event = db.query(SiemEvent).one()
    alert = db.query(Alert).one()
    assert result["correlation"] is None
    assert event.message == "Flood réseau grue_G01"
    assert alert.message == "Flood réseau grue_G01"
    assert event.severity == "high"
    db.close()


def test_flood_alone_keeps_specific_message():
    db = make_db()
    siem = SmartPortSiem(db)
    result = siem.collect(SiemEventIn(
        source="sensor", event_type="flood", device_id="grue_G01",
        message="Flood MQTT détecté sur grue_G01", severity="high",
    ))
    alert = db.query(Alert).one()
    assert result["correlation"] is None
    assert alert.message == "Flood MQTT détecté sur grue_G01"
    db.close()


def test_unknown_ip_alone_keeps_specific_message():
    db = make_db()
    siem = SmartPortSiem(db)
    result = siem.collect(SiemEventIn(
        source="network", event_type="unknown_ip", device_id="grue_G01",
        message="IP inconnue pour grue_G01", severity="high",
    ))
    alert = db.query(Alert).one()
    assert result["correlation"] is None
    assert alert.message == "IP inconnue pour grue_G01"
    db.close()


def test_normal_telemetry_http_does_not_false_correlate():
    db = make_db()
    siem = SmartPortSiem(db)
    siem.collect(SiemEventIn(
        source="http", event_type="telemetry_ingested", device_id="grue_G01",
        message="HTTP telemetry accepted from grue_G01", severity="info",
    ))
    siem.collect(SiemEventIn(
        source="http", event_type="http_request", device_id="grue_G01",
        message="HTTP request", severity="info",
    ))
    events = db.query(SiemEvent).all()
    assert all(e.severity == "info" for e in events)
    assert db.query(Alert).count() == 0
    assert db.query(Incident).count() == 0
    db.close()


def test_network_plus_sensor_anomaly_can_correlate_without_erasing_flood():
    db = make_db()
    siem = SmartPortSiem(db)
    siem.collect(SiemEventIn(
        source="network", event_type="network_flood", device_id="grue_G01",
        message="Flood réseau grue_G01", severity="high",
    ))
    # Generic ML sensor anomaly may receive the cross-domain label.
    result = siem.collect(SiemEventIn(
        source="sensor", event_type="ml_anomaly", device_id="grue_G01",
        message="AI anomaly: temperature (score=0.91)", severity="medium",
    ))
    assert result["severity"] == "high"
    assert result["correlation"] == "Network and sensor anomaly correlated"
    # Confirmed network_flood alert must keep its specific wording.
    flood_alert = db.query(Alert).filter(Alert.alert_type == "network_flood").one()
    assert flood_alert.message == "Flood réseau grue_G01"
    db.close()


def test_loose_network_and_sensor_sources_do_not_correlate():
    """source=network + source=sensor alone is not enough without event_type checks."""
    db = make_db()
    engine = CorrelationEngine()
    _seed(db, source="network", event_type="http_request", device_id="grue_G01",
          message="noise", severity="info")
    current = _seed(db, source="sensor", event_type="telemetry_ingested", device_id="grue_G01",
                    message="noise sensor", severity="info")
    severity, correlation = engine.correlate(db, current)
    assert severity == "info"
    assert correlation is None
    db.close()


def test_high_frequency_does_not_overwrite_security_message():
    db = make_db()
    for i in range(4):
        _seed(db, source="sensor", event_type="ml_signal", device_id="grue_G01",
              message=f"signal {i}", severity="low")
    engine = CorrelationEngine()
    current = _seed(db, source="sensor", event_type="flood", device_id="grue_G01",
                    message="Flood MQTT détecté", severity="high")
    severity, correlation = engine.correlate(db, current)
    assert severity == "high"
    assert correlation is None
    db.close()


def test_critical_preserves_source_message():
    db = make_db()
    siem = SmartPortSiem(db)
    result = siem.collect(SiemEventIn(
        source="sensor", event_type="bad_token", device_id="grue_G01",
        message="Invalid device credential for grue_G01", severity="critical",
    ))
    alert = db.query(Alert).one()
    incident = db.query(Incident).one()
    assert result["severity"] == "critical"
    assert result["correlation"] is None
    assert alert.message == "Invalid device credential for grue_G01"
    assert incident.description == "Invalid device credential for grue_G01"
    db.close()


def test_http_request_never_becomes_alert_or_incident():
    db = make_db()
    siem = SmartPortSiem(db)
    siem.collect(SiemEventIn(
        source="http", event_type="http_request", device_id="platform",
        message="GET /api/v1/ops/statistics -> 200", severity="medium",
    ))
    assert db.query(Alert).count() == 0
    assert db.query(Incident).count() == 0
    risk = siem.risk.calculate(db)
    assert risk["event_count"] == 0
    assert risk["score"] == 0
    db.close()


def test_risk_ignores_http_noise_but_scores_security_events():
    db = make_db()
    siem = SmartPortSiem(db)
    for _ in range(20):
        siem.collect(SiemEventIn(
            source="http", event_type="http_request",
            message="GET /health -> 200", severity="info",
        ))
    siem.collect(SiemEventIn(
        source="network", event_type="network_flood", device_id="grue_G01",
        message="Flood réseau grue_G01", severity="high",
    ))
    risk = siem.risk.calculate(db)
    assert risk["event_count"] == 1
    assert risk["signal_count"] == 1
    assert risk["score"] == 30
    assert risk["level"] == "medium"
    db.close()


def test_risk_deduplicates_flood_burst_per_device_type():
    db = make_db()
    siem = SmartPortSiem(db)
    for i in range(50):
        siem.collect(SiemEventIn(
            source="network", event_type="network_flood", device_id="temp_01",
            message=f"Flood réseau temp_01 #{i}", severity="high",
        ))
    risk = siem.risk.calculate(db)
    assert risk["event_count"] == 50
    assert risk["signal_count"] == 1
    assert risk["score"] == 30
    db.close()
