"""Transport-boundary regressions for telemetry units and UDP safety."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, SensorReading
from backend import mqtt_listener
from backend.schemas.platform import TelemetryIn
from backend.schemas.siem import SiemEventIn
from backend.services.platform_service import PlatformService
from smart_port.communication.udp_telemetry import (
    MAX_UDP_DATAGRAM_SIZE,
    UdpTelemetryProtocol,
)


class MemoryLake:
    def __init__(self):
        self.records = []

    def append(self, stream, record):
        self.records.append((stream, dict(record)))


def make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


@pytest.mark.parametrize(("transport", "unit"), [("http", "°C"), ("udp", "ppm")])
def test_platform_telemetry_preserves_unit_and_transport_siem_source(transport, unit):
    db = make_db()
    lake = MemoryLake()
    collected = []

    class CapturingSiem:
        def __init__(self, _db):
            pass

        def collect(self, event):
            collected.append(event)

    payload = TelemetryIn(
        device_id="grue_G01", type="temperature", value=22.5, unit=unit,
        token="tk_temp123", mqtt_topic="port/gantry_crane/temperature",
    )
    with patch("backend.services.platform_service.SmartPortSiem", CapturingSiem):
        PlatformService(db, lake=lake).ingest_telemetry(payload, transport=transport)

    assert db.query(SensorReading).one().unit == unit
    telemetry = next(record for stream, record in lake.records if stream == "telemetry")
    assert telemetry["unit"] == unit
    assert collected[0].source == transport
    assert collected[0].message == f"{transport.upper()} telemetry accepted from grue_G01"
    db.close()


def test_unit_is_optional_for_legacy_telemetry():
    assert TelemetryIn(device_id="grue_G01", type="temperature", value=22.5).unit is None


def test_legacy_device_identity_remains_valid_for_service_ingestion():
    db = make_db()

    class CapturingSiem:
        def __init__(self, _db):
            pass

        def collect(self, _event):
            pass

    payload = TelemetryIn(
        device_id="temp_01", type="temperature", value=22.5,
        token="tk_temp123", mqtt_topic="port/container01/temperature",
    )
    with patch("backend.services.platform_service.SmartPortSiem", CapturingSiem):
        result = PlatformService(db, lake=MemoryLake()).ingest_telemetry(payload)

    assert result["alerts"] == 0
    assert db.query(SensorReading).one().device_id == "grue_G01"
    db.close()


def test_siem_transport_sources_remain_validated():
    assert SiemEventIn(source="http", event_type="telemetry_ingested", message="ok").source == "http"
    assert SiemEventIn(source="udp", event_type="telemetry_ingested", message="ok").source == "udp"
    with pytest.raises(ValueError):
        SiemEventIn(source="invalid", event_type="telemetry_ingested", message="no")


def test_udp_ignores_malformed_and_non_object_json():
    callback = AsyncMock()
    protocol = UdpTelemetryProtocol(callback)

    protocol.datagram_received(b"{broken", ("127.0.0.1", 1000))
    protocol.datagram_received(b"[1, 2]", ("127.0.0.1", 1000))
    protocol.datagram_received(b'"scalar"', ("127.0.0.1", 1000))
    protocol.datagram_received(b"42", ("127.0.0.1", 1000))

    callback.assert_not_awaited()


def test_udp_preserves_unit_and_udp_metadata():
    async def run():
        callback = AsyncMock()
        protocol = UdpTelemetryProtocol(callback)
        protocol.datagram_received(
            b'{"device_id":"entrepot_E01","type":"smoke","value":1.0,"unit":"ppm"}',
            ("192.0.2.10", 4000),
        )
        await asyncio.sleep(0)
        callback.assert_awaited_once()
        payload = callback.await_args.args[0]
        assert payload["unit"] == "ppm"
        assert payload["transport"] == "udp"
        assert payload["source_address"] == "192.0.2.10"

    asyncio.run(run())


def test_udp_callback_errors_are_consumed_safely():
    async def fail(_payload):
        raise RuntimeError("service unavailable")

    async def run():
        protocol = UdpTelemetryProtocol(fail)
        protocol.datagram_received(b'{"device_id":"grue_G01"}', ("127.0.0.1", 1000))
        await asyncio.sleep(0)

    asyncio.run(run())


def test_udp_ignores_oversized_datagrams():
    callback = AsyncMock()
    protocol = UdpTelemetryProtocol(callback)
    protocol.datagram_received(b"x" * (MAX_UDP_DATAGRAM_SIZE + 1), ("127.0.0.1", 1000))
    callback.assert_not_awaited()


@pytest.mark.parametrize("payload", [
    {"device_id": "grue_G01", "type": "temperature", "value": 23.1, "unit": "°C", "token": "tk_temp123"},
    {"device_id": "camera_Q01", "type": "camera", "people_count": 2, "token": "tk_cam000"},
    {"device_id": "temp_01", "type": "temperature", "value": -200, "token": "tk_temp123"},
    {"device_id": "hacker_01", "type": "malware", "value": 0, "token": "bad"},
])
def test_mqtt_callback_accepts_existing_simulator_and_attack_payload_shapes(payload):
    async def run():
        old_loop, old_queue = mqtt_listener.loop, mqtt_listener.ingress_queue
        queue = asyncio.Queue()
        mqtt_listener.loop = asyncio.get_running_loop()
        mqtt_listener.ingress_queue = queue
        try:
            mqtt_listener.on_message(
                None, None,
                SimpleNamespace(payload=json.dumps(payload).encode("utf-8"), topic="port/test/topic"),
            )
            accepted = await asyncio.wait_for(queue.get(), timeout=1)
        finally:
            mqtt_listener.loop, mqtt_listener.ingress_queue = old_loop, old_queue
        assert accepted["mqtt_topic"] == "port/test/topic"
        assert accepted["device_id"] == payload["device_id"]

    asyncio.run(run())
