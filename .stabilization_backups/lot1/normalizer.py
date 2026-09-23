"""EventNormalizer — pure conversion from raw ingress dict to CommonEvent.

PURPOSE
-------
Translate an arbitrary ingress payload (MQTT, HTTP or UDP) into a CommonEvent
internal envelope, applying the classification rules already established in
backend/mqtt_listener.py.

DESIGN CONSTRAINTS (all enforced by this module)
-------------------------------------------------
1. PURE FUNCTION / NO SIDE EFFECTS
   - No database access.
   - No file I/O.
   - No network calls.
   - No MQTT publish.
   - No ML inference.
   - No SIEM interaction.
   - No decision_engine calls.

2. PAYLOAD IMMUTABILITY
   raw_payload is a shallow copy of the original dict taken BEFORE any
   extraction.  The caller's dict is never modified.

3. STATUS TYPE PRESERVATION
   DataPayload.status is assigned verbatim from the payload.  The type is
   never cast (bool stays bool, str stays str).

4. NETWORK METRICS NOT INVENTED
   Explicit ingress routing values are preserved (structured where supported,
   otherwise in metadata for compatibility). Computed metrics such as latency,
   throughput, packet_count, bytes_total, avg_interval and packet_size are
   never invented; they are the sole responsibility of network_monitor.

5. OBSERVED / SIMULATED INVARIANT
   NetworkContext.observed is always False.
   NetworkContext.simulated is always True.
   IP/MAC from simulators are metadata, not real network captures.

6. UNKNOWN FIELDS PRESERVED
   Any payload key not consumed by DeviceContext, DataPayload, IdentityContext
   or NetworkContext is placed verbatim into CommonEvent.metadata.

CLASSIFICATION RULES (mirroring backend/mqtt_listener.process_message)
-----------------------------------------------------------------------
DRONE_TELEMETRY  if  type in {drone, drone_gps, camera_stream}
                 OR  topic in {drone/telemetry, drone/gps, drone/camera}

DRONE_EVENT      if  type == drone_event
                 OR  topic == drone/event

IOT_TELEMETRY    otherwise  (default)

SECURITY_EVENT and NETWORK_METADATA are defined in EventKind but are NOT
produced by this normalizer at this stage.
"""
from __future__ import annotations

import time
from typing import Any, Mapping, Union

from backend.events.contracts import (
    CommonEvent,
    DataPayload,
    DeviceContext,
    EventKind,
    IdentityContext,
    NetworkContext,
    Transport,
)

# ---------------------------------------------------------------------------
# Internal constants — mirror of mqtt_listener classification rules
# ---------------------------------------------------------------------------

# type values that identify drone telemetry frames
_DRONE_TELEMETRY_TYPES: frozenset[str] = frozenset({"drone", "drone_gps", "camera_stream"})

# MQTT topics that identify drone telemetry frames
_DRONE_TELEMETRY_TOPICS: frozenset[str] = frozenset({
    "drone/telemetry",
    "drone/gps",
    "drone/camera",
})

# type value that identifies a drone operational event
_DRONE_EVENT_TYPE: str = "drone_event"

# MQTT topic that identifies a drone operational event
_DRONE_EVENT_TOPIC: str = "drone/event"

# Fields consumed from the raw payload into structured sub-contracts.
# Everything else ends up in metadata.
_CONSUMED_KEYS: frozenset[str] = frozenset({
    # top-level routing / identity
    "device_id",
    "type",
    "timestamp",
    "transport",
    "mqtt_topic",
    "token",
    # DataPayload
    "value",
    "unit",
    "status",
    "people_count",
    "latitude",
    "longitude",
    # NetworkContext (metadata from simulators only, never a real capture)
    "ip_src",
    "mac_src",
    "port_src",
    "source_port",
})


# ---------------------------------------------------------------------------
# Transport coercion helper
# ---------------------------------------------------------------------------

def _coerce_transport(transport: Union[Transport, str]) -> Transport:
    """Accept a Transport enum or its string value; raise on unknown."""
    if isinstance(transport, Transport):
        return transport
    try:
        return Transport(transport.lower())
    except ValueError:
        raise ValueError(
            f"Unknown transport {transport!r}. "
            f"Accepted values: {[t.value for t in Transport]}"
        )


# ---------------------------------------------------------------------------
# Classification helper
# ---------------------------------------------------------------------------

def _classify(dev_type: str, topic: str) -> EventKind:
    """Determine EventKind from device type and MQTT topic.

    Rules mirror backend/mqtt_listener.process_message exactly:

        DRONE_TELEMETRY  ← type in {drone, drone_gps, camera_stream}
                            OR topic in {drone/telemetry, drone/gps, drone/camera}
        DRONE_EVENT      ← type == drone_event
                            OR topic == drone/event
        IOT_TELEMETRY    ← everything else  (default)
    """
    if dev_type in _DRONE_TELEMETRY_TYPES or topic in _DRONE_TELEMETRY_TOPICS:
        return EventKind.DRONE_TELEMETRY
    if dev_type == _DRONE_EVENT_TYPE or topic == _DRONE_EVENT_TOPIC:
        return EventKind.DRONE_EVENT
    return EventKind.IOT_TELEMETRY


