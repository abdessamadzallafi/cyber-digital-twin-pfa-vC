"""Append-only JSONL data lake sink for raw operational evidence."""
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Mapping
import json

from smart_port.config import settings


STREAMS = frozenset({"telemetry", "security", "missions", "network", "logs"})
_write_lock = Lock()


def _stream_path(stream: str) -> str:
    """Keep storage names stable even when callers use a domain alias."""
    aliases = {"siem": "security", "audit": "logs", "mission": "missions"}
    stream = aliases.get(stream, stream)
    if stream not in STREAMS:
        raise ValueError(f"Unsupported data lake stream: {stream}")
    return stream


def write_event(stream: str, event: Mapping[str, Any]) -> Path:
    """Persist raw events independently from the operational database.

    JSON Lines is intentionally dependency-free and can later be ingested by a
    warehouse/object store without changing the edge ingestion contract.
    """
    stream = _stream_path(stream)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target = Path(settings.data_lake_path) / stream / f"{day}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {"ingested_at": datetime.now(timezone.utc).isoformat(), **dict(event)}
    # Multiple MQTT/HTTP/UDP handlers can append concurrently in one process.
    # Serialising each line avoids partial/interleaved JSONL records.
    with _write_lock, target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
    return target


def lake_summary() -> dict[str, dict[str, int]]:
    """Return a cheap, dependency-free catalogue for the dashboard/API."""
    root = Path(settings.data_lake_path)
    result: dict[str, dict[str, int]] = {}
    for stream in sorted(STREAMS):
        files = list((root / stream).glob("*.jsonl")) if (root / stream).exists() else []
        event_count = 0
        for path in files:
            try:
                with path.open(encoding="utf-8") as handle:
                    event_count += sum(1 for _ in handle)
            except OSError:
                # A concurrently rotated/unreadable file should not make the
                # dashboard catalog endpoint fail.
                continue
        result[stream] = {"files": len(files), "events": event_count}
    return result
