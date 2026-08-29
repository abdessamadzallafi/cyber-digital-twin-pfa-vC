"""Regression tests for the CommonEvent integration in mqtt_listener.process_message.

Scope
-----
Verify that process_message now produces a CommonEvent alongside the existing
flat-dict pipeline, without altering any existing behaviour:

- The flat `data` dict produced by DeviceGateway.normalize() is still used by
  all downstream consumers (SensorReading, make_decision, etc.).
- The CommonEvent is produced from raw_data (the original payload), not from
  the post-normalized dict.
- All existing consumer mocks (SessionLocal, write_event, make_decision, …)
  still behave as before.
- Drone telemetry continues to be routed to _process_drone_telemetry and never
  reaches make_decision.

Design constraints
------------------
- No DB, no broker, no filesystem, no FastAPI startup.
- All external collaborators (SessionLocal, write_event, make_decision,
  process_network_data, ActionDispatcher, SmartPortSiem, drone_manager) are
  mocked at the mqtt_listener module boundary.
- Only mqtt_listener and backend.events.* are exercised as real code.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call

from backend import mqtt_listener
from backend.events.contracts import EventKind, Transport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine synchronously in a fresh event loop."""
    return asyncio.run(coro)


def _make_db_mock():
    """Return a MagicMock that satisfies SessionLocal() and db.close()."""
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    return db


def _make_decision_mock(anomaly=False, threat_level="green"):
    """Return a make_decision return value with no alerts."""
    return {
        "device_id": "temp_01",
        "anomaly": anomaly,
        "anomaly_score": 0.0,
        "threat_level": threat_level,
        "dispatch_recommended": False,
        "create_mission": False,
        "alerts": [],
        "ai_predictions": [],
    }


def _net_info():
    return {
        "ip_src": "192.168.1.10",
        "mac_src": "AA:BB:CC:DD:EE:01",
        "packet_count": 1,
        "bytes_total": 50,
        "avg_interval": 0.0,
        "throughput": 0.0,
        "duration": 0.0,
    }


# ---------------------------------------------------------------------------
# Base class: patch all external collaborators
# ---------------------------------------------------------------------------

class MqttListenerEventBase(unittest.TestCase):
    """Base: mock every collaborator that touches DB / network / ML."""

    def setUp(self):
        self.db = _make_db_mock()
        self.patches = [
            patch.object(mqtt_listener, "SessionLocal", return_value=self.db),
            patch.object(mqtt_listener, "write_event"),
            patch.object(mqtt_listener, "process_network_data", return_value=_net_info()),
            patch.object(mqtt_listener, "make_decision", return_value=_make_decision_mock()),
            patch.object(mqtt_listener, "SmartPortSiem"),
            patch.object(mqtt_listener, "ActionDispatcher"),
            patch.object(mqtt_listener, "_publish_dashboard", new_callable=AsyncMock),
            patch.object(mqtt_listener, "drone_manager"),
        ]
        self.mocks = [p.start() for p in self.patches]

    def tearDown(self):
        for p in self.patches:
            p.stop()


# ===========================================================================
# TEST A — IoT temperature: CommonEvent is produced correctly
# ===========================================================================

