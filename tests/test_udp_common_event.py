"""Regression + integration tests for the CommonEvent envelope in the UDP pipeline.

Scope
-----
Verify that ingest_udp_payload() now produces a CommonEvent from the original
raw UDP dict, WITHOUT altering any existing behaviour:

- The CommonEvent is produced BEFORE TelemetryIn(**payload) strips unknown
  fields (latitude, longitude, bool status, port_src, extra keys…).
- EventNormalizer.normalize() is called with the raw dict and Transport.UDP.
- All existing consumers (SessionLocal, PlatformService) still receive their
  expected inputs unmodified.
- GPS fields (latitude, longitude) are captured in the CommonEvent even though
  TelemetryIn has no such fields.
- bool status (presence sensor) is preserved verbatim in the CommonEvent;
  TelemetryIn would cast it to str, but the CommonEvent sees the original bool.
- port_src from the UDP payload maps to network.source_port in the CommonEvent.
- observed=False and simulated=True are invariant.
- No network metrics are invented (destination_port, packet_size, latency,
  throughput, packet_count, bytes_total, avg_interval all remain None).
- raw_payload is a shallow copy independent from the caller's dict.
- Unknown/extra fields end up in CommonEvent.metadata.
- transport is Transport.UDP.

Design constraints
------------------
- No real DB, no UDP socket, no FastAPI startup, no MQTT broker.
- SessionLocal and PlatformService are mocked at the backend.main boundary.
- Only backend.main.ingest_udp_payload and backend.events.* are exercised as
  real code.
- Each test method is self-contained; no shared mutable state.

GPS critical test
-----------------
TestUdpGpsPayload verifies that latitude and longitude from the raw UDP dict
reach CommonEvent.data.latitude / CommonEvent.data.longitude even though
TelemetryIn drops those fields.  This is the key regression guard for the
GPS perte identified in the Step 6 report.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import backend.main as main_module
from backend.main import ingest_udp_payload
from backend.events.contracts import EventKind, Transport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine synchronously in a fresh event loop."""
    return asyncio.run(coro)


def _make_db_mock():
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    return db


def _mock_platform_service():
    """Return a MagicMock PlatformService whose ingest_telemetry returns a green result."""
    svc = MagicMock()
    svc.ingest_telemetry.return_value = {"accepted": True, "alerts": 0, "severity": "green"}
    return svc


# ---------------------------------------------------------------------------
# Base class: mock all external I/O collaborators
# ---------------------------------------------------------------------------

class UdpIngestBase(unittest.TestCase):
    """Mock SessionLocal and PlatformService so no DB or network is touched."""

    def setUp(self):
        self.db = _make_db_mock()
        self.platform_svc = _mock_platform_service()
        self.patches = [
            patch.object(main_module, "SessionLocal", return_value=self.db),
            patch.object(main_module, "PlatformService", return_value=self.platform_svc),
        ]
        self.mocks = [p.start() for p in self.patches]

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _capture_common_event(self, payload: dict) -> object:
        """Run ingest_udp_payload with a spy on EventNormalizer, return captured event."""
        captured = {}

        def spy(raw, transport):
            from backend.events.normalizer import EventNormalizer as EN
            evt = EN.normalize(raw, transport)
            captured["event"] = evt
            return evt

        with patch.object(main_module, "EventNormalizer") as mock_en:
            mock_en.normalize.side_effect = spy
            _run(ingest_udp_payload(payload))

        return captured.get("event")


# ===========================================================================
# TEST A — Transport and kind: IoT temperature
# ===========================================================================

