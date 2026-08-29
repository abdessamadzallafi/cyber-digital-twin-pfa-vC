from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
import asyncio
import threading
import time
import json
from datetime import datetime, timedelta
from typing import Any, Mapping
import paho.mqtt.client as mqtt
from sqlalchemy import text

from backend.database import SessionLocal, SensorReading, Alert, Mission, Incident, engine as db_engine, Base as DatabaseBase
from backend.ml.anomaly_detector import load_models
from backend.ml.prediction_service import load_prediction_models
from backend.mqtt_listener import metrics as mqtt_metrics, start_mqtt, stop_mqtt
from backend.logger import logger
from backend.auth import authenticate_user, create_access_token, get_current_user, ACCESS_TOKEN_EXPIRE_MINUTES
from smart_port.application.router import router as platform_router
from backend.api.router import api_router
from backend.core.config import settings
from backend.siem.platform import SmartPortSiem
from backend.schemas.siem import SiemEventIn
from backend.schemas.platform import TelemetryIn
from backend.services.platform_service import PlatformService
from smart_port.communication.udp_telemetry import start_udp_telemetry
from smart_port.config import settings as platform_settings
from backend.events.normalizer import EventNormalizer
from backend.events.contracts import Transport as EventTransport
from backend.mission_planner import create_mission

connected_websockets = set()
update_queue = asyncio.Queue(maxsize=settings.websocket_queue_size)
loop = None
udp_transport = None
mqtt_thread = None
broadcast_task = None


async def ingest_udp_payload(payload: dict) -> None:
    """UDP gateway -> canonical HTTP/service ingestion boundary."""
    # --- Additive CommonEvent envelope ---------------------------------------
    # Built from the original raw UDP dict BEFORE TelemetryIn(**payload) strips
    # unknown fields (e.g. latitude, longitude, bool status, port_src, …).
    # All existing consumers are completely unchanged.
    _udp_common_event = EventNormalizer.normalize(payload, EventTransport.UDP)
    # --- Existing pipeline (unchanged) ---------------------------------------
    db = SessionLocal()
    try:
        PlatformService(db).ingest_telemetry(TelemetryIn(**payload), transport="udp")
    except Exception:
        logger.exception("UDP telemetry rejected")
    finally:
        db.close()

