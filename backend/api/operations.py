"""Operational read API used by the command dashboard.

These endpoints deliberately expose a stable, versioned view over the SQLite
operational store and the append-only JSONL data lake.  They are lightweight
enough for the demo and map directly to production service boundaries.
"""
from pathlib import Path
from fastapi import APIRouter, Depends, Query

from backend.core.dependencies import CurrentUser, get_db, get_siem_service
from backend.database.models import Alert, Incident, Mission, NetworkFlow, SensorReading, SiemEvent
from backend.ros.drone_manager import drone_manager
from backend.siem.platform import SmartPortSiem
from smart_port.data.data_lake import lake_summary
from smart_port.edge.device_registry import DEVICE_REGISTRY

router = APIRouter(prefix="/api/v1/ops", tags=["Operations"])


@router.get("/map")
def port_map(_: dict = CurrentUser):
    return {"name": "Terminal Tanger Med", "assets": [
        {"device_id": item.device_id, "type": item.device_type, "zone": item.zone,
         "coordinates": {"x": index * 12 + 10, "y": (index % 3) * 24 + 18}}
        for index, item in enumerate(DEVICE_REGISTRY.values())
    ], "drone": drone_manager.status()}


@router.get("/datalake")
def data_lake_catalog(_: dict = CurrentUser):
    return {"format": "jsonl", "retention": "append-only", "streams": lake_summary()}


@router.get("/network")
def network_overview(limit: int = Query(50, ge=1, le=500), db=Depends(get_db), _: dict = CurrentUser):
    flows = db.query(NetworkFlow).order_by(NetworkFlow.end_time.desc()).limit(limit).all()
    return {"protocols": ["UDP", "HTTP", "MQTT"], "flows": flows,
            "metrics": {"packets": sum(flow.packet_count for flow in flows),
                        "bytes": sum(flow.bytes_total for flow in flows),
                        "loss_percent": None,
                        "latency_ms": None}}


@router.get("/security")
def security_overview(limit: int = Query(50, ge=1, le=500), db=Depends(get_db), _: dict = CurrentUser):
    alerts = db.query(Alert).order_by(Alert.created_at.desc()).limit(limit).all()
    attacks = ["mqtt_flood", "spoofing", "unknown_device", "impossible_values", "dos", "network_anomaly"]
    return {"detections": attacks, "alerts": alerts, "mitre_attack": {
        "mqtt_flood": "T1499 – Endpoint Denial of Service",
        "spoofing": "T1550 – Use Alternate Authentication Material",
        "unknown_device": "T1078 – Valid Accounts / unauthorized asset",
        "network_anomaly": "T1046 – Network Service Discovery"}}


@router.get("/mission")
def missions(limit: int = Query(50, ge=1, le=500), db=Depends(get_db), _: dict = CurrentUser):
    return {"drone": drone_manager.status(), "missions": db.query(Mission).order_by(Mission.created_at.desc()).limit(limit).all()}


@router.get("/analytics")
def analytics(db=Depends(get_db), _: dict = CurrentUser):
    total = db.query(SensorReading).count()
    anomalies = db.query(Alert).filter(Alert.alert_type.in_(["ml_anomaly", "network_flood", "unknown_device", "bad_token"])).count()
    return {"telemetry_events": total, "anomalies": anomalies,
            "anomaly_rate": round(anomalies / total, 4) if total else 0.0,
            "models": ["impossible_values", "mqtt_flood", "spoofing", "unknown_device", "dos", "network_anomaly"]}


@router.get("/statistics")
def statistics(db=Depends(get_db), siem: SmartPortSiem = Depends(get_siem_service), _: dict = CurrentUser):
    return {"devices": len(DEVICE_REGISTRY), "telemetry": db.query(SensorReading).count(),
            "alerts": db.query(Alert).count(), "incidents_open": db.query(Incident).filter(Incident.status != "resolved").count(),
            "risk": siem.risk.calculate(db), "data_lake": lake_summary()}


@router.get("/reports")
def reports(_: dict = CurrentUser):
    return [{"filename": path.name, "size": path.stat().st_size} for path in sorted(Path("reports").glob("*.pdf"), reverse=True)]


@router.get("/siem/timeline")
def siem_timeline(limit: int = Query(100, ge=1, le=1000), db=Depends(get_db), _: dict = CurrentUser):
    return db.query(SiemEvent).order_by(SiemEvent.occurred_at.desc()).limit(limit).all()
