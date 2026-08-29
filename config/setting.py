"""Legacy configuration facade; canonical settings live in :mod:`smart_port.config`."""
from smart_port.config import settings

MQTT_BROKER = settings.mqtt_host
MQTT_PORT = settings.mqtt_port
DATABASE_URL = settings.database_url
BACKEND_HOST = settings.api_host
BACKEND_PORT = settings.api_port