# ---------------------------------------------------------------------------
# Public normalizer
# ---------------------------------------------------------------------------

class EventNormalizer:
    """Convert a raw ingress dict into a CommonEvent envelope.

    Usage
    -----
        from backend.events.normalizer import EventNormalizer
        from backend.events.contracts import Transport

        event = EventNormalizer.normalize(raw_payload, Transport.MQTT)

    The class has no instance state; all methods are static.  It can also
    be used as a bare function via the module-level alias ``normalize``.
    """

    @staticmethod
    def normalize(
        payload: Mapping[str, Any],
        transport: Union[Transport, str],
    ) -> CommonEvent:
        """Normalise *payload* into a CommonEvent.

        Parameters
        ----------
        payload:
            Raw ingress dict from MQTT on_message, HTTP endpoint or UDP
            datagram.  The caller's dict is never modified.
        transport:
            Ingress transport.  Accepts ``Transport`` enum or plain string
            ("mqtt", "http", "udp").

        Returns
        -------
        CommonEvent
            Fully populated envelope.  Fields for which no data exists in the
            payload are left at their dataclass defaults (typically None /
            False / True / {}).
        """
        # --- 1. Copy raw payload FIRST — immutability guarantee ---------------
        raw: dict[str, Any] = dict(payload)

        # --- 2. Resolve transport enum ----------------------------------------
        transport_enum = _coerce_transport(transport)

        # --- 3. Extract scalar routing fields ---------------------------------
        dev_type:  str = raw.get("type", "") or ""
        topic:     str = raw.get("mqtt_topic", "") or ""
        device_id: str = raw.get("device_id") or "unknown"

        # --- 4. Classify event ------------------------------------------------
        event_kind = _classify(dev_type, topic)

        # --- 5. Timestamp — preserve if present, fall back to now() ----------
        occurred_at: float
        ts = raw.get("timestamp")
        if ts is not None:
            try:
                occurred_at = float(ts)
            except (TypeError, ValueError):
                occurred_at = time.time()
        else:
            occurred_at = time.time()

        # --- 6. DeviceContext -------------------------------------------------
        device = DeviceContext(
            device_id=device_id,
            device_type=dev_type if dev_type else None,
            # zone is not available in any simulator payload; populated later
            # by a registry lookup if needed (not the normalizer's job).
            zone=raw.get("zone"),
        )

        # --- 7. DataPayload — extract known measurement fields ----------------
        #   status: assigned verbatim — type is NEVER cast (bool stays bool).
        data = DataPayload(
            value=raw.get("value"),
            unit=raw.get("unit"),
            status=raw.get("status"),          # bool | str | None — no cast
            people_count=raw.get("people_count"),
            latitude=raw.get("latitude"),
            longitude=raw.get("longitude"),
        )

        # --- 8. IdentityContext -----------------------------------------------
        identity = IdentityContext(
            token=raw.get("token"),
            mqtt_topic=topic if topic else None,
        )

        # --- 9. NetworkContext — metadata only, no metrics invented ----------
        #   port_src → source_port (rename to match contract field name).
        #   All computed metrics (packet_size, latency, throughput, …) stay None.
        #   observed is always False; simulated is always True.
        network = NetworkContext(
            ip_src=raw.get("ip_src"),
            ip_dst=raw.get("ip_dst") or raw.get("destination_ip"),
            mac_src=raw.get("mac_src"),
            source_port=raw.get("port_src") or raw.get("source_port"),
            # Destination routing stays in metadata for compatibility with
            # the existing simulated-network contract. It is not inferred.
            # packet_size      : calculated by mqtt_listener, not here
            # latency          : network_monitor responsibility
            # throughput       : network_monitor responsibility
            # packet_count     : network_monitor responsibility
            # bytes_total      : network_monitor responsibility
            # avg_interval     : network_monitor responsibility
            observed=False,
            simulated=True,
        )

        # --- 10. Metadata — preserve ALL unknown / extra fields ---------------
        #   Everything in the payload that was not consumed by the sub-contracts
        #   above ends up here verbatim, ensuring zero information loss.
        #   Explicitly excluded: zone is already in DeviceContext.
        metadata: dict[str, Any] = {
            k: v
            for k, v in raw.items()
            if k not in _CONSUMED_KEYS
        }

        # --- 11. Assemble and return ------------------------------------------
        return CommonEvent(
            event_kind=event_kind,
            transport=transport_enum,
            occurred_at=occurred_at,
            device=device,
            source=raw.get("source") or transport_enum.value,
            event_type=raw.get("event_type") or event_kind.value,
            severity=raw.get("severity"),
            attack_type=raw.get("attack_type"),
            anomaly_score=raw.get("anomaly_score"),
            data=data,
            identity=identity,
            network=network,
            raw_payload=raw,
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Module-level convenience alias
# ---------------------------------------------------------------------------

#: Functional alias — ``from backend.events.normalizer import normalize``
normalize = EventNormalizer.normalize
