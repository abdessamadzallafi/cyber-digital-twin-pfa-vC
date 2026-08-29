"""Stable API contracts, separated from SQLAlchemy entities."""
from typing import Any, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class TelemetryIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=64)
    value: Optional[float] = None
    # status accepts bool (presence/barrier) or str — never cast between types.
    # Fix B1/P3: Pydantic v2 previously rejected status=True for Optional[str].
    status: Optional[Union[bool, str]] = None
    people_count: Optional[int] = Field(default=None, ge=0)
    timestamp: Optional[float] = None
    token: str = ""
    mqtt_topic: str = ""
    ip_src: Optional[str] = None
    mac_src: Optional[str] = None
    # Fix P2/I3: GPS payloads carry latitude/longitude over HTTP and UDP.
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # Fix P4/I2: edge devices report source port; now preserved for all transports.
    port_src: Optional[int] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class DeviceOut(BaseModel):
    device_id: str
    type: str
    zone: str
    topic: str


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    device_id: str
    alert_type: str
    message: str
    timestamp: float
    severity: Optional[str] = None