class TestIoTCommonEventProduced(MqttListenerEventBase):
    """process_message produces a CommonEvent for a normal IoT payload."""

    def setUp(self):
        super().setUp()
        self.raw = {
            "device_id": "grue_G01",
            "type": "temperature",
            "value": 28.3,
            "unit": "°C",
            "timestamp": 1_700_000_000.0,
            "token": "tk_temp123",
            "mqtt_topic": "port/gantry_crane/temperature",
            "ip_src": "192.168.1.10",
            "mac_src": "AA:BB:CC:DD:EE:01",
            "port_src": 1883,
        }

    def test_common_event_kind_iot(self):
        captured = {}

        def capturing_normalize(payload, transport):
            from backend.events.normalizer import EventNormalizer as EN
            evt = EN.normalize(payload, transport)
            captured["event"] = evt
            return evt

        with patch.object(mqtt_listener, "EventNormalizer") as mock_en:
            mock_en.normalize.side_effect = capturing_normalize
            _run(mqtt_listener.process_message(self.raw))

        self.assertIn("event", captured)
        self.assertEqual(captured["event"].event_kind, EventKind.IOT_TELEMETRY)

    def test_common_event_transport_mqtt(self):
        captured = {}

        def capturing_normalize(payload, transport):
            from backend.events.normalizer import EventNormalizer as EN
            evt = EN.normalize(payload, transport)
            captured["event"] = evt
            return evt

        with patch.object(mqtt_listener, "EventNormalizer") as mock_en:
            mock_en.normalize.side_effect = capturing_normalize
            _run(mqtt_listener.process_message(self.raw))

        self.assertEqual(captured["event"].transport, Transport.MQTT)

    def test_common_event_device_id(self):
        captured = {}

        def capturing_normalize(payload, transport):
            from backend.events.normalizer import EventNormalizer as EN
            evt = EN.normalize(payload, transport)
            captured["event"] = evt
            return evt

        with patch.object(mqtt_listener, "EventNormalizer") as mock_en:
            mock_en.normalize.side_effect = capturing_normalize
            _run(mqtt_listener.process_message(self.raw))

        self.assertEqual(captured["event"].device.device_id, "grue_G01")

    def test_common_event_raw_payload_is_original(self):
        """raw_payload must be the original dict, not the DeviceGateway-normalized one."""
        captured = {}

        def capturing_normalize(payload, transport):
            from backend.events.normalizer import EventNormalizer as EN
            evt = EN.normalize(payload, transport)
            captured["event"] = evt
            return evt

        with patch.object(mqtt_listener, "EventNormalizer") as mock_en:
            mock_en.normalize.side_effect = capturing_normalize
            _run(mqtt_listener.process_message(self.raw))

        # raw_payload must contain all original fields
        rp = captured["event"].raw_payload
        self.assertEqual(rp.get("device_id"), "grue_G01")
        self.assertEqual(rp.get("value"), 28.3)
        self.assertEqual(rp.get("mqtt_topic"), "port/gantry_crane/temperature")

    def test_existing_pipeline_still_calls_make_decision(self):
        """The flat data dict pipeline must remain untouched."""
        _run(mqtt_listener.process_message(self.raw))
        mqtt_listener.make_decision.assert_called_once()

    def test_existing_pipeline_still_calls_write_event(self):
        _run(mqtt_listener.process_message(self.raw))
        mqtt_listener.write_event.assert_called_once()

    def test_db_close_always_called(self):
        _run(mqtt_listener.process_message(self.raw))
        self.db.close.assert_called_once()


# ===========================================================================
# TEST B — EventNormalizer.normalize is called with raw_data (not data)
# ===========================================================================

class TestNormalizerCalledWithRawData(MqttListenerEventBase):
    """Verify that EventNormalizer receives raw_data, not the DeviceGateway output."""

    def test_normalizer_receives_original_payload(self):
        raw = {
            "device_id": "entrepot_E01",
            "type": "smoke",
            "value": 0.1,
            "timestamp": 42.0,
            "token": "tk_smoke333",
            "mqtt_topic": "port/warehouse/smoke",
        }
        call_args = {}

        def spy_normalize(payload, transport):
            call_args["payload"] = dict(payload)
            call_args["transport"] = transport
            from backend.events.normalizer import EventNormalizer as EN
            return EN.normalize(payload, transport)

        with patch.object(mqtt_listener, "EventNormalizer") as mock_en:
            mock_en.normalize.side_effect = spy_normalize
            _run(mqtt_listener.process_message(raw))

        # Must have been called with the original dict (containing original keys)
        self.assertEqual(call_args["payload"].get("device_id"), "entrepot_E01")
        self.assertEqual(call_args["payload"].get("value"), 0.1)
        self.assertEqual(call_args["transport"], Transport.MQTT)

    def test_normalizer_called_exactly_once(self):
        raw = {"device_id": "x", "type": "temperature", "value": 1.0, "timestamp": 1.0,
               "mqtt_topic": "port/x/temperature"}

        with patch.object(mqtt_listener, "EventNormalizer") as mock_en:
            mock_en.normalize.return_value = MagicMock()
            _run(mqtt_listener.process_message(raw))

        mock_en.normalize.assert_called_once()


# ===========================================================================
# TEST C — Drone telemetry: CommonEvent is DRONE_TELEMETRY, no make_decision
# ===========================================================================

class TestDroneTelemetryCommonEvent(MqttListenerEventBase):
    """Drone telemetry path: CommonEvent is produced, make_decision is NOT called."""

    def setUp(self):
        super().setUp()
        self.raw_drone = {
            "device_id": "drone_01",
            "type": "drone",
            "x": 1.0, "y": 2.0, "altitude": 5.0, "battery": 90.0,
            "status": "flying",
            "timestamp": 1_700_000_007.0,
            "token": "tk_drone_secure_001",
            "mqtt_topic": "drone/telemetry",
        }
        # _process_drone_telemetry must be async
        self.patches.append(
            patch.object(mqtt_listener, "_process_drone_telemetry", new_callable=AsyncMock)
        )
        self.mocks.append(self.patches[-1].start())

    def test_drone_common_event_kind(self):
        captured = {}

        def capturing_normalize(payload, transport):
            from backend.events.normalizer import EventNormalizer as EN
            evt = EN.normalize(payload, transport)
            captured["event"] = evt
            return evt

        with patch.object(mqtt_listener, "EventNormalizer") as mock_en:
            mock_en.normalize.side_effect = capturing_normalize
            _run(mqtt_listener.process_message(self.raw_drone))

        self.assertEqual(captured["event"].event_kind, EventKind.DRONE_TELEMETRY)

    def test_drone_make_decision_never_called(self):
        """Safety regression: drone telemetry must not reach make_decision."""
        with patch.object(mqtt_listener, "make_decision",
                          side_effect=AssertionError("must not be called")):
            # Should not raise
            _run(mqtt_listener.process_message(self.raw_drone))

    def test_drone_process_drone_telemetry_called(self):
        _run(mqtt_listener.process_message(self.raw_drone))
        mqtt_listener._process_drone_telemetry.assert_awaited_once()


