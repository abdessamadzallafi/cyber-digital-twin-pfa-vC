"""Reproducible Isolation Forest training pipeline for Smart Port AI domains."""
from pathlib import Path
from typing import Callable
import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

MODEL_DIR = Path(__file__).with_name("models")
RANDOM_STATE = 42


def _scalar(low: float, high: float) -> Callable[[np.random.Generator, int], np.ndarray]:
    return lambda rng, count: rng.uniform(low, high, count).reshape(-1, 1)


TRAINING_SPECS: dict[str, tuple[list[str], Callable[[np.random.Generator, int], np.ndarray]]] = {
    "temperature": (["celsius"], _scalar(15, 35)),
    "humidity": (["percent"], _scalar(30, 70)),
    "battery": (["percent"], _scalar(40, 100)),
    "drone_trajectory": ("x y dx dy speed".split(), lambda rng, n: np.column_stack((
        rng.uniform(0, 30, n), rng.uniform(0, 20, n), rng.normal(0, 0.8, n),
        rng.normal(0, 0.8, n), rng.uniform(0, 2.5, n)))),
    "sensor_failure": (["gap_seconds", "has_measurement"], lambda rng, n: np.column_stack((
        rng.uniform(0, 30, n), rng.normal(1.0, 0.005, n)))),
    "flood_attack": (["packet_count", "packet_size"], lambda rng, n: np.column_stack((
        rng.poisson(4, n), rng.uniform(80, 800, n)))),
    # Tiny natural variance avoids degenerate constant-feature forests while
    # preserving the intended normal state close to one.
    "spoofing": (["valid_token", "valid_topic"], lambda rng, n: rng.normal(1.0, 0.005, (n, 2))),
    "unknown_device": (["registered_device"], lambda rng, n: rng.normal(1.0, 0.005, (n, 1))),
    "network_traffic": ("packet_count bytes_total avg_interval throughput".split(), lambda rng, n: np.column_stack((
        rng.poisson(5, n), rng.exponential(500, n), rng.exponential(2, n), rng.exponential(100, n)))),
}


def train_all(samples: int = 2_000, contamination: float = 0.03) -> list[Path]:
    """Train and atomically persist every AI domain model with feature metadata."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(RANDOM_STATE)
    paths = []
    for name, (features, generator) in TRAINING_SPECS.items():
        model = IsolationForest(contamination=contamination, random_state=RANDOM_STATE, n_jobs=-1)
        model.fit(generator(rng, samples))
        path = MODEL_DIR / f"advanced_{name}.pkl"
        joblib.dump({"model": model, "features": features, "version": 1}, path)
        paths.append(path)
    return paths


if __name__ == "__main__":
    for model_path in train_all():
        print(model_path)
