"""Compatibility adapter for the established MQTT worker."""
from backend.mqtt_listener import process_message, start_mqtt

__all__ = ["process_message", "start_mqtt"]