class TestUdpTemperatureEvent(UdpIngestBase):
    """UDP temperature payload → IOT_TELEMETRY + Transport.UDP."""

    def setUp(self):
        super().setUp()
        self.payload = {
            "device_id": "grue_G01",
            "type": "temperature",
            "value": 28.3,
            "unit": "°C",
            "timestamp": 1_700_000_000.0,
            "token": "tk_temp123",
            "ip_src": "192.168.1.10",
            "mac_src": "AA:BB:CC:DD:EE:01",
            "port_src": 1883,
            "transport": "udp",
            "source_address": "192.168.1.10",
        }

    def test_event_kind_iot_telemetry(self):
        e = self._capture_common_event(self.payload)
        self.assertEqual(e.event_kind, EventKind.IOT_TELEMETRY)

    def test_transport_is_udp(self):
        e = self._capture_common_event(self.payload)
        self.assertEqual(e.transport, Transport.UDP)

    def test_device_id(self):
        e = self._capture_common_event(self.payload)
        self.assertEqual(e.device.device_id, "grue_G01")

    def test_device_type(self):
        e = self._capture_common_event(self.payload)
        self.assertEqual(e.device.device_type, "temperature")

    def test_value(self):
        e = self._capture_common_event(self.payload)
        self.assertAlmostEqual(e.data.value, 28.3)

    def test_unit(self):
        e = self._capture_common_event(self.payload)
        self.assertEqual(e.data.unit, "°C")

    def test_timestamp(self):
        e = self._capture_common_event(self.payload)
        self.assertEqual(e.occurred_at, 1_700_000_000.0)

    def test_token(self):
        e = self._capture_common_event(self.payload)
        self.assertEqual(e.identity.token, "tk_temp123")

    def test_normalizer_called_exactly_once(self):
        with patch.object(main_module, "EventNormalizer") as mock_en:
            mock_en.normalize.return_value = MagicMock()
            _run(ingest_udp_payload(self.payload))
        mock_en.normalize.assert_called_once()

    def test_normalizer_called_with_udp_transport(self):
        with patch.object(main_module, "EventNormalizer") as mock_en:
            mock_en.normalize.return_value = MagicMock()
            _run(ingest_udp_payload(self.payload))
        _, transport_arg = mock_en.normalize.call_args[0]
        self.assertEqual(transport_arg, Transport.UDP)


# ===========================================================================
# TEST B — Humidity
# ===========================================================================

class TestUdpHumidityEvent(UdpIngestBase):
    """UDP humidity payload → IOT_TELEMETRY."""

    def test_humidity_iot_telemetry(self):
        payload = {
            "device_id": "station_H01", "type": "humidity",
            "value": 62.5, "unit": "%", "timestamp": 2.0,
            "token": "tk_hum456",
            "ip_src": "192.168.1.11", "mac_src": "AA:BB:CC:DD:EE:02", "port_src": 1883,
        }
        e = self._capture_common_event(payload)
        self.assertEqual(e.event_kind, EventKind.IOT_TELEMETRY)
        self.assertEqual(e.device.device_type, "humidity")
        self.assertAlmostEqual(e.data.value, 62.5)
        self.assertEqual(e.data.unit, "%")
        self.assertEqual(e.identity.token, "tk_hum456")


# ===========================================================================
# TEST C — Vibration
# ===========================================================================

class TestUdpVibrationEvent(UdpIngestBase):
    """UDP vibration payload → IOT_TELEMETRY."""

    def test_vibration_iot_telemetry(self):
        payload = {
            "device_id": "portique_P01", "type": "vibration",
            "value": 0.3, "unit": "g", "timestamp": 3.0,
            "token": "tk_vib789",
            "ip_src": "192.168.1.12", "mac_src": "AA:BB:CC:DD:EE:03", "port_src": 1883,
        }
        e = self._capture_common_event(payload)
        self.assertEqual(e.event_kind, EventKind.IOT_TELEMETRY)
        self.assertAlmostEqual(e.data.value, 0.3)
        self.assertEqual(e.data.unit, "g")
        self.assertIsNone(e.data.status)


# ===========================================================================
# TEST D — Presence with bool status (KEY regression guard)
# ===========================================================================

class TestUdpPresenceBoolStatus(UdpIngestBase):
    """bool status from presence sensor must be preserved verbatim in CommonEvent.

    Step 8 fix (B1/P3): TelemetryIn.status is now Optional[Union[bool, str]].
    Pydantic no longer rejects status=True; the CommonEvent continues to see the
    original bool because it is built from the raw dict BEFORE TelemetryIn(**payload).
    """

    def test_status_true_is_bool_in_common_event(self):
        payload = {
            "device_id": "parking_P01", "type": "presence",
            "status": True, "timestamp": 5.0,
            "token": "tk_pres444",
            "ip_src": "192.168.1.60", "mac_src": "AA:BB:CC:DD:EE:08", "port_src": 1883,
        }
        e = self._capture_common_event(payload)
        self.assertIs(e.data.status, True)
        self.assertIs(type(e.data.status), bool)

    def test_status_false_is_bool_in_common_event(self):
        payload = {
            "device_id": "parking_P01", "type": "presence",
            "status": False, "timestamp": 5.0,
            "token": "tk_pres444",
            "ip_src": "192.168.1.60", "mac_src": "AA:BB:CC:DD:EE:08", "port_src": 1883,
        }
        e = self._capture_common_event(payload)
        self.assertIs(e.data.status, False)
        self.assertIs(type(e.data.status), bool)

    def test_existing_pipeline_receives_pydantic_payload(self):
        """Step 8 fix (B1): TelemetryIn now accepts status=True (bool).
        PlatformService.ingest_telemetry must be called successfully — no more
        ValidationError.  db.close() must also be called.
        """
        payload = {
            "device_id": "parking_P01", "type": "presence",
            "status": True, "timestamp": 5.0, "token": "tk_pres444",
        }
        _run(ingest_udp_payload(payload))
        # B1 fixed: ingest_telemetry is now called (no more ValidationError)
        self.platform_svc.ingest_telemetry.assert_called_once()
        self.db.close.assert_called_once()


# ===========================================================================
# TEST E — GPS payload: latitude/longitude preserved (KEY GPS guard)
# ===========================================================================

class TestUdpGpsPayload(UdpIngestBase):
    """GPS payload: latitude and longitude must reach CommonEvent even though
    TelemetryIn has no such fields.

    This is the critical test for the GPS loss issue identified in Step 6.
    The CommonEvent is built from the raw dict BEFORE TelemetryIn strips them.
    """

    def setUp(self):
        super().setUp()
        self.payload = {
            "device_id": "camion_C12",
            "type": "gps",
            "latitude": 35.767,
            "longitude": -5.800,
            "timestamp": 7.0,
            "token": "tk_gps111",
            "ip_src": "192.168.1.30",
            "mac_src": "AA:BB:CC:DD:EE:05",
            "port_src": 1883,
        }

    def test_latitude_preserved_in_common_event(self):
        """latitude from raw UDP dict must reach CommonEvent.data.latitude."""
        e = self._capture_common_event(self.payload)
        self.assertAlmostEqual(e.data.latitude, 35.767, places=3)

    def test_longitude_preserved_in_common_event(self):
        """longitude from raw UDP dict must reach CommonEvent.data.longitude."""
        e = self._capture_common_event(self.payload)
        self.assertAlmostEqual(e.data.longitude, -5.800, places=3)

    def test_gps_event_kind(self):
        e = self._capture_common_event(self.payload)
        self.assertEqual(e.event_kind, EventKind.IOT_TELEMETRY)

    def test_gps_device_id(self):
        e = self._capture_common_event(self.payload)
        self.assertEqual(e.device.device_id, "camion_C12")

    def test_gps_device_type(self):
        e = self._capture_common_event(self.payload)
        self.assertEqual(e.device.device_type, "gps")

    def test_gps_value_is_none(self):
        """GPS payloads have no 'value' field; data.value must be None."""
        e = self._capture_common_event(self.payload)
        self.assertIsNone(e.data.value)

    def test_gps_token(self):
        e = self._capture_common_event(self.payload)
        self.assertEqual(e.identity.token, "tk_gps111")

    def test_gps_latitude_longitude_in_raw_payload(self):
        """raw_payload must also preserve latitude and longitude."""
        e = self._capture_common_event(self.payload)
        self.assertAlmostEqual(e.raw_payload.get("latitude"), 35.767, places=3)
        self.assertAlmostEqual(e.raw_payload.get("longitude"), -5.800, places=3)

    def test_telemetry_in_now_preserves_lat_lon(self):
        """Step 8 fix (P2/I3): TelemetryIn now has latitude/longitude fields.
        Both the TelemetryIn object and the CommonEvent must carry them.
        """
        from backend.schemas.platform import TelemetryIn
        # TelemetryIn now has latitude/longitude — no longer dropped.
        ti = TelemetryIn(**self.payload)
        self.assertTrue(hasattr(ti, "latitude"))
        self.assertTrue(hasattr(ti, "longitude"))
        self.assertAlmostEqual(ti.latitude, 35.767, places=3)
        self.assertAlmostEqual(ti.longitude, -5.800, places=3)
        # The CommonEvent also retains them (built before TelemetryIn):
        e = self._capture_common_event(self.payload)
        self.assertIsNotNone(e.data.latitude)
        self.assertIsNotNone(e.data.longitude)


# ===========================================================================
# TEST F — Drone telemetry via UDP
# ===========================================================================

class TestUdpDroneTelemetry(UdpIngestBase):
    """Drone telemetry via UDP must be classified as DRONE_TELEMETRY."""

    def test_drone_telemetry_classification(self):
        payload = {
            "device_id": "drone_01", "type": "drone",
            "x": 1.0, "y": 2.0, "altitude": 5.0, "battery": 88.0,
            "status": "flying", "timestamp": 8.0,
            "token": "tk_drone_secure_001",
            "ip_src": "192.168.1.101", "mac_src": "AA:BB:CC:DD:EE:11", "port_src": 1883,
        }
        e = self._capture_common_event(payload)
        self.assertEqual(e.event_kind, EventKind.DRONE_TELEMETRY)

    def test_drone_gps_classification(self):
        payload = {
            "device_id": "drone_01", "type": "drone_gps",
            "latitude": 2.0, "longitude": 3.0, "altitude": 10.0,
            "timestamp": 9.0, "token": "tk_drone_secure_001",
        }
        e = self._capture_common_event(payload)
        self.assertEqual(e.event_kind, EventKind.DRONE_TELEMETRY)

    def test_drone_event_classification(self):
        payload = {
            "device_id": "drone_01", "type": "drone_event",
            "event_type": "mission_completed", "timestamp": 10.0,
            "token": "tk_drone_secure_001",
        }
        e = self._capture_common_event(payload)
        self.assertEqual(e.event_kind, EventKind.DRONE_EVENT)


# ===========================================================================
# TEST G — Network context: ip_src, mac_src, port_src → source_port
# ===========================================================================

class TestUdpNetworkContext(UdpIngestBase):
    """Network fields from UDP raw dict must be correctly mapped."""

    def setUp(self):
        super().setUp()
        self.payload = {
            "device_id": "portique_P01", "type": "vibration",
            "value": 0.2, "timestamp": 4.0, "token": "tk_vib789",
            "ip_src": "192.168.1.12", "mac_src": "AA:BB:CC:DD:EE:03", "port_src": 1883,
        }

    def test_ip_src(self):
        e = self._capture_common_event(self.payload)
        self.assertEqual(e.network.ip_src, "192.168.1.12")

    def test_mac_src(self):
        e = self._capture_common_event(self.payload)
        self.assertEqual(e.network.mac_src, "AA:BB:CC:DD:EE:03")

    def test_source_port_from_port_src(self):
        """port_src in UDP payload → network.source_port in CommonEvent."""
        e = self._capture_common_event(self.payload)
        self.assertEqual(e.network.source_port, 1883)

    def test_observed_always_false(self):
        e = self._capture_common_event(self.payload)
        self.assertIs(e.network.observed, False)

    def test_simulated_always_true(self):
        e = self._capture_common_event(self.payload)
        self.assertIs(e.network.simulated, True)

    def test_no_invented_network_metrics(self):
        """All 7 invented metrics must be None for UDP ingress."""
        e = self._capture_common_event(self.payload)
        n = e.network
        invented = {
            "destination_port": n.destination_port,
            "packet_size":      n.packet_size,
            "latency":          n.latency,
            "throughput":       n.throughput,
            "packet_count":     n.packet_count,
            "bytes_total":      n.bytes_total,
            "avg_interval":     n.avg_interval,
        }
        for field_name, val in invented.items():
            with self.subTest(field=field_name):
                self.assertIsNone(val, f"Expected {field_name}=None, got {val!r}")

    def test_ip_absent_gives_none(self):
        payload = {"device_id": "x", "type": "temperature", "value": 1.0, "timestamp": 1.0}
        e = self._capture_common_event(payload)
        self.assertIsNone(e.network.ip_src)

    def test_source_port_absent_gives_none(self):
        payload = {"device_id": "x", "type": "temperature", "value": 1.0, "timestamp": 1.0}
        e = self._capture_common_event(payload)
        self.assertIsNone(e.network.source_port)


# ===========================================================================
# TEST H — mqtt_topic: absent for UDP
# ===========================================================================

class TestUdpMqttTopicAbsent(UdpIngestBase):
    """UDP payloads have no mqtt_topic; identity.mqtt_topic must be None."""

    def test_no_mqtt_topic_in_udp_payload(self):
        payload = {
            "device_id": "hum_01", "type": "humidity",
            "value": 55.0, "timestamp": 6.0, "token": "tk_hum456",
        }
        e = self._capture_common_event(payload)
        self.assertIsNone(e.identity.mqtt_topic)

    def test_mqtt_topic_absent_even_with_source_address(self):
        """UdpTelemetryProtocol adds source_address; this must not create a topic."""
        payload = {
            "device_id": "hum_01", "type": "humidity",
            "value": 55.0, "timestamp": 6.0,
            "transport": "udp", "source_address": "192.168.1.11",
        }
        e = self._capture_common_event(payload)
        self.assertIsNone(e.identity.mqtt_topic)


# ===========================================================================
# TEST I — raw_payload: exact copy, independent from caller's dict
# ===========================================================================

class TestUdpRawPayload(UdpIngestBase):
    """raw_payload must be a shallow copy independent from the original dict."""

    def test_raw_payload_contains_all_original_fields(self):
        payload = {
            "device_id": "grue_G01", "type": "temperature",
            "value": 28.3, "unit": "°C", "timestamp": 1.0,
            "token": "tk_temp123",
            "ip_src": "192.168.1.10", "mac_src": "AA:BB:CC:DD:EE:01", "port_src": 1883,
        }
        e = self._capture_common_event(payload)
        for key, val in payload.items():
            with self.subTest(key=key):
                self.assertEqual(e.raw_payload.get(key), val)

    def test_raw_payload_is_independent_copy(self):
        payload = {"device_id": "x", "type": "temperature", "value": 1.0, "timestamp": 1.0}
        e = self._capture_common_event(payload)
        # Mutate the original payload after the call
        payload["value"] = 999.0
        # raw_payload must not be affected
        self.assertNotEqual(e.raw_payload.get("value"), 999.0)

    def test_raw_payload_contains_gps_fields(self):
        """GPS-specific fields must survive in raw_payload."""
        payload = {
            "device_id": "camion_C12", "type": "gps",
            "latitude": 35.767, "longitude": -5.800, "timestamp": 7.0,
            "token": "tk_gps111",
        }
        e = self._capture_common_event(payload)
        self.assertAlmostEqual(e.raw_payload.get("latitude"), 35.767, places=3)
        self.assertAlmostEqual(e.raw_payload.get("longitude"), -5.800, places=3)

    def test_raw_payload_contains_udp_protocol_fields(self):
        """UdpTelemetryProtocol adds transport and source_address; both must be in raw."""
        payload = {
            "device_id": "temp_01", "type": "temperature", "value": 22.0,
            "timestamp": 1.0, "transport": "udp", "source_address": "10.0.0.1",
        }
        e = self._capture_common_event(payload)
        self.assertEqual(e.raw_payload.get("transport"), "udp")
        self.assertEqual(e.raw_payload.get("source_address"), "10.0.0.1")