# ===========================================================================
# TEST D — Drone event: CommonEvent is DRONE_EVENT
# ===========================================================================

class TestDroneEventCommonEvent(MqttListenerEventBase):
    """drone_event type path: CommonEvent is DRONE_EVENT."""

    def test_drone_event_common_event_kind(self):
        raw = {
            "device_id": "drone_01",
            "type": "drone_event",
            "event_type": "mission_started",
            "timestamp": 1_700_000_010.0,
            "token": "tk_drone_secure_001",
            "mqtt_topic": "drone/event",
        }
        captured = {}

        def capturing_normalize(payload, transport):
            from backend.events.normalizer import EventNormalizer as EN
            evt = EN.normalize(payload, transport)
            captured["event"] = evt
            return evt

        with patch.object(mqtt_listener, "EventNormalizer") as mock_en:
            mock_en.normalize.side_effect = capturing_normalize
            _run(mqtt_listener.process_message(raw))

        self.assertEqual(captured["event"].event_kind, EventKind.DRONE_EVENT)

    def test_drone_event_make_decision_not_called(self):
        raw = {
            "device_id": "drone_01", "type": "drone_event",
            "event_type": "mission_completed", "timestamp": 1.0,
            "mqtt_topic": "drone/event",
        }
        with patch.object(mqtt_listener, "make_decision",
                          side_effect=AssertionError("must not be called")):
            _run(mqtt_listener.process_message(raw))


# ===========================================================================
# TEST E — CommonEvent does NOT replace the flat dict (backward-compat guard)
# ===========================================================================

class TestFlatDictUnchanged(MqttListenerEventBase):
    """The flat `data` dict still drives all existing consumers."""

    def test_process_network_data_receives_flat_fields(self):
        """process_network_data must receive ip_src, mac_src from the flat dict."""
        raw = {
            "device_id": "portique_P01",
            "type": "vibration",
            "value": 0.3, "unit": "g",
            "timestamp": 5.0,
            "token": "tk_vib789",
            "mqtt_topic": "port/gantry_crane/vibration",
            "ip_src": "192.168.1.12",
            "mac_src": "AA:BB:CC:DD:EE:03",
            "port_src": 1883,
        }
        _run(mqtt_listener.process_message(raw))
        args = mqtt_listener.process_network_data.call_args
        # First positional arg is device_id, second is ip_src
        self.assertEqual(args[0][0], "portique_P01")
        self.assertEqual(args[0][1], "192.168.1.12")

    def test_write_event_receives_normalized_dict(self):
        """write_event must be called with the DeviceGateway-normalized dict."""
        raw = {
            "device_id": "camera_Q01", "type": "camera",
            "people_count": 3, "timestamp": 6.0,
            "token": "tk_cam000", "mqtt_topic": "port/quay/camera",
        }
        _run(mqtt_listener.process_message(raw))
        called_stream = mqtt_listener.write_event.call_args[0][0]
        called_payload = mqtt_listener.write_event.call_args[0][1]
        self.assertEqual(called_stream, "telemetry")
        self.assertEqual(called_payload.get("device_id"), "camera_Q01")


# ===========================================================================
# TEST F — Presence sensor: status bool preserved in CommonEvent
# ===========================================================================

class TestPresenceBoolStatusInCommonEvent(MqttListenerEventBase):
    """Status bool in presence sensor payload must be preserved in CommonEvent."""

    def test_status_bool_preserved(self):
        raw = {
            "device_id": "parking_P01", "type": "presence",
            "status": True, "timestamp": 7.0,
            "token": "tk_pres444", "mqtt_topic": "port/parking/presence",
            "ip_src": "192.168.1.60", "mac_src": "AA:BB:CC:DD:EE:08", "port_src": 1883,
        }
        captured = {}

        def capturing_normalize(payload, transport):
            from backend.events.normalizer import EventNormalizer as EN
            evt = EN.normalize(payload, transport)
            captured["event"] = evt
            return evt

        with patch.object(mqtt_listener, "EventNormalizer") as mock_en:
            mock_en.normalize.side_effect = capturing_normalize
            _run(mqtt_listener.process_message(raw))

        self.assertIs(captured["event"].data.status, True)
        self.assertIs(type(captured["event"].data.status), bool)


if __name__ == "__main__":
    unittest.main()
