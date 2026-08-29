import joblib
import numpy as np
import os

from backend.logger import logger

MODELS = {}
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")


def load_models() -> None:
    """Load optional legacy models without making application startup fragile."""
    MODELS.clear()
    for name in ["temperature", "humidity", "vibration", "smoke", "camera"]:
        path = os.path.join(MODEL_DIR, f"{name}_model.pkl")
        if os.path.exists(path):
            try:
                MODELS[name] = joblib.load(path)
            except Exception:
                logger.exception("Ignoring invalid ML model name=%s path=%s", name, path)


def _safe_numpy_array(value):
    """Convert *value* into a float array usable by scikit-learn models.

    Returns ``None`` when the value is invalid or incompatible.
    """
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return np.array([[numeric]])


def _safe_predict(model, X):
    """Return model prediction or ``None`` on error."""
    try:
        return model.predict(X)[0]
    except Exception:
        logger.exception("ML predict failed; using fallback")
        return None


def _safe_decision(model, X):
    """Return model decision function value or ``None`` on error."""
    try:
        return float(model.decision_function(X)[0])
    except Exception:
        logger.exception("ML decision_function failed; using fallback")
        return None


def is_anomaly(dev_type, value):
    """
    Returns (is_anomaly: bool, score: float).

    - is_anomaly: True when the model predicts an anomaly.
    - score: normalized anomaly score in [0, 1].
    """
    if not dev_type or dev_type not in MODELS:
        return False, 0.0

    model = MODELS[dev_type]
    X = _safe_numpy_array(value)
    if X is None:
        logger.warning("ML value rejected type=%s value=%r", dev_type, value)
        return False, 0.0

    prediction = _safe_predict(model, X)
    if prediction is None:
        return False, 0.0

    is_ano = bool(prediction == -1)

    decision = _safe_decision(model, X)
    if decision is None:
        return is_ano, 0.0

    score = 0.5 - decision * 3.0
    score = max(0.0, min(1.0, score))
    return is_ano, float(score)