async def audit_http_requests(request, call_next):
    """Collect HTTP access evidence without making SIEM availability a dependency."""
    started = time.time()
    response = await call_next(request)
    try:
        db = SessionLocal()
        try:
            SmartPortSiem(db).collect(SiemEventIn(
                source="http", event_type="http_request",
                severity="medium" if response.status_code >= 400 else "info",
                message=f"{request.method} {request.url.path} -> {response.status_code}",
                payload={"method": request.method, "path": request.url.path,
                         "status_code": response.status_code, "duration_ms": round((time.time() - started) * 1000, 2)}))
        finally:
            db.close()
    except Exception:
        logger.exception("SIEM HTTP audit failed")
    return response

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start optional ingress services and always release them cleanly.

    MQTT and UDP are intentionally non-fatal for the REST control plane: a
    local demo can still use HTTP ingestion when a broker or UDP port is not
    available.  Model loading has the same property; the ML layer exposes its
    documented rules-based fallback when no valid model is present.
    """
    global loop, udp_transport, mqtt_thread, broadcast_task
    settings.validate_for_runtime()
    
    # Ensure all database tables exist
    try:
        DatabaseBase.metadata.create_all(bind=db_engine)
        logger.info("Database tables initialized successfully")
    except Exception:
        logger.exception("Database table initialization failed; continuing")
    
    loop = asyncio.get_running_loop()
    try:
        load_models()
        load_prediction_models()
    except Exception:
        logger.exception("ML model loading failed; continuing with fallback detection")
    mqtt_thread = threading.Thread(target=start_mqtt, args=(loop, update_queue), daemon=True, name="mqtt-listener")
    mqtt_thread.start()
    try:
        udp_transport, _ = await start_udp_telemetry(platform_settings.udp_host, platform_settings.udp_port, ingest_udp_payload)
    except OSError:
        # UDP is an optional ingress; an occupied/unavailable port must never
        # make the HTTP control plane unavailable.
        udp_transport = None
        logger.exception("UDP telemetry gateway unavailable; continuing without UDP")
    broadcast_task = asyncio.create_task(broadcast(), name="websocket-broadcast")
    try:
        yield
    finally:
        stop_mqtt()
        if udp_transport:
            udp_transport.close()
            udp_transport = None
        if broadcast_task:
            broadcast_task.cancel()
            try:
                await broadcast_task
            except asyncio.CancelledError:
                pass
            broadcast_task = None
        for websocket in list(connected_websockets):
            try:
                await websocket.close(code=1012)
            except RuntimeError:
                logger.debug("WebSocket already closed during shutdown")
        connected_websockets.clear()


app = FastAPI(title="Smart Port Security Platform", lifespan=lifespan)
app.include_router(platform_router)
app.include_router(api_router)

_cors_origins = list(settings.cors_origins)
if not _cors_origins or _cors_origins == ["*"]:
    # Wildcard origins are incompatible with allow_credentials=True in FastAPI/Starlette.
    # Fall back to explicit localhost origins so Authorization headers still work in dev.
    _cors_origins = ["http://localhost:3000", "http://localhost:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.middleware("http")(audit_http_requests)

async def broadcast():
    while True:
        msg = await update_queue.get()
        dead = set()
        for ws in connected_websockets:
            try:
                await ws.send_json(msg)
            except (WebSocketDisconnect, RuntimeError):
                dead.add(ws)
        connected_websockets.difference_update(dead)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_websockets.discard(websocket)

# ---------- AUTHENTIFICATION ----------
@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Identifiants incorrects")
    access_token = create_access_token(
        data={"sub": user["username"]},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token, "token_type": "bearer"}

# ---------- STATISTIQUES ----------
@app.get("/statistics")
def get_statistics():
    db = SessionLocal()
    total_devices = db.query(SensorReading.device_id).distinct().count()
    now = time.time()
    active_threshold = now - 10
    active_devices = db.query(SensorReading.device_id).filter(
        SensorReading.timestamp >= active_threshold
    ).distinct().count()
    offline_devices = total_devices - active_devices
    total_alerts = db.query(Alert).count()
    attacks = db.query(Alert).filter(Alert.alert_type.in_(
        ["flood", "unknown_device", "bad_token", "wrong_topic", "network_flood", "unknown_ip"])).count()
    ml_anomalies = db.query(Alert).filter(Alert.alert_type == "ml_anomaly").count()
    flood_count = db.query(Alert).filter(Alert.alert_type == "flood").count()
    spoof_count = db.query(Alert).filter(Alert.alert_type == "bad_token").count()
    unknown_count = db.query(Alert).filter(Alert.alert_type == "unknown_device").count()
    db.close()
    return {
        "total_devices": total_devices,
        "active_devices": active_devices,
        "offline_devices": offline_devices,
        "total_alerts": total_alerts,
        "attacks": attacks,
        "ml_anomalies": ml_anomalies,
        "flood_count": flood_count,
        "spoof_count": spoof_count,
        "unknown_count": unknown_count
    }

@app.get("/dashboard")
def get_dashboard():
    db = SessionLocal()
    now = time.time()
    active_threshold = now - 10
    device_ids = [row[0] for row in db.query(SensorReading.device_id).distinct().all()]
    devices = []
    for dev_id in device_ids:
        last = db.query(SensorReading).filter(SensorReading.device_id == dev_id)\
                  .order_by(SensorReading.received_at.desc()).first()
        if last:
            active = last.timestamp >= active_threshold
            alerts = db.query(Alert).filter(Alert.device_id == dev_id,
                                            Alert.created_at >= datetime.utcfromtimestamp(now - 60))\
                                      .all()
            alert_list = [a.message for a in alerts]
            status = "green"
            if any(a.alert_type in ["flood", "unknown_device", "bad_token", "wrong_topic", "network_flood", "unknown_ip"] for a in alerts):
                status = "red"
            elif any(a.alert_type == "ml_anomaly" for a in alerts):
                status = "yellow"
            devices.append({
                "device_id": dev_id,
                "type": last.type,
                "value": last.value,
                "status": last.status,
                "people_count": last.people_count,
                "latitude": last.latitude,
                "longitude": last.longitude,
                "last_update": last.timestamp,
                "active": active,
                "alerts": alert_list,
                "overall_status": status
            })
    db.close()
    return {"devices": devices, "server_time": time.time()}

# ---------- SANTÉ & RISQUE ----------
@app.get("/health", tags=["Platform"])
def platform_healthcheck():
    """Small unauthenticated liveness/readiness response for local orchestration."""
    database_available = False
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            database_available = True
        finally:
            db.close()
    except Exception:
        logger.warning("Health check database probe failed", exc_info=True)

    mqtt_status = "connected" if mqtt_metrics["mqtt_connected"] else "disconnected"
    return {
        "status": "ok" if database_available else "degraded",
        "api": "ok",
        "database": "available" if database_available else "unavailable",
        "mqtt": mqtt_status,
    }


@app.get("/health/{device_id}")
def get_device_health(device_id: str):
    db = SessionLocal()
    total = db.query(SensorReading).filter(SensorReading.device_id == device_id).count()
    anomalies = db.query(Alert).filter(
        Alert.device_id == device_id,
        Alert.alert_type == "ml_anomaly"
    ).count()
    db.close()
    if total == 0:
        return {"device_id": device_id, "health_score": 100}
    ratio = anomalies / total
    score = max(0, 100 - int(ratio * 200))
    return {"device_id": device_id, "health_score": score}

@app.get("/risk")
def get_risk_score():
    db = SessionLocal()
    now = time.time()
    recent = now - 300  # 5 minutes
    total_alerts = db.query(Alert).filter(Alert.timestamp >= recent).count()
    attacks = db.query(Alert).filter(
        Alert.alert_type.in_(["flood", "unknown_device", "bad_token", "network_flood", "unknown_ip"]),
        Alert.timestamp >= recent
    ).count()
    db.close()
    if total_alerts == 0:
        return {"risk_score": 0, "score": 0, "level": "Low"}
    ratio = attacks / total_alerts if total_alerts else 0.0
    score = max(0, min(100, int(ratio * 100)))
    if score < 30:
        level = "Low"
    elif score < 60:
        level = "Medium"
    else:
        level = "High"
    return {"risk_score": score, "score": score, "level": level}

# ---------- SIMULATION ATTAQUES (protégées) ----------
def publish_attack(topic: str, payload_dict: Mapping[str, Any]) -> None:
    """Publish a protected simulation event through the configured MQTT broker."""
    try:
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="attack-simulator")
        except AttributeError:
            client = mqtt.Client(client_id="attack-simulator")
        if platform_settings.mqtt_tls:
            client.tls_set(ca_certs=platform_settings.mqtt_ca_file)
        client.connect(settings.mqtt_host, settings.mqtt_port, 60)
        client.loop_start()
        try:
            result = client.publish(topic, json.dumps(payload_dict))
            result.wait_for_publish()
            rc = result.rc
            if isinstance(rc, int) and rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT attack simulation publish failed: rc={rc}")
        finally:
            client.disconnect()
            client.loop_stop()
    except Exception:
        logger.exception("MQTT attack simulation failed")
        raise

@app.post("/simulate/flood")
def simulate_flood(current_user: dict = Depends(get_current_user)):
    logger.warning("Lancement simulation : Flood MQTT")
    for _ in range(20):
        publish_attack("port/container01/temperature", {
            "device_id": "temp_01",
            "type": "temperature",
            "value": 25.0,
            "token": "tk_temp123",
            "timestamp": time.time()
        })
        time.sleep(0.1)
    return {"status": "Flood attaque lancée"}

@app.post("/simulate/spoof")
def simulate_spoof(current_user: dict = Depends(get_current_user)):
    logger.warning("Lancement simulation : Spoofing")
    publish_attack("port/container01/temperature", {
        "device_id": "temp_01",
        "type": "temperature",
        "value": 999,
        "token": "faux_token",
        "timestamp": time.time()
    })
    return {"status": "Attaque spoofing envoyée"}

@app.post("/simulate/unknown")
def simulate_unknown(current_user: dict = Depends(get_current_user)):
    logger.warning("Lancement simulation : Appareil inconnu")
    publish_attack("port/unknown/device", {
        "device_id": "hacker_01",
        "type": "malware",
        "value": 0,
        "token": "bad",
        "timestamp": time.time()
    })
    return {"status": "Appareil inconnu envoyé"}

@app.post("/simulate/impossible")
def simulate_impossible(current_user: dict = Depends(get_current_user)):
    logger.warning("Lancement simulation : Valeur impossible")
    publish_attack("port/container01/temperature", {
        "device_id": "temp_01",
        "type": "temperature",
        "value": -200,
        "token": "tk_temp123",
        "timestamp": time.time()
    })
    return {"status": "Valeur impossible envoyée"}

# ---------- MISSION MANUELLE (protégée) ----------
@app.post("/force_mission/{device_id}")
def force_mission(device_id: str, current_user: dict = Depends(get_current_user)):
    try:
        create_mission(device_id, "manual")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": f"Mission manuelle envoyée à {device_id}"}

# ---------- RESEAU ----------
@app.get("/network/flow/{device_id}")
def get_network_flow(device_id: str, limit: int = 100):
    db = SessionLocal()
    flows = db.query(SensorReading).filter(SensorReading.device_id == device_id)\
              .order_by(SensorReading.received_at.desc()).limit(limit).all()
    result = [{
        "timestamp": f.timestamp,
        "ip_src": f.ip_src,
        "mac_src": f.mac_src,
        "packet_size": f.packet_size
    } for f in flows]
    db.close()
    return result

@app.get("/network/stats")
def get_network_stats():
    db = SessionLocal()
    alerts = db.query(Alert).filter(Alert.alert_type.in_(["network_flood", "unknown_ip"]))\
               .order_by(Alert.created_at.desc()).limit(50).all()
    db.close()
    return alerts

# ---------- DRONE ----------
@app.get("/drone/status")
def get_drone_status():
    """Legacy-dashboard-friendly facade over the canonical drone manager."""
    from backend.ros.drone_manager import drone_manager
    return drone_manager.status()

@app.get("/missions")
def get_missions():
    db = SessionLocal()
    missions = db.query(Mission).order_by(Mission.created_at.desc()).limit(20).all()
    db.close()
    return missions

# ---------- RAPPORT PDF ----------
@app.post("/report/{device_id}")
def create_report(device_id: str, anomaly_type: str = "ml_anomaly", current_user: dict = Depends(get_current_user)):
    from backend.report_generator import generate_incident_report
    filename = generate_incident_report(device_id, anomaly_type)
    return {"filename": filename, "status": "Report generated"}

# ---------- AUTRES (existants) ----------
@app.get("/equipments")
def get_equipments():
    db = SessionLocal()
    ids = [row[0] for row in db.query(SensorReading.device_id).distinct().all()]
    db.close()
    return {"equipments": ids}

@app.get("/measures/{device_id}")
def get_measures(device_id: str, limit: int = 100):
    db = SessionLocal()
    readings = db.query(SensorReading).filter(SensorReading.device_id == device_id)\
                  .order_by(SensorReading.received_at.desc()).limit(limit).all()
    db.close()
    return readings

@app.get("/alerts")
def get_alerts(limit: int = 100):
    db = SessionLocal()
    alerts = db.query(Alert).order_by(Alert.created_at.desc()).limit(limit).all()
    db.close()
    return alerts

@app.get("/ml/anomalies")
def get_ml_anomalies(limit: int = 50):
    db = SessionLocal()
    anomalies = db.query(Alert).filter(Alert.alert_type == "ml_anomaly")\
                    .order_by(Alert.created_at.desc()).limit(limit).all()
    db.close()
    return anomalies

@app.get("/security/events")
def get_security_events(limit: int = 50):
    db = SessionLocal()
    events = db.query(Alert).filter(Alert.alert_type.in_(
        ["flood", "unknown_device", "bad_token", "wrong_topic", "network_flood", "unknown_ip"]))\
              .order_by(Alert.created_at.desc()).limit(limit).all()
    db.close()
    return events

# ---------- INCIDENT MANAGEMENT ----------
@app.post("/incidents")
def create_incident(device_id: str, anomaly_type: str = "ml_anomaly", severity: str = "high",
                    description: str = "", current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    incident = Incident(
        device_id=device_id,
        anomaly_type=anomaly_type,
        severity=severity,
        description=description
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    db.close()
    return incident

@app.get("/incidents")
def get_incidents(status: str = None, limit: int = 50):
    db = SessionLocal()
    query = db.query(Incident).order_by(Incident.created_at.desc())
    if status:
        query = query.filter(Incident.status == status)
    incidents = query.limit(limit).all()
    db.close()
    return incidents

@app.put("/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: int, current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if incident:
        incident.status = "resolved"
        incident.resolved_at = datetime.utcnow()
        db.commit()
    db.close()
    return {"status": "updated"}

# ---------- TIMELINE ----------
@app.get("/timeline")
def get_timeline(limit: int = 50):
    db = SessionLocal()
    alerts = db.query(Alert).order_by(Alert.created_at.desc()).limit(limit).all()
    incidents = db.query(Incident).order_by(Incident.created_at.desc()).limit(limit).all()
    missions = db.query(Mission).order_by(Mission.created_at.desc()).limit(limit).all()

    events = []
    for a in alerts:
        events.append({"time": a.created_at.isoformat(), "type": "alert", "message": a.message, "device": a.device_id})
    for i in incidents:
        events.append({"time": i.created_at.isoformat(), "type": "incident", "message": f"Incident #{i.id} - {i.anomaly_type}", "device": i.device_id})
    for m in missions:
        events.append({"time": m.created_at.isoformat(), "type": "mission", "message": f"Mission {m.mission_id} - {m.status}", "device": m.device_id})

    # Trier par date décroissante
    events.sort(key=lambda x: x["time"], reverse=True)
    return events[:limit]

# ---------- DEVICE MANAGER ENRICHED ----------
@app.get("/devices")
def get_all_devices():
    db = SessionLocal()
    # Récupère tous les device_id distincts, avec leur dernière lecture
    device_ids = [row[0] for row in db.query(SensorReading.device_id).distinct().all()]
    devices = []
    now = time.time()
    for dev_id in device_ids:
        last = db.query(SensorReading).filter(SensorReading.device_id == dev_id).order_by(SensorReading.received_at.desc()).first()
        if last:
            active = (now - last.timestamp) < 10  # actif si moins de 10s
            # Calcul simplifié de la zone (basé sur le type ou le nom)
            zone = "Inconnue"
            if "temp" in dev_id or "hum" in dev_id or "vib" in dev_id:
                zone = "Conteneur"
            elif "cam" in dev_id:
                zone = "Sécurité"
            elif "gps" in dev_id:
                zone = "Véhicule"
            elif "gate" in dev_id:
                zone = "Accès"
            elif "smoke" in dev_id:
                zone = "Entrepôt"
            elif "pres" in dev_id:
                zone = "Parking"
            elif "drone" in dev_id:
                zone = "Inspection"
            # Récupérer le health score depuis l'endpoint dédié (ou calculer)
            # Pour simplifier, on appelle la fonction get_device_health
            health = get_device_health(dev_id)["health_score"]
            devices.append({
                "device_id": dev_id,
                "type": last.type,
                "zone": zone,
                "online": active,
                "last_value": last.value or last.status or last.people_count,
                "last_update": last.timestamp,
                "health_score": health
            })
    db.close()
    return devices

@app.get("/drone/missions")
def get_drone_missions(current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    missions = db.query(Mission).filter(Mission.drone_id == "drone_01").order_by(Mission.created_at.desc()).limit(10).all()
    db.close()
    return missions
