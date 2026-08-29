"""Optional UDP telemetry adapter for edge equipment that cannot run MQTT."""
import asyncio
import json
from typing import Awaitable, Callable


class UdpTelemetryProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_payload: Callable[[dict], Awaitable[None]]):
        self.on_payload = on_payload

    def datagram_received(self, data: bytes, addr):
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        payload.setdefault("transport", "udp")
        payload.setdefault("source_address", addr[0])
        asyncio.create_task(self.on_payload(payload))


async def start_udp_telemetry(host: str, port: int, on_payload: Callable[[dict], Awaitable[None]]):
    loop = asyncio.get_running_loop()
    return await loop.create_datagram_endpoint(lambda: UdpTelemetryProtocol(on_payload), local_addr=(host, port))
