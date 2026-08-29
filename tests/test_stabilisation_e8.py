"""Stabilisation tests for Step 8 — TelemetryIn / CommonEvent contract fixes.

Corrections verified
--------------------
B1 / P3 : TelemetryIn.status now accepts bool | str | None (was Optional[str]).
P2 / I3 : TelemetryIn now carries latitude / longitude (were absent).
P4 / I2 : TelemetryIn now carries port_src (was absent).
SIEM-UDP : SOURCES now includes "udp" (was missing, causing ValidationError).

Each section maps to one correction and covers MQTT, HTTP and/or UDP as relevant.
No ML, SIEM, Dashboard or CommonEvent consumer wiring is done here.

Design constraints
------------------
- No DB, no broker, no filesystem, no FastAPI startup.
- External collaborators mocked at the module boundary.
- CommonEvent is verified only via type inspection — never mutated.
- SensorReading construction is verified by inspecting mock call-args.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers shared across sections
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _make_platform_service_mock():
    svc = MagicMock()
    svc.ingest_telemetry.return_value = {"accepted": True, "alerts": 0, "severity": "green"}
    return svc


def _make_db_mock():
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    return db


# ===========================================================================
# SECTION 1 — B1/P3 : TelemetryIn.status accepts bool | str | None
# ===========================================================================

class TestTelemetryInStatusBool(unittest.TestCase):
    """TelemetryIn must accept status=True, status=False and status=None without
    raising a Pydantic ValidationError."""

    def _make(self, **kwargs):
        from backend.schemas.platform import TelemetryIn
        return TelemetryIn(device_id="parking_P01", type="presence", **kwargs)

    def test_status_true_accepted(self):
        ti = self._make(status=True)
        self.assertIs(ti.status, True)
        self.assertIs(type(ti.status), bool)

    def test_status_false_accepted(self):
        ti = self._make(status=False)
        self.assertIs(ti.status, False)
        self.assertIs(type(ti.status), bool)

    def test_status_string_accepted(self):
        ti = self._make(status="active")
        self.assertEqual(ti.status, "active")
        self.assertIs(type(ti.status), str)

    def test_status_none_accepted(self):
        ti = self._make(status=None)
        self.assertIsNone(ti.status)

    def test_status_bool_not_cast_to_str_in_telemetry_in(self):
        """TelemetryIn must preserve the bool — not coerce it to 'True'."""
        ti = self._make(status=True)
        self.assertNotEqual(ti.status, "True")
        self.assertIs(type(ti.status), bool)

    def test_status_default_is_none(self):
        from backend.schemas.platform import TelemetryIn
        ti = TelemetryIn(device_id="x", type="temperature")
        self.assertIsNone(ti.status)


# ===========================================================================
# SECTION 2 — B1/P3 : CommonEvent.data.status preserves bool (all transports)
# ===========================================================================

class TestCommonEventStatusBoolMqtt(unittest.TestCase):
    """MQTT: CommonEvent.data.status must be a bool for presence payloads."""

    def setUp(self):
        from backend import mqtt_listener
        self.db = _make_db_mock()
        self.patches = [
            patch.object(mqtt_listener, "SessionLocal", return_value=self.db),
            patch.object(mqtt_listener, "write_event"),
            patch.object(mqtt_listener, "process_network_data",
                         return_value={"ip_src": "192.168.1.60", "mac_src": "AA:BB:CC:DD:EE:08",
                                       "packet_count": 1, "bytes_total": 50,
                                       "avg_interval": 0.0, "throughput": 0.0, "duration": 0.0}),
            patch.object(mqtt_listener, "make_decision",
                         return_value={"device_id": "parking_P01", "anomaly": False,
                                       "anomaly_score": 0.0, "threat_level": "green",
                                       "dispatch_recommended": False, "create_mission": False,
                                       "alerts": [], "ai_predictions": []}),
            patch.object(mqtt_listener, "SmartPortSiem"),
            patch.object(mqtt_listener, "ActionDispatcher"),
            patch.object(mqtt_listener, "_publish_dashboard", new_callable=AsyncMock),
            patch.object(mqtt_listener, "drone_manager"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _capture(self, payload):
        from backend import mqtt_listener
        captured = {}

        def spy(raw, tr):
            from backend.events.normalizer import EventNormalizer as EN
            evt = EN.normalize(raw, tr)
            captured["event"] = evt
            return evt

        with patch.object(mqtt_listener, "EventNormalizer") as mock_en:
            mock_en.normalize.side_effect = spy
            _run(mqtt_listener.process_message(payload))
        return captured.get("event")

    def test_mqtt_status_true_is_bool_in_common_event(self):
        payload = {
            "device_id": "parking_P01", "type": "presence",
            "status": True, "timestamp": 5.0,
            "token": "tk_pres444", "mqtt_topic": "port/parking/presence",
            "ip_src": "192.168.1.60", "mac_src": "AA:BB:CC:DD:EE:08", "port_src": 1883,
        }
        e = self._capture(payload)
        self.assertIs(e.data.status, True)
        self.assertIs(type(e.data.status), bool)

    def test_mqtt_status_false_is_bool_in_common_event(self):
        payload = {
            "device_id": "parking_P01", "type": "presence",
            "status": False, "timestamp": 5.0,
            "token": "tk_pres444", "mqtt_topic": "port/parking/presence",
            "ip_src": "192.168.1.60", "mac_src": "AA:BB:CC:DD:EE:08", "port_src": 1883,
        }
        e = self._capture(payload)
        self.assertIs(e.data.status, False)
        self.assertIs(type(e.data.status), bool)


class TestCommonEventStatusBoolHttp(unittest.TestCase):
    """HTTP: CommonEvent.data.status preserves bool from TelemetryIn."""

    def _make_service(self):
        from backend.services.platform_service import PlatformService
        db = MagicMock()
        lake = MagicMock()
        siem = MagicMock()
        siem.evaluate.return_value = {"alerts": [], "correlation": {"severity": "green"}}
        return PlatformService(db, lake=lake, siem=siem)

    def _capture(self, payload_kwargs):
        import backend.services.platform_service as ps_mod
        from backend.schemas.platform import TelemetryIn
        service = self._make_service()
        captured = {}

        def spy(raw, tr):
            from backend.events.normalizer import EventNormalizer as EN
            evt = EN.normalize(raw, tr)
            captured["event"] = evt
            return evt

        with patch.object(ps_mod, "EventNormalizer") as mock_en, \
             patch.object(ps_mod, "SmartPortSiem"):
            mock_en.normalize.side_effect = spy
            service.ingest_telemetry(TelemetryIn(**payload_kwargs), transport="http")
        return captured.get("event")

    def test_http_status_true_preserved_in_common_event(self):
        e = self._capture({
            "device_id": "parking_P01", "type": "presence",
            "status": True, "timestamp": 5.0, "token": "tk_pres444",
        })
        self.assertIs(e.data.status, True)
        self.assertIs(type(e.data.status), bool)

    def test_http_status_false_preserved_in_common_event(self):
        e = self._capture({
            "device_id": "parking_P01", "type": "presence",
            "status": False, "timestamp": 5.0, "token": "tk_pres444",
        })
        self.assertIs(e.data.status, False)
        self.assertIs(type(e.data.status), bool)

    def test_http_status_string_preserved_in_common_event(self):
        e = self._capture({
            "device_id": "portail_N01", "type": "barrier",
            "status": "open", "timestamp": 6.0, "token": "tk_gate222",
        })
        self.assertEqual(e.data.status, "open")
        self.assertIs(type(e.data.status), str)


class TestCommonEventStatusBoolUdp(unittest.TestCase):
    """UDP: CommonEvent.data.status preserves bool from raw dict."""

    def setUp(self):
        import backend.main as main_mod
        self.db = _make_db_mock()
        self.platform_svc = _make_platform_service_mock()
        self.patches = [
            patch.object(main_mod, "SessionLocal", return_value=self.db),
            patch.object(main_mod, "PlatformService", return_value=self.platform_svc),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _capture(self, payload):
        import backend.main as main_mod
        captured = {}

        def spy(raw, tr):
            from backend.events.normalizer import EventNormalizer as EN
            evt = EN.normalize(raw, tr)
            captured["event"] = evt
            return evt

        with patch.object(main_mod, "EventNormalizer") as mock_en:
            mock_en.normalize.side_effect = spy
            _run(main_mod.ingest_udp_payload(payload))
        return captured.get("event")

    def test_udp_status_true_preserved_in_common_event(self):
        e = self._capture({
            "device_id": "parking_P01", "type": "presence",
            "status": True, "timestamp": 5.0, "token": "tk_pres444",
        })
        self.assertIs(e.data.status, True)
        self.assertIs(type(e.data.status), bool)

    def test_udp_status_false_preserved_in_common_event(self):
        e = self._capture({
            "device_id": "parking_P01", "type": "presence",
            "status": False, "timestamp": 5.0, "token": "tk_pres444",
        })
        self.assertIs(e.data.status, False)
        self.assertIs(type(e.data.status), bool)

    def test_udp_bool_status_now_reaches_ingest_telemetry(self):
        """B1 fixed: TelemetryIn now accepts bool status, so ingest_telemetry
        must be called even when status=True."""
        _run(__import__("backend.main", fromlist=["ingest_udp_payload"]).ingest_udp_payload({
            "device_id": "parking_P01", "type": "presence",
            "status": True, "timestamp": 5.0, "token": "tk_pres444",
        }))
        self.platform_svc.ingest_telemetry.assert_called_once()


# ===========================================================================
# SECTION 3 — P2/I3 : latitude/longitude conservés HTTP et UDP
# ===========================================================================

class TestLatitudeLongitudeHttp(unittest.TestCase):
    """HTTP GPS payload: latitude/longitude must now reach TelemetryIn and
    flow through to CommonEvent and SensorReading."""

    def _make_service(self):
        from backend.services.platform_service import PlatformService
        db = MagicMock()
        lake = MagicMock()
        siem = MagicMock()
        siem.evaluate.return_value = {"alerts": [], "correlation": {"severity": "green"}}
        svc = PlatformService(db, lake=lake, siem=siem)
        return svc, db

    def test_telemetry_in_accepts_latitude_longitude(self):
        from backend.schemas.platform import TelemetryIn
        ti = TelemetryIn(device_id="camion_C12", type="gps",
                         latitude=35.767, longitude=-5.800, timestamp=7.0, token="tk_gps111")
        self.assertAlmostEqual(ti.latitude, 35.767, places=3)
        self.assertAlmostEqual(ti.longitude, -5.800, places=3)

    def test_http_gps_latitude_in_common_event(self):
        import backend.services.platform_service as ps_mod
        from backend.schemas.platform import TelemetryIn
        service, _ = self._make_service()
        captured = {}

        def spy(raw, tr):
            from backend.events.normalizer import EventNormalizer as EN
            evt = EN.normalize(raw, tr)
            captured["event"] = evt
            return evt

        with patch.object(ps_mod, "EventNormalizer") as mock_en, \
             patch.object(ps_mod, "SmartPortSiem"):
            mock_en.normalize.side_effect = spy
            service.ingest_telemetry(
                TelemetryIn(device_id="camion_C12", type="gps",
                            latitude=35.767, longitude=-5.800,
                            timestamp=7.0, token="tk_gps111"),
                transport="http",
            )
        self.assertAlmostEqual(captured["event"].data.latitude, 35.767, places=3)
        self.assertAlmostEqual(captured["event"].data.longitude, -5.800, places=3)

    def test_http_gps_latitude_reaches_sensor_reading(self):
        """latitude/longitude must now be passed to SensorReading constructor."""
        import backend.services.platform_service as ps_mod
        from backend.schemas.platform import TelemetryIn
        service, db = self._make_service()

        with patch.object(ps_mod, "SensorReading") as mock_sr, \
             patch.object(ps_mod, "SmartPortSiem"), \
             patch.object(ps_mod, "EventNormalizer") as mock_en:
            mock_en.normalize.return_value = MagicMock()
            service.ingest_telemetry(
                TelemetryIn(device_id="camion_C12", type="gps",
                            latitude=35.767, longitude=-5.800,
                            timestamp=7.0, token="tk_gps111"),
                transport="http",
            )

        kwargs = mock_sr.call_args[1]
        self.assertAlmostEqual(kwargs["latitude"], 35.767, places=3)
        self.assertAlmostEqual(kwargs["longitude"], -5.800, places=3)

    def test_http_non_gps_latitude_is_none(self):
        """Non-GPS payloads carry no lat/lon — both must be None in CommonEvent."""
        import backend.services.platform_service as ps_mod
        from backend.schemas.platform import TelemetryIn
        service, _ = self._make_service()
        captured = {}

        def spy(raw, tr):
            from backend.events.normalizer import EventNormalizer as EN
            evt = EN.normalize(raw, tr)
            captured["event"] = evt
            return evt

        with patch.object(ps_mod, "EventNormalizer") as mock_en, \
             patch.object(ps_mod, "SmartPortSiem"):
            mock_en.normalize.side_effect = spy
            service.ingest_telemetry(
                TelemetryIn(device_id="grue_G01", type="temperature", value=28.5,
                            timestamp=1.0, token="tk_temp123"),
                transport="http",
            )
        self.assertIsNone(captured["event"].data.latitude)
        self.assertIsNone(captured["event"].data.longitude)


class TestLatitudeLongitudeUdp(unittest.TestCase):
    """UDP GPS payload: latitude/longitude must flow through TelemetryIn and
    be accepted by ingest_telemetry without rejection."""

    def setUp(self):
        import backend.main as main_mod
        self.db = _make_db_mock()
        self.platform_svc = _make_platform_service_mock()
        self.patches = [
            patch.object(main_mod, "SessionLocal", return_value=self.db),
            patch.object(main_mod, "PlatformService", return_value=self.platform_svc),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_udp_gps_ingest_telemetry_called_with_lat_lon(self):
        """TelemetryIn now accepts lat/lon so ingest_telemetry must be called."""
        import backend.main as main_mod
        _run(main_mod.ingest_udp_payload({
            "device_id": "camion_C12", "type": "gps",
            "latitude": 35.767, "longitude": -5.800,
            "timestamp": 7.0, "token": "tk_gps111",
        }))
        self.platform_svc.ingest_telemetry.assert_called_once()
        ti = self.platform_svc.ingest_telemetry.call_args[0][0]
        self.assertAlmostEqual(ti.latitude, 35.767, places=3)
        self.assertAlmostEqual(ti.longitude, -5.800, places=3)

    def test_udp_gps_latitude_in_common_event(self):
        import backend.main as main_mod
        captured = {}

        def spy(raw, tr):
            from backend.events.normalizer import EventNormalizer as EN
            evt = EN.normalize(raw, tr)
            captured["event"] = evt
            return evt

        with patch.object(main_mod, "EventNormalizer") as mock_en:
            mock_en.normalize.side_effect = spy
            _run(main_mod.ingest_udp_payload({
                "device_id": "camion_C12", "type": "gps",
                "latitude": 35.767, "longitude": -5.800,
                "timestamp": 7.0, "token": "tk_gps111",
            }))
        self.assertAlmostEqual(captured["event"].data.latitude, 35.767, places=3)
        self.assertAlmostEqual(captured["event"].data.longitude, -5.800, places=3)


# ===========================================================================
# SECTION 4 — P4/I2 : port_src conservé HTTP et UDP
# ===========================================================================

class TestPortSrcHttp(unittest.TestCase):
    """HTTP: port_src now accepted by TelemetryIn and passed to SensorReading."""

    def test_telemetry_in_accepts_port_src(self):
        from backend.schemas.platform import TelemetryIn
        ti = TelemetryIn(device_id="grue_G01", type="temperature", value=28.5,
                         port_src=1883, token="tk_temp123")
        self.assertEqual(ti.port_src, 1883)

    def test_telemetry_in_port_src_none_by_default(self):
        from backend.schemas.platform import TelemetryIn
        ti = TelemetryIn(device_id="grue_G01", type="temperature", value=28.5,
                         token="tk_temp123")
        self.assertIsNone(ti.port_src)

    def test_http_port_src_reaches_sensor_reading(self):
        import backend.services.platform_service as ps_mod
        from backend.schemas.platform import TelemetryIn
        db = MagicMock()
        lake = MagicMock()
        siem = MagicMock()
        siem.evaluate.return_value = {"alerts": [], "correlation": {"severity": "green"}}
        from backend.services.platform_service import PlatformService
        service = PlatformService(db, lake=lake, siem=siem)

        with patch.object(ps_mod, "SensorReading") as mock_sr, \
             patch.object(ps_mod, "SmartPortSiem"), \
             patch.object(ps_mod, "EventNormalizer") as mock_en:
            mock_en.normalize.return_value = MagicMock()
            service.ingest_telemetry(
                TelemetryIn(device_id="grue_G01", type="temperature", value=28.5,
                            port_src=9000, timestamp=1.0, token="tk_temp123"),
                transport="http",
            )

        kwargs = mock_sr.call_args[1]
        self.assertEqual(kwargs["port_src"], 9000)

    def test_http_port_src_none_when_absent(self):
        import backend.services.platform_service as ps_mod
        from backend.schemas.platform import TelemetryIn
        db = MagicMock()
        lake = MagicMock()
        siem = MagicMock()
        siem.evaluate.return_value = {"alerts": [], "correlation": {"severity": "green"}}
        from backend.services.platform_service import PlatformService
        service = PlatformService(db, lake=lake, siem=siem)

        with patch.object(ps_mod, "SensorReading") as mock_sr, \
             patch.object(ps_mod, "SmartPortSiem"), \
             patch.object(ps_mod, "EventNormalizer") as mock_en:
            mock_en.normalize.return_value = MagicMock()
            service.ingest_telemetry(
                TelemetryIn(device_id="grue_G01", type="temperature", value=28.5,
                            timestamp=1.0, token="tk_temp123"),
                transport="http",
            )

        kwargs = mock_sr.call_args[1]
        self.assertIsNone(kwargs["port_src"])


class TestPortSrcUdp(unittest.TestCase):
    """UDP: port_src flows through TelemetryIn to ingest_telemetry."""

    def setUp(self):
        import backend.main as main_mod
        self.db = _make_db_mock()
        self.platform_svc = _make_platform_service_mock()
        self.patches = [
            patch.object(main_mod, "SessionLocal", return_value=self.db),
            patch.object(main_mod, "PlatformService", return_value=self.platform_svc),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_udp_port_src_passed_to_telemetry_in(self):
        import backend.main as main_mod
        _run(main_mod.ingest_udp_payload({
            "device_id": "grue_G01", "type": "temperature", "value": 28.3,
            "timestamp": 1.0, "token": "tk_temp123",
            "ip_src": "192.168.1.10", "mac_src": "AA:BB:CC:DD:EE:01", "port_src": 1883,
        }))
        self.platform_svc.ingest_telemetry.assert_called_once()
        ti = self.platform_svc.ingest_telemetry.call_args[0][0]
        self.assertEqual(ti.port_src, 1883)


# ===========================================================================
# SECTION 5 — SIEM source="udp" accepted
# ===========================================================================

class TestSiemUdpSource(unittest.TestCase):
    """SiemEventIn must accept source='udp' after adding it to SOURCES."""

    def test_udp_source_accepted_by_siem_event_in(self):
        from backend.schemas.siem import SiemEventIn
        event = SiemEventIn(
            source="udp",
            event_type="telemetry_ingested",
            message="UDP telemetry accepted from camion_C12",
            device_id="camion_C12",
        )
        self.assertEqual(event.source, "udp")

    def test_udp_in_sources_set(self):
        from backend.siem.contracts import SOURCES
        self.assertIn("udp", SOURCES)

    def test_existing_sources_still_present(self):
        from backend.siem.contracts import SOURCES
        for src in ("mqtt", "http", "drone", "ros2", "auth", "sensor", "network"):
            with self.subTest(source=src):
                self.assertIn(src, SOURCES)

    def test_unknown_source_still_rejected(self):
        from backend.schemas.siem import SiemEventIn
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            SiemEventIn(source="ftp", event_type="x", message="x")

    def test_udp_source_case_insensitive(self):
        """Validator lowercases the source before checking."""
        from backend.schemas.siem import SiemEventIn
        event = SiemEventIn(source="UDP", event_type="x", message="x")
        self.assertEqual(event.source, "udp")


# ===========================================================================
# SECTION 6 — SensorReading receives bool status as str (DB boundary)
# ===========================================================================

class TestSensorReadingStatusConversion(unittest.TestCase):
    """PlatformService converts bool status to str at the SensorReading boundary
    to maintain compatibility with the existing String column in DB.
    CommonEvent is NOT affected — it still receives the original bool."""

    def _ingest(self, status_value):
        import backend.services.platform_service as ps_mod
        from backend.schemas.platform import TelemetryIn
        from backend.services.platform_service import PlatformService
        db = MagicMock()
        lake = MagicMock()
        siem = MagicMock()
        siem.evaluate.return_value = {"alerts": [], "correlation": {"severity": "green"}}
        service = PlatformService(db, lake=lake, siem=siem)

        with patch.object(ps_mod, "SensorReading") as mock_sr, \
             patch.object(ps_mod, "SmartPortSiem"), \
             patch.object(ps_mod, "EventNormalizer") as mock_en:
            mock_en.normalize.return_value = MagicMock()
            service.ingest_telemetry(
                TelemetryIn(device_id="parking_P01", type="presence",
                            status=status_value, timestamp=5.0, token="tk_pres444"),
                transport="http",
            )
        return mock_sr.call_args[1]["status"]

    def test_bool_true_becomes_str_in_sensor_reading(self):
        result = self._ingest(True)
        self.assertIsInstance(result, str)
        self.assertEqual(result, "True")

    def test_bool_false_becomes_str_in_sensor_reading(self):
        result = self._ingest(False)
        self.assertIsInstance(result, str)
        self.assertEqual(result, "False")

    def test_str_status_unchanged_in_sensor_reading(self):
        result = self._ingest("open")
        self.assertIsInstance(result, str)
        self.assertEqual(result, "open")

    def test_none_status_unchanged_in_sensor_reading(self):
        result = self._ingest(None)
        self.assertIsNone(result)


# ===========================================================================
# SECTION 7 — CommonEvent unchanged for non-presence payloads (non-regression)
# ===========================================================================

class TestCommonEventNonRegressionE8(unittest.TestCase):
    """Verify that existing CommonEvent behaviour is unaffected by Step 8 changes."""

    def _normalize(self, payload, transport="mqtt"):
        from backend.events.normalizer import EventNormalizer
        from backend.events.contracts import Transport
        t = Transport(transport)
        return EventNormalizer.normalize(payload, t)

    def test_temperature_value_unchanged(self):
        e = self._normalize({"device_id": "grue_G01", "type": "temperature",
                             "value": 28.3, "unit": "°C", "timestamp": 1.0,
                             "token": "tk_temp123"})
        self.assertAlmostEqual(e.data.value, 28.3)
        self.assertEqual(e.data.unit, "°C")
        self.assertIsNone(e.data.status)

    def test_humidity_unchanged(self):
        e = self._normalize({"device_id": "station_H01", "type": "humidity",
                             "value": 62.5, "unit": "%", "timestamp": 2.0})
        self.assertEqual(e.data.value, 62.5)

    def test_gps_lat_lon_mqtt(self):
        e = self._normalize({"device_id": "camion_C12", "type": "gps",
                             "latitude": 35.767, "longitude": -5.800, "timestamp": 7.0})
        self.assertAlmostEqual(e.data.latitude, 35.767, places=3)
        self.assertAlmostEqual(e.data.longitude, -5.800, places=3)

    def test_drone_telemetry_kind_unchanged(self):
        from backend.events.contracts import EventKind
        e = self._normalize({"device_id": "drone_01", "type": "drone",
                             "status": "flying", "timestamp": 8.0,
                             "mqtt_topic": "drone/telemetry"})
        self.assertEqual(e.event_kind, EventKind.DRONE_TELEMETRY)
        self.assertEqual(e.data.status, "flying")

    def test_raw_payload_independence(self):
        p = {"device_id": "x", "type": "t", "value": 1.0, "timestamp": 1.0}
        e = self._normalize(p)
        p["value"] = 999.0
        self.assertNotEqual(e.raw_payload.get("value"), 999.0)

    def test_event_id_unique_per_call(self):
        p = {"device_id": "x", "type": "t", "timestamp": 1.0}
        e1 = self._normalize(p)
        e2 = self._normalize(p)
        self.assertNotEqual(e1.event_id, e2.event_id)

    def test_network_metrics_still_none(self):
        """No network metrics must be invented — Step 8 must not change this."""
        e = self._normalize({"device_id": "x", "type": "t", "timestamp": 1.0,
                             "ip_src": "192.168.1.10", "port_src": 1883})
        n = e.network
        for field in ("destination_port", "latency", "throughput",
                      "packet_count", "bytes_total", "avg_interval", "packet_size"):
            with self.subTest(field=field):
                self.assertIsNone(getattr(n, field))

    def test_observed_simulated_invariant(self):
        e = self._normalize({"device_id": "x", "type": "t", "timestamp": 1.0})
        self.assertIs(e.network.observed, False)
        self.assertIs(e.network.simulated, True)


if __name__ == "__main__":
    unittest.main()
