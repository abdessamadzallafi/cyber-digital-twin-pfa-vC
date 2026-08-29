"""Internal CommonEvent contract for unified MQTT/HTTP/UDP normalisation.

This module is a PURE DATA CONTRACT.  It does NOT replace any existing public
MQTT payload or Pydantic schema.  It is NOT wired into any pipeline yet.
Pipelines are adapted incrementally in later phases.

Design decisions
----------------
- stdlib only: dataclasses, enum, typing, uuid — zero new dependencies.
- dataclass (not Pydantic): lightweight, consistent with DeviceProfile in
  smart_port/edge/device_registry.py.
- status field typed as Optional[Any]: preserves the original payload type
  exactly (bool for presence/barrier, str for other status strings).
  The normalizer must never cast this value.
- NetworkContext.observed defaults to False, NetworkContext.simulated defaults
  to True: IP/MAC from simulators are never presented as real network capture.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EventKind(str, Enum):
    """Authorised internal event categories.

    Do NOT add new values without explicit validation.
    """
    IOT_TELEMETRY    = "iot_telemetry"
    DRONE_TELEMETRY  = "drone_telemetry"
    DRONE_EVENT      = "drone_event"
    SECURITY_EVENT   = "security_event"
    NETWORK_METADATA = "network_metadata"


class Transport(str, Enum):
    """Authorised ingress transports."""
    MQTT = "mqtt"
    HTTP = "http"
    UDP  = "udp"


# ---------------------------------------------------------------------------
# Sub-contracts
# ---------------------------------------------------------------------------

@dataclass
class DeviceContext:
    """Edge device identity extracted from the payload or the device registry."""
    device_id:   str
    device_type: Optional[str] = None
    zone:        Optional[str] = None


@dataclass
class DataPayload:
    """Normalised measurement fields.

    status is Optional[Any] to preserve the original payload type exactly:
      - presence sensor  → bool   (True / False)
      - barrier sensor   → str    ("open" / "closed")
      - drone            → str    ("idle" / "flying" / …)
    The value is NEVER cast; callers must inspect the type themselves.
    """
    value:        Optional[float] = None
    unit:         Optional[str]   = None
    status:       Optional[Any]   = None   # bool | str | None — never cast
    people_count: Optional[int]   = None
    latitude:     Optional[float] = None
    longitude:    Optional[float] = None


@dataclass
class IdentityContext:
    """Credential and routing metadata preserved from the original message."""
    token:      Optional[str] = None
    mqtt_topic: Optional[str] = None


@dataclass
class NetworkContext:
    """Network metadata attached to the event.

    IMPORTANT — observed / simulated semantics
    ------------------------------------------
    observed  = False  →  values come from simulator metadata, NOT from real
                           network capture.  Never set to True unless a genuine
                           packet-capture pipeline is in place.
    simulated = True   →  IP/MAC originate from simulation/network_config.py.
                           They must never be presented as real network data.

    Metrics such as latency, throughput, packet_count, bytes_total, and
    avg_interval are populated ONLY by network_monitor.process_network_data(),
    never by the normalizer itself.
    """
    ip_src:           Optional[str]   = None
    ip_dst:           Optional[str]   = None
    mac_src:          Optional[str]   = None
    source_port:      Optional[int]   = None
    destination_port: Optional[int]   = None
    protocol:         Optional[str]   = None
    packet_size:      Optional[int]   = None
    latency:          Optional[float] = None
    throughput:       Optional[float] = None
    packet_count:     Optional[int]   = None
    bytes_total:      Optional[int]   = None
    avg_interval:     Optional[float] = None
    # Defaults enforce the "simulated metadata, not real capture" invariant.
    observed:  bool = False
    simulated: bool = True


# ---------------------------------------------------------------------------
# Root contract
# ---------------------------------------------------------------------------

@dataclass
class CommonEvent:
    """Unified internal event envelope for MQTT, HTTP and UDP messages.

    Mandatory fields (no default)
    ------------------------------
    event_kind   — EventKind enum value, determined by the normalizer.
    transport    — Transport enum value (mqtt | http | udp).
    occurred_at  — Unix timestamp (float).  Preserved from the payload when
                   present; set to time.time() by the normalizer when absent.
    device       — DeviceContext populated from device_id / type fields.

    Optional sub-contracts (default to empty instances)
    ----------------------------------------------------
    data         — Measurement fields (value, unit, status, …).
    identity     — Token and MQTT topic.
    network      — IP/MAC and network metrics (observed=False, simulated=True).
    raw_payload  — Exact copy of the original dict BEFORE normalisation.
                   Must never be mutated after assignment.
    metadata     — Any extra fields from the payload that do not map to a
                   known sub-contract field.  Preserves unknown keys.
    event_id     — UUID4 string, auto-generated.  Unique per envelope.
    """
    event_kind:  EventKind
    transport:   Transport
    occurred_at: float
    device:      DeviceContext
    source:      Optional[str]       = None
    event_type:  Optional[str]       = None
    severity:    Optional[str]       = None
    attack_type: Optional[str]       = None
    anomaly_score: Optional[float]   = None
    data:        DataPayload      = field(default_factory=DataPayload)
    identity:    IdentityContext  = field(default_factory=IdentityContext)
    network:     NetworkContext   = field(default_factory=NetworkContext)
    raw_payload: dict[str, Any]   = field(default_factory=dict)
    metadata:    dict[str, Any]   = field(default_factory=dict)
    event_id:    str              = field(default_factory=lambda: str(uuid.uuid4()))
