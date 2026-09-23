"""Regression tests for legacy attack-simulation MQTT publishing."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import WebSocketDisconnect

from backend import main
from backend.auth import create_access_token


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


class FakeWebSocket:
    def __init__(self, token=None):
        self.query_params = {} if token is None else {"token": token}
        self.accepted = False
        self.closed = None

    async def accept(self):
        self.accepted = True

    async def close(self, code=None, reason=None):
        self.closed = (code, reason)

    async def receive_text(self):
        raise WebSocketDisconnect()


class WebSocketAuthTests(unittest.TestCase):
    def test_valid_token_is_accepted(self):
        websocket = FakeWebSocket(create_access_token({"sub": "admin"}))

        asyncio.run(main.websocket_endpoint(websocket))

        self.assertTrue(websocket.accepted)
        self.assertIsNone(websocket.closed)

    def test_missing_token_is_rejected(self):
        websocket = FakeWebSocket()

        asyncio.run(main.websocket_endpoint(websocket))

        self.assertFalse(websocket.accepted)
        self.assertEqual(websocket.closed[0], 1008)

    def test_invalid_token_is_rejected(self):
        websocket = FakeWebSocket("not-a-valid-jwt")

        asyncio.run(main.websocket_endpoint(websocket))

        self.assertFalse(websocket.accepted)
        self.assertEqual(websocket.closed[0], 1008)


if __name__ == "__main__":
    unittest.main()
