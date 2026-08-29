"""Regression tests for legacy attack-simulation MQTT publishing."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend import main


class PublishAttackTests(unittest.TestCase):
    def test_publish_attack_uses_configured_broker(self) -> None:
        payload = {"device_id": "temp_01", "value": 25.0}

        with patch.object(main, "settings", SimpleNamespace(
            mqtt_host="mqtt.internal", mqtt_port=2883,
        )), patch.object(main.mqtt, "Client") as client_class:
            client = client_class.return_value

            main.publish_attack("port/container01/temperature", payload)

        client.connect.assert_called_once_with("mqtt.internal", 2883, 60)
        client.publish.assert_called_once_with(
            "port/container01/temperature", '{"device_id": "temp_01", "value": 25.0}',
        )
        client.disconnect.assert_called_once_with()

    def test_publish_attack_does_not_disconnect_after_connection_error(self) -> None:
        with patch.object(main.mqtt, "Client") as client_class:
            client = client_class.return_value
            client.connect.side_effect = OSError("broker unavailable")

            with self.assertRaises(OSError):
                main.publish_attack("port/test", {})

        client.disconnect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