# ===========================================================================
# TEST J — Metadata: extra/unknown fields land in metadata
# ===========================================================================

class TestUdpMetadata(UdpIngestBase):
    """Unknown payload fields must land verbatim in CommonEvent.metadata."""

    def test_source_address_in_metadata(self):
        """UdpTelemetryProtocol.source_address is not a consumed key → metadata."""
        payload = {
            "device_id": "temp_01", "type": "temperature", "value": 22.0,
            "timestamp": 1.0, "transport": "udp", "source_address": "10.0.0.1",
        }
        e = self._capture_common_event(payload)
        self.assertEqual(e.metadata.get("source_address"), "10.0.0.1")

    def test_unknown_field_in_metadata(self):
        payload = {
            "device_id": "x", "type": "temperature", "value": 1.0,
            "timestamp": 1.0, "future_field": "xyz",
        }
        e = self._capture_common_event(payload)
        self.assertEqual(e.metadata.get("future_field"), "xyz")

    def test_consumed_keys_not_in_metadata(self):
        payload = {
            "device_id": "x", "type": "temperature", "value": 1.0,
            "unit": "°C", "timestamp": 1.0, "token": "t",
            "ip_src": "1.2.3.4", "mac_src": "AA:BB:CC:DD:EE:FF", "port_src": 9000,
        }
        e = self._capture_common_event(payload)
        consumed = {"device_id", "type", "timestamp", "token", "value", "unit",
                    "status", "people_count", "latitude", "longitude",
                    "ip_src", "mac_src", "port_src", "mqtt_topic", "transport"}
        for key in consumed:
            with self.subTest(key=key):
                self.assertNotIn(key, e.metadata)

    def test_drone_extra_fields_in_metadata(self):
        """x, y, altitude, battery, mission_id must land in metadata for drone."""
        payload = {
            "device_id": "drone_01", "type": "drone",
            "x": 3.0, "y": 2.0, "altitude": 10.0, "battery": 85.0,
            "status": "flying", "mission_id": "m-001",
            "timestamp": 8.0, "token": "tk_drone_secure_001",
        }
        e = self._capture_common_event(payload)
        for field in ("x", "y", "altitude", "battery", "mission_id"):
            with self.subTest(field=field):
                self.assertIn(field, e.metadata)


# ===========================================================================
# TEST K — Timestamp handling
# ===========================================================================

class TestUdpTimestamp(UdpIngestBase):
    """occurred_at must come from payload timestamp when present; generated otherwise."""

    def test_timestamp_preserved(self):
        payload = {"device_id": "x", "type": "t", "value": 1.0,
                   "timestamp": 1_700_000_000.0}
        e = self._capture_common_event(payload)
        self.assertEqual(e.occurred_at, 1_700_000_000.0)

    def test_timestamp_generated_when_absent(self):
        import time
        payload = {"device_id": "x", "type": "t", "value": 1.0}
        before = time.time()
        e = self._capture_common_event(payload)
        after = time.time()
        self.assertGreaterEqual(e.occurred_at, before)
        self.assertLessEqual(e.occurred_at, after + 1.0)

    def test_normalizer_receives_original_timestamp(self):
        """Normalizer must receive the original timestamp, not a mutated one."""
        payload = {"device_id": "x", "type": "t", "value": 1.0,
                   "timestamp": 42.0}
        received = {}

        def spy(raw, tr):
            received["ts"] = raw.get("timestamp")
            from backend.events.normalizer import EventNormalizer as EN
            return EN.normalize(raw, tr)

        with patch.object(main_module, "EventNormalizer") as mock_en:
            mock_en.normalize.side_effect = spy
            _run(ingest_udp_payload(payload))

        self.assertEqual(received["ts"], 42.0)


