"""Versioned industrial API additions. Legacy endpoints remain mounted at root."""
from fastapi import APIRouter
from sqlalchemy import text

from smart_port.config import settings
from smart_port.edge.device_registry import DEVICE_REGISTRY
from backend.mqtt_listener import metrics as mqtt_metrics
from backend.database import SessionLocal

router = APIRouter(prefix="/api/v1", tags=["Smart Port Platform"])


@router.get("/platform/health")
def platform_health():
    database_available = False
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            database_available = True
        finally:
            db.close()
    except Exception:
        database_available = False
    return {
        "service": "SecurIoT-Port",
        "status": "operational",
        "layers": ["edge", "communication", "data", "analytics", "application", "presentation"],
        "mqtt": {"host": settings.mqtt_host, "port": settings.mqtt_port,
                 "status": "online" if mqtt_metrics["mqtt_connected"] else "offline"},
        "database_available": database_available,
        "websocket_available": True,
    }


@router.get("/edge/devices")
def edge_devices():
    return [{"device_id": item.device_id, "type": item.device_type, "zone": item.zone, "topic": item.topic} for item in DEVICE_REGISTRY.values()]
