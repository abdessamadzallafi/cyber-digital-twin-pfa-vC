# backend/ml/network_anomaly.py
import joblib
import numpy as np
import os

from backend.logger import logger

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "network_model.pkl")
model = None

def load_network_model():
    global model
    if os.path.exists(MODEL_PATH):
        try:
            model = joblib.load(MODEL_PATH)
        except Exception:
            model = None
            logger.exception("Ignoring invalid network ML model path=%s", MODEL_PATH)
    else:
        model = None

def is_network_anomaly(device_id, net_info):
    if model is None:
        return False
    try:
        features = [net_info["packet_count"], net_info["bytes_total"],
                    net_info["avg_interval"], net_info["throughput"]]
        X = np.array([features], dtype=float)
        return model.predict(X)[0] == -1
    except (KeyError, TypeError, ValueError, AttributeError):
        logger.exception("Network ML inference failed; using deterministic rules")
        return False

# Chargement automatique au premier import
load_network_model()
