from contextlib import asynccontextmanager
from pathlib import Path

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

from backend.database import SessionLocal, SensorReading, Alert, Incident, engine as db_engine, verify_schema
from backend.ml.anomaly_detector import load_models
from backend.ml.prediction_service import load_prediction_models
from backend.mqtt_listener import metrics as mqtt_metrics, start_mqtt, stop_mqtt
from backend.logger import logger
from backend.auth import authenticate_user, create_access_token, get_current_user, jwt_auth_middleware, ACCESS_TOKEN_EXPIRE_MINUTES
from smart_port.application.router import router as platform_router
from backend.api.router import api_router
from backend.core.config import settings
from backend.siem.platform import SmartPortSiem
from backend.schemas.siem import SiemEventIn
from backend.schemas.platform import TelemetryIn
from backend.services.platform_service import PlatformService
from smart_port.communication.udp_telemetry import start_udp_telemetry
from smart_port.config import settings as platform_settings
from smart_port.data.data_lake import lake_summary

connected_websockets = set()
update_queue: asyncio.Queue | None = None
loop = None
udp_transport = None
mqtt_thread = None
broadcast_task = None


async def ingest_udp_payload(payload: dict) -> None:
    """UDP gateway -> canonical HTTP/service ingestion boundary."""
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
    global loop, udp_transport, mqtt_thread, broadcast_task, update_queue
    settings.validate_for_runtime()
    
    verify_schema(db_engine)
    logger.info("Existing database schema verified")
    
    loop = asyncio.get_running_loop()
    update_queue = asyncio.Queue(maxsize=settings.websocket_queue_size)
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


app = FastAPI(title="SecurIoT-Port", lifespan=lifespan)
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
app.middleware("http")(jwt_auth_middleware)
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
    token = websocket.query_params.get("token")
    try:
        if not token:
            raise HTTPException(status_code=401, detail="WebSocket token missing")
        get_current_user(token)
    except HTTPException:
        await websocket.close(code=1008, reason="WebSocket authentication failed")
        return
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
    from datetime import datetime, timedelta

    db = SessionLocal()
    now = datetime.utcnow()
    fresh_since = now - timedelta(minutes=30)
    window_since = now - timedelta(hours=24)
    fresh = db.query(SensorReading).filter(
        SensorReading.device_id == device_id,
        SensorReading.received_at >= fresh_since,
    ).count()
    if fresh == 0:
        any_recent = db.query(SensorReading).filter(
            SensorReading.device_id == device_id,
            SensorReading.received_at >= window_since,
        ).count()
        db.close()
        return {
            "device_id": device_id,
            "health_score": None,
            "status": "stale" if any_recent else "unknown",
        }
    anomalies = db.query(Alert).filter(
        Alert.device_id == device_id,
        Alert.alert_type == "ml_anomaly",
        Alert.created_at >= fresh_since,
    ).count()
    db.close()
    ratio = anomalies / fresh
    score = max(0, 100 - int(ratio * 200))
    return {"device_id": device_id, "health_score": score, "status": "ok"}

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
