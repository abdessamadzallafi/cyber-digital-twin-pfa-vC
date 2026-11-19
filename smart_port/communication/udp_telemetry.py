"""Optional UDP telemetry adapter for edge equipment that cannot run MQTT."""
import asyncio
import json
import logging
from typing import Awaitable, Callable


logger = logging.getLogger(__name__)
# Telemetry packets are small JSON documents.  This cap leaves headroom for
# metadata while preventing a UDP sender from making the gateway decode an
# unexpectedly large packet.
MAX_UDP_DATAGRAM_SIZE = 64 * 1024


class UdpTelemetryProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_payload: Callable[[dict], Awaitable[None]]):
        self.on_payload = on_payload

    def datagram_received(self, data: bytes, addr):
        if len(data) > MAX_UDP_DATAGRAM_SIZE:
            logger.warning("Ignoring oversized UDP telemetry datagram from %s", addr[0])
            return
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        payload.setdefault("transport", "udp")
        payload.setdefault("source_address", addr[0])
        try:
            task = asyncio.create_task(self.on_payload(payload))
        except Exception:
            logger.exception("UDP telemetry callback could not be scheduled")
            return
        task.add_done_callback(self._consume_callback_error)

    @staticmethod
    def _consume_callback_error(task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("UDP telemetry callback failed")


async def start_udp_telemetry(host: str, port: int, on_payload: Callable[[dict], Awaitable[None]]):
    loop = asyncio.get_running_loop()
    return await loop.create_datagram_endpoint(lambda: UdpTelemetryProtocol(on_payload), local_addr=(host, port))
