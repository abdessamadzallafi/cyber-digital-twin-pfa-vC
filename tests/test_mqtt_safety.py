"""Safety regressions for the MQTT processing boundary."""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend import mqtt_listener
from backend.decision_engine import make_decision


class MqttSafetyTests(unittest.TestCase):
    def test_drone_telemetry_never_reaches_decision_engine(self):
        db = MagicMock()
        telemetry_handler = AsyncMock()
        payload = {"device_id": "drone_01", "type": "drone", "status": "idle", "timestamp": 1.0}
        with patch.object(mqtt_listener, "SessionLocal", return_value=db), \
             patch.object(mqtt_listener, "write_event"), \
             patch.object(mqtt_listener, "_process_drone_telemetry", telemetry_handler), \
             patch.object(mqtt_listener, "make_decision", side_effect=AssertionError("must not be called")):
            asyncio.run(mqtt_listener.process_message(payload))
        telemetry_handler.assert_awaited_once()
        db.close.assert_called_once()

    def test_ml_failure_returns_a_decision_instead_of_raising(self):
        data = {"device_id": "temp_01", "type": "temperature", "value": "not-a-number", "token": "tk_temp123", "mqtt_topic": "port/container01/temperature"}
        with patch("backend.decision_engine.prediction_service.analyze", side_effect=ValueError("bad model input")):
            decision = make_decision(data, {"packet_count": 1, "ip_src": "192.168.1.10", "bytes_total": 1, "avg_interval": 0, "throughput": 0})
        self.assertFalse(decision["anomaly"])
        self.assertIn("alerts", decision)


if __name__ == "__main__":
    unittest.main()
