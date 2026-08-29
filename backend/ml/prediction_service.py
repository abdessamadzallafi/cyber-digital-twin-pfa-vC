"""Runtime multi-domain prediction service backed by Isolation Forest models."""
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
import time
import joblib
import numpy as np

from backend.ml.training import MODEL_DIR, TRAINING_SPECS
from smart_port.edge.device_registry import known_devices, validate_identity
from backend.logger import logger


@dataclass(frozen=True)
class Prediction:
    domain: str
    anomalous: bool
    score: float
    features: dict[str, float]


class PredictionService:
    def __init__(self):
        self.models: dict[str, dict] = {}
        self.last_seen: dict[str, float] = {}
        self.last_position: dict[str, tuple[float, float, float]] = {}
        self.lock = Lock()

    def load_models(self) -> None:
        """Load each optional bundle independently.

        A stale/corrupt joblib file must not disable HTTP, MQTT or the
        deterministic detection rules used by the local demonstration.
        """
        self.models.clear()
        for name in TRAINING_SPECS:
            path = Path(MODEL_DIR) / f"advanced_{name}.pkl"
            if path.exists():
                try:
                    bundle = joblib.load(path)
                    if not isinstance(bundle, dict) or "model" not in bundle or "features" not in bundle:
                        raise ValueError("invalid model bundle")
                    self.models[name] = bundle
                except Exception:
                    logger.exception("Ignoring invalid advanced ML model domain=%s path=%s", name, path)

    def _predict(self, domain: str, values: list[float]) -> Prediction | None:
        bundle = self.models.get(domain)
        if not bundle:
            return None
        try:
            model = bundle["model"]
            vector = np.asarray([values], dtype=float)
            anomalous = bool(model.predict(vector)[0] == -1)
            decision = float(model.decision_function(vector)[0])
        except (KeyError, TypeError, ValueError, AttributeError):
            logger.exception("Advanced ML inference failed domain=%s; using fallback", domain)
            return None
        score = max(0.0, min(1.0, 0.5 - decision * 3.0))
        return Prediction(domain, anomalous, score, dict(zip(bundle["features"], values)))

    def analyze(self, data: dict, network: dict) -> list[Prediction]:
        """Extract features once per event and predict all applicable domains."""
        timestamp = float(data.get("timestamp", time.time()))
        device_id = str(data.get("device_id", "unknown"))
        device_type = data.get("type")
        results: list[Prediction] = []
        with self.lock:
            if device_type in {"temperature", "humidity"} and data.get("value") is not None:
                result = self._predict(device_type, [float(data["value"])])
                if result: results.append(result)

            if data.get("battery") is not None:
                result = self._predict("battery", [float(data["battery"])])
                if result: results.append(result)

            if device_type == "drone" and data.get("x") is not None and data.get("y") is not None:
                x, y = float(data["x"]), float(data["y"])
                previous = self.last_position.get(device_id, (x, y, timestamp))
                elapsed = max(timestamp - previous[2], 0.001)
                dx, dy = x - previous[0], y - previous[1]
                speed = (dx ** 2 + dy ** 2) ** 0.5 / elapsed
                result = self._predict("drone_trajectory", [x, y, dx, dy, speed])
                if result: results.append(result)
                self.last_position[device_id] = (x, y, timestamp)

            previous_seen = self.last_seen.get(device_id, timestamp)
            has_measurement = float(any(data.get(field) is not None for field in ("value", "status", "people_count", "latitude", "battery")))
            result = self._predict("sensor_failure", [max(0.0, timestamp - previous_seen), has_measurement])
            if result: results.append(result)
            self.last_seen[device_id] = timestamp

            result = self._predict("flood_attack", [float(network.get("packet_count", 0)), float(data.get("packet_size", network.get("bytes_total", 0)))])
            if result: results.append(result)
            result = self._predict("network_traffic", [float(network.get(key, 0)) for key in ("packet_count", "bytes_total", "avg_interval", "throughput")])
            if result: results.append(result)

            identity_alerts = validate_identity(device_id, data.get("token", ""), data.get("mqtt_topic", ""))
            valid_token = 0.0 if any(kind == "bad_token" for kind, _ in identity_alerts) else 1.0
            valid_topic = 0.0 if any(kind == "wrong_topic" for kind, _ in identity_alerts) else 1.0
            result = self._predict("spoofing", [valid_token, valid_topic])
            if result: results.append(result)
            result = self._predict("unknown_device", [1.0 if device_id in known_devices() else 0.0])
            if result: results.append(result)
        return results


prediction_service = PredictionService()


def load_prediction_models() -> None:
    prediction_service.load_models()
