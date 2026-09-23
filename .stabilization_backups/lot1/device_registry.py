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


DRONE_TOKEN = os.getenv("SMART_PORT_DRONE_TOKEN", "")

DEVICE_REGISTRY: Dict[str, DeviceProfile] = {
    "grue_G01": DeviceProfile("grue_G01", "temperature", "quay-crane", "tk_temp123", "port/gantry_crane/temperature", "192.168.1.10", "AA:BB:CC:DD:EE:01"),
    "station_H01": DeviceProfile("station_H01", "humidity", "weather-station", "tk_hum456", "port/weather/humidity", "192.168.1.11", "AA:BB:CC:DD:EE:02"),
    "portique_P01": DeviceProfile("portique_P01", "vibration", "container-yard", "tk_vib789", "port/gantry_crane/vibration", "192.168.1.12", "AA:BB:CC:DD:EE:03"),
    "camera_Q01": DeviceProfile("camera_Q01", "camera", "quay-security", "tk_cam000", "port/quay/camera", "192.168.1.20", "AA:BB:CC:DD:EE:04"),
    "camion_C12": DeviceProfile("camion_C12", "gps", "vehicle-zone", "tk_gps111", "port/vehicle/gps", "192.168.1.30", "AA:BB:CC:DD:EE:05"),
    "portail_N01": DeviceProfile("portail_N01", "barrier", "north-gate", "tk_gate222", "port/gate/status", "192.168.1.40", "AA:BB:CC:DD:EE:06"),
    "entrepot_E01": DeviceProfile("entrepot_E01", "smoke", "warehouse", "tk_smoke333", "port/warehouse/smoke", "192.168.1.50", "AA:BB:CC:DD:EE:07"),
    "parking_P01": DeviceProfile("parking_P01", "presence", "parking", "tk_pres444", "port/parking/presence", "192.168.1.60", "AA:BB:CC:DD:EE:08"),
    "drone_01": DeviceProfile("drone_01", "drone", "autonomous-inspection", DRONE_TOKEN, "drone/telemetry", "192.168.1.101", "AA:BB:CC:DD:EE:11"),
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


def known_devices() -> Iterable[str]:
    return (*DEVICE_REGISTRY.keys(), *LEGACY_DEVICE_ALIASES.keys())


def validate_identity(device_id: str, token: str, topic: str) -> list[tuple[str, str]]:
    """Return SIEM-ready identity violations without raising on untrusted input."""
    profile = DEVICE_REGISTRY.get(device_id)
    expected = (profile.token, profile.topic) if profile else LEGACY_DEVICE_ALIASES.get(device_id)
    if not expected:
        return [("unknown_device", f"Unregistered edge device {device_id}")]
    expected_token, expected_topic = expected
    allowed_topics = {expected_topic}
    if device_id == "drone_01":
        allowed_topics.update({"drone/telemetry", "drone/gps", "drone/camera", "drone/mission"})
    alerts = []
    if token != expected_token:
        alerts.append(("bad_token", f"Invalid device credential for {device_id}"))
    if topic not in allowed_topics:
        alerts.append(("wrong_topic", f"Unauthorized topic {topic} for {device_id}"))
    return alerts
