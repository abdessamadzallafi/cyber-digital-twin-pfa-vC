import numpy as np
from sklearn.ensemble import IsolationForest
import joblib
import os

# Créer le dossier de destination si absent
os.makedirs("backend/ml/models", exist_ok=True)

# Génération de données d'entraînement normales
np.random.seed(42)
samples = 2000

models = {
    "temperature": np.random.uniform(15, 35, samples).reshape(-1, 1),
    "humidity":    np.random.uniform(30, 70, samples).reshape(-1, 1),
    "vibration":   np.random.uniform(0, 2, samples).reshape(-1, 1),
    "smoke":       np.random.uniform(0, 5, samples).reshape(-1, 1),
    "camera":      np.random.randint(0, 11, samples).reshape(-1, 1)
}

for name, X in models.items():
    model = IsolationForest(contamination=0.05, random_state=42)
    model.fit(X)
    path = f"backend/ml/models/{name}_model.pkl"
    joblib.dump(model, path)
    print(f"Modèle {name} sauvegardé -> {path}")

print("Entraînement terminé.")