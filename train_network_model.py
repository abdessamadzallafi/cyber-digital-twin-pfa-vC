import numpy as np
from sklearn.ensemble import IsolationForest
import joblib
import os

os.makedirs("backend/ml/models", exist_ok=True)

# Données normales : faible trafic IoT
np.random.seed(42)
samples = 2000
normal_data = np.column_stack([
    np.random.poisson(5, samples),          # packet_count
    np.random.exponential(500, samples),    # bytes_total
    np.random.exponential(2, samples),      # avg_interval
    np.random.exponential(100, samples)     # throughput
])

model = IsolationForest(contamination=0.05, random_state=42)
model.fit(normal_data)
joblib.dump(model, "backend/ml/models/network_model.pkl")
print("Modèle réseau sauvegardé.")