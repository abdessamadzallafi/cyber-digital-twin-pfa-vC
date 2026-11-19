"""Safety regressions for the MQTT processing boundary."""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend import mqtt_listener
from backend.decision_engine import make_decision


class MqttSafetyTests(unittest.TestCase):
    def test_ml_failure_returns_a_decision_instead_of_raising(self):
        data = {"device_id": "temp_01", "type": "temperature", "value": "not-a-number", "token": "tk_temp123", "mqtt_topic": "port/container01/temperature"}
        with patch("backend.decision_engine.prediction_service.analyze", side_effect=ValueError("bad model input")):
            decision = make_decision(data, {"packet_count": 1, "ip_src": "192.168.1.10", "bytes_total": 1, "avg_interval": 0, "throughput": 0})
        self.assertFalse(decision["anomaly"])
        self.assertIn("alerts", decision)


if __name__ == "__main__":
    unittest.main()
