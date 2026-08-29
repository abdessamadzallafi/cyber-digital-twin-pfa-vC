"""SIEM value objects and severity policy."""
from enum import Enum


class SeverityLevel(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_POINTS = {
    SeverityLevel.INFO.value: 1,
    SeverityLevel.LOW.value: 5,
    SeverityLevel.MEDIUM.value: 15,
    SeverityLevel.HIGH.value: 30,
    SeverityLevel.CRITICAL.value: 50,
}


SOURCES = {"mqtt", "http", "udp", "drone", "ros2", "auth", "sensor", "network"}
