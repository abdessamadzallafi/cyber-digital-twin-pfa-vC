"""Generate deterministic demonstration evidence for every Data Lake stream.

Run with ``python simulation/data_lake_seed.py`` before a jury demonstration.
It does not need Mosquitto, Gazebo, or the API to be running.
"""
import sys
import time
from pathlib import Path

# Make direct execution from the project root and from this directory reliable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smart_port.data.data_lake import write_event


def main() -> None:
    now = time.time()
    records = {
        "telemetry": {"device_id": "grue_G01", "type": "temperature", "value": 27.4, "unit": "C", "timestamp": now},
        "security": {"device_id": "drone_01", "alert_type": "mqtt_flood", "severity": "high", "mitre": "T1499", "timestamp": now},
        "missions": {"mission_id": "drone_demo_001", "drone_id": "drone_01", "mission_type": "inspection", "status": "created", "timestamp": now},
        "network": {"transport": "udp", "device_id": "station_H01", "packets": 12, "latency_ms": 4.2, "loss_percent": 0.0, "timestamp": now},
        "logs": {"level": "info", "source": "seed", "message": "Smart Port demo dataset initialised", "timestamp": now},
    }
    for stream, record in records.items():
        print(write_event(stream, record))


if __name__ == "__main__":
    main()
