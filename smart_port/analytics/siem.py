"""SIEM policy facade for identity, topic and message-rate controls."""
from smart_port.edge.device_registry import validate_identity


def evaluate_identity(device_id: str, token: str, topic: str) -> list[tuple[str, str]]:
    return validate_identity(device_id, token, topic)