# ===========================================================================
# TEST L — Existing pipeline completely unchanged
# ===========================================================================

class TestUdpExistingPipelineUnchanged(UdpIngestBase):
    """All existing consumers of ingest_udp_payload() must behave exactly as before."""

    def test_platform_service_ingest_telemetry_called(self):
        payload = {"device_id": "grue_G01", "type": "temperature",
                   "value": 28.3, "timestamp": 1.0, "token": "tk_temp123"}
        _run(ingest_udp_payload(payload))
        self.platform_svc.ingest_telemetry.assert_called_once()

    def test_ingest_telemetry_called_with_udp_transport(self):
        payload = {"device_id": "x", "type": "temperature",
                   "value": 1.0, "timestamp": 1.0}
        _run(ingest_udp_payload(payload))
        _, kwargs = self.platform_svc.ingest_telemetry.call_args
        # transport is passed as a positional arg or keyword
        call_args = self.platform_svc.ingest_telemetry.call_args
        # Either positional [1] or keyword 'transport'
        transport_val = (call_args[0][1] if len(call_args[0]) > 1
                         else call_args[1].get("transport", "http"))
        self.assertEqual(transport_val, "udp")

    def test_session_local_called(self):
        payload = {"device_id": "x", "type": "temperature",
                   "value": 1.0, "timestamp": 1.0}
        _run(ingest_udp_payload(payload))
        main_module.SessionLocal.assert_called_once()

    def test_db_close_always_called(self):
        payload = {"device_id": "x", "type": "temperature",
                   "value": 1.0, "timestamp": 1.0}
        _run(ingest_udp_payload(payload))
        self.db.close.assert_called_once()

    def test_exception_in_platform_service_does_not_propagate(self):
        """Existing behaviour: exceptions are swallowed and logged."""
        self.platform_svc.ingest_telemetry.side_effect = ValueError("bad payload")
        payload = {"device_id": "x", "type": "t", "value": 1.0, "timestamp": 1.0}
        # Must not raise
        _run(ingest_udp_payload(payload))
        self.db.close.assert_called_once()

    def test_common_event_created_before_telemetry_in(self):
        """CommonEvent must be built BEFORE TelemetryIn — verified by checking
        that the normalizer receives latitude/longitude even though TelemetryIn
        would drop them."""
        payload = {
            "device_id": "camion_C12", "type": "gps",
            "latitude": 35.0, "longitude": -5.0, "timestamp": 7.0,
        }
        received_raw = {}

        def spy(raw, tr):
            received_raw["payload"] = dict(raw)
            from backend.events.normalizer import EventNormalizer as EN
            return EN.normalize(raw, tr)

        with patch.object(main_module, "EventNormalizer") as mock_en:
            mock_en.normalize.side_effect = spy
            _run(ingest_udp_payload(payload))

        # The raw dict seen by the normalizer must still have lat/lon
        self.assertAlmostEqual(received_raw["payload"].get("latitude"), 35.0)
        self.assertAlmostEqual(received_raw["payload"].get("longitude"), -5.0)


# ===========================================================================
# TEST M — event_id uniqueness for UDP
# ===========================================================================

class TestUdpEventIdUniqueness(UdpIngestBase):
    """Each UDP call must produce a distinct UUID4 event_id."""

    def test_two_calls_produce_different_event_ids(self):
        payload = {"device_id": "x", "type": "temperature",
                   "value": 1.0, "timestamp": 1.0}
        e1 = self._capture_common_event(payload)
        e2 = self._capture_common_event(payload)
        self.assertNotEqual(e1.event_id, e2.event_id)

    def test_event_id_is_36_char_uuid(self):
        payload = {"device_id": "x", "type": "temperature",
                   "value": 1.0, "timestamp": 1.0}
        e = self._capture_common_event(payload)
        self.assertEqual(len(e.event_id), 36)
        self.assertEqual(len(e.event_id.split("-")), 5)


if __name__ == "__main__":
    unittest.main()
