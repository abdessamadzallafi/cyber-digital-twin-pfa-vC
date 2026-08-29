"""Backend-facing data-lake port. Storage may be replaced without API changes."""
from typing import Any, Mapping
from smart_port.data.data_lake import write_event


class DataLakeWriter:
    def append(self, stream: str, record: Mapping[str, Any]) -> str:
        return str(write_event(stream, record))
