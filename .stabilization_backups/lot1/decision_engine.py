from backend.ml.anomaly_detector import is_anomaly
from backend.ml.network_anomaly import is_network_anomaly
from backend.ml.prediction_service import prediction_service
from backend.security.engine import check_security
from backend.logger import logger
from backend.network.network_monitor import check_network_anomalies
from smart_port.analytics.correlation_engine import correlate

def make_decision(data, net_info):
    device_id = data.get("device_id")
    dev_type = data.get("type")
    token = data.get("token", "")
    topic = data.get("mqtt_topic", "")
    alerts = []   # chaque alerte = (alert_type, message)
    threat_level = "green"

    # 1. Sécurité
    sec_alerts = check_security(device_id, token, topic)
    for alert_type, msg in sec_alerts:
        alerts.append((alert_type, msg))
    if sec_alerts:
        threat_level = "red"

    # 2. Réseau
    net_alerts = check_network_anomalies(device_id, net_info)
    for alert_type, msg in net_alerts:
        alerts.append((alert_type, msg))
    if net_alerts:
        threat_level = "red"

    # 3. Legacy scalar models (smoke, vibration and camera remain compatible).
    ml_anomaly = False
    raw_score = 0.0
    if dev_type in ["temperature", "humidity", "vibration", "smoke"]:
        sensor_value = data.get("value")
    elif dev_type == "camera":
        sensor_value = data.get("people_count")
    else:
        sensor_value = None

    if sensor_value is not None:
        try:
            if dev_type == "camera":
                ml_anomaly, raw_score = is_anomaly("camera", sensor_value)
            elif dev_type in ["temperature", "humidity", "vibration", "smoke"]:
                ml_anomaly, raw_score = is_anomaly(dev_type, sensor_value)
        except (TypeError, ValueError):
            logger.exception("Scalar ML inference rejected device=%s type=%s", device_id, dev_type)

    if ml_anomaly:
        alerts.append(("ml_anomaly", f"Anomalie IA sur {dev_type} (score={raw_score:.2f})"))
        threat_level = "red" if threat_level != "red" else "red"

    # 4. Multi-domain Isolation Forest inference.
    try:
        predictions = prediction_service.analyze(data, net_info)
    except (TypeError, ValueError, KeyError):
        logger.exception("Advanced ML inference rejected device=%s type=%s", device_id, dev_type)
        predictions = []
    advanced_anomalies = [item for item in predictions if item.anomalous]
    for item in advanced_anomalies:
        alerts.append(("ml_anomaly", f"AI anomaly: {item.domain} (score={item.score:.2f})"))
        raw_score = max(raw_score, item.score)
        threat_level = "red"

    # 5. Legacy network model remains a compatibility signal.
    try:
        net_ml_anomaly = is_network_anomaly(device_id, net_info)
    except (TypeError, ValueError, KeyError):
        logger.exception("Network ML inference rejected device=%s", device_id)
        net_ml_anomaly = False
    if net_ml_anomaly:
        alerts.append(("ml_anomaly", "Anomalie réseau détectée"))
        threat_level = "red"
        raw_score = max(raw_score, 0.8)

    # 6. Autonomous inspection dispatch for safety, cyber and drone anomalies.
    create_mission = False
    mission_domains = {"temperature", "battery", "drone_trajectory", "sensor_failure", "flood_attack", "network_traffic"}
    if (ml_anomaly and dev_type in ["vibration", "smoke", "temperature"]) or any(item.domain in mission_domains for item in advanced_anomalies):
        create_mission = True

    any_anomaly = ml_anomaly or net_ml_anomaly or bool(advanced_anomalies)
    correlation = correlate(alerts, raw_score if any_anomaly else 0.0)
    return {
        "device_id": device_id,
        "anomaly": any_anomaly,
        "anomaly_score": raw_score if any_anomaly else 0.0,
        "threat_level": "red" if correlation["severity"] in {"high", "critical"} else threat_level,
        "dispatch_recommended": create_mission or correlation["dispatch_drone"],
        "create_mission": create_mission or correlation["dispatch_drone"],
        "alerts": alerts,
        "ai_predictions": [{"domain": item.domain, "anomalous": item.anomalous, "score": item.score} for item in predictions]
    }
