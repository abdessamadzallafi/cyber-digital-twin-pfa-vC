"""Trusted edge-device inventory and MQTT routing policy.

This is the single source of truth shared by the device gateway and SIEM.
Aliases retain support for the original demo identities used by attack scripts.
"""
from dataclasses import dataclass
import os
from typing import Dict, Iterable


@dataclass(frozen=True)
class DeviceProfile:
    device_id: str
    device_type: str
    zone: str
    token: str
    topic: str
    ip: str
    mac: str


DEVICE_REGISTRY: Dict[str, DeviceProfile] = {
    "grue_G01": DeviceProfile("grue_G01", "temperature", "quay-crane", "tk_temp123", "port/gantry_crane/temperature", "192.168.1.10", "AA:BB:CC:DD:EE:01"),
    "station_H01": DeviceProfile("station_H01", "humidity", "weather-station", "tk_hum456", "port/weather/humidity", "192.168.1.11", "AA:BB:CC:DD:EE:02"),
    "portique_P01": DeviceProfile("portique_P01", "vibration", "container-yard", "tk_vib789", "port/gantry_crane/vibration", "192.168.1.12", "AA:BB:CC:DD:EE:03"),
    "camera_Q01": DeviceProfile("camera_Q01", "camera", "quay-security", "tk_cam000", "port/quay/camera", "192.168.1.20", "AA:BB:CC:DD:EE:04"),
    "camion_C12": DeviceProfile("camion_C12", "gps", "vehicle-zone", "tk_gps111", "port/vehicle/gps", "192.168.1.30", "AA:BB:CC:DD:EE:05"),
    "portail_N01": DeviceProfile("portail_N01", "barrier", "north-gate", "tk_gate222", "port/gate/status", "192.168.1.40", "AA:BB:CC:DD:EE:06"),
    "entrepot_E01": DeviceProfile("entrepot_E01", "smoke", "warehouse", "tk_smoke333", "port/warehouse/smoke", "192.168.1.50", "AA:BB:CC:DD:EE:07"),
    "parking_P01": DeviceProfile("parking_P01", "presence", "parking", "tk_pres444", "port/parking/presence", "192.168.1.60", "AA:BB:CC:DD:EE:08"),
}

# Legacy IDs keep existing attack generators and clients working unchanged.
LEGACY_DEVICE_ALIASES = {
    "temp_01": ("tk_temp123", "port/container01/temperature"),
    "hum_01": ("tk_hum456", "port/container01/humidity"),
    "vib_01": ("tk_vib789", "port/container01/vibration"),
    "cam_01": ("tk_cam000", "port/camera01/status"),
    "gps_01": ("tk_gps111", "port/truck05/gps"),
    "gate_01": ("tk_gate222", "port/gate01/status"),
    "smoke_01": ("tk_smoke333", "port/security/smoke"),
    "pres_01": ("tk_pres444", "port/parking/presence"),
}

# Map legacy demo identities onto the canonical registry inventory used by the UI.
ALIAS_TO_CANONICAL = {
    "temp_01": "grue_G01",
    "hum_01": "station_H01",
    "vib_01": "portique_P01",
    "cam_01": "camera_Q01",
    "gps_01": "camion_C12",
    "gate_01": "portail_N01",
    "smoke_01": "entrepot_E01",
    "pres_01": "parking_P01",
}


def known_devices() -> Iterable[str]:
    return (*DEVICE_REGISTRY.keys(), *LEGACY_DEVICE_ALIASES.keys())


def canonical_device_id(device_id: str | None) -> str:
    """Resolve legacy attack/sim IDs to the registry device shown on the dashboard."""
    if not device_id:
        return "unknown"
    return ALIAS_TO_CANONICAL.get(device_id, device_id)


def device_identity_keys(device_id: str) -> tuple[str, ...]:
    """All ids that represent one logical equipment (canonical + aliases)."""
    canonical = canonical_device_id(device_id)
    aliases = [alias for alias, target in ALIAS_TO_CANONICAL.items() if target == canonical]
    ordered = [canonical, *aliases]
    if device_id not in ordered:
        ordered.append(device_id)
    return tuple(dict.fromkeys(ordered))


def validate_identity(device_id: str, token: str, topic: str) -> list[tuple[str, str]]:
    """Return SIEM-ready identity violations without raising on untrusted input."""
    profile = DEVICE_REGISTRY.get(device_id)
    expected = (profile.token, profile.topic) if profile else LEGACY_DEVICE_ALIASES.get(device_id)
    if not expected:
        return [("unknown_device", f"Unregistered edge device {device_id}")]
    expected_token, expected_topic = expected
    allowed_topics = {expected_topic}
    # Canonical registry devices also accept their legacy demo topic.
    for alias, target in ALIAS_TO_CANONICAL.items():
        if target == device_id and alias in LEGACY_DEVICE_ALIASES:
            allowed_topics.add(LEGACY_DEVICE_ALIASES[alias][1])
    alerts = []
    if token != expected_token:
        alerts.append(("bad_token", f"Invalid device credential for {device_id}"))
    if topic not in allowed_topics:
        alerts.append(("wrong_topic", f"Unauthorized topic {topic} for {device_id}"))
    return alerts
