# Multi-domain AI anomaly detection

The Smart Port AI uses independent, reproducible `IsolationForest` models rather
than a single smoke-only rule. Each model learns a baseline of normal behavior;
`predict == -1` is anomalous and the normalized decision-function value is
reported as a score between 0 and 1.

## Covered domains and feature vectors

| Domain | Features | Operational response |
|---|---|---|
| Temperature | Celsius | Alert; autonomous inspection for anomalous safety values. |
| Humidity | Percent | Alert and SIEM evidence. |
| Battery | Percentage | Model available through the prediction service; live drone telemetry is not yet routed to it. |
| Drone trajectory | `x`, `y`, `dx`, `dy`, speed | Model available through the prediction service; live drone telemetry is not yet routed to it. |
| Sensor failure | Time since previous observation, measurement-present flag | Detects stalled/malformed sensors. |
| Flood attack | Packet count, packet size | Detects high-rate MQTT/network behavior. |
| Spoofing | Token-valid, topic-valid flags | Complements credential/topic security controls. |
| Unknown device | Registered-device flag | Complements trusted edge inventory enforcement. |
| Network traffic | Packet count, bytes, interval, throughput | Detects unusual traffic profile. |

Existing smoke, vibration and camera models are retained as compatibility models.
The Decision Engine combines all model outputs with deterministic security and
network rules, then sends alerts, SIEM evidence, incidents and—in defined
safety/cyber domains—an autonomous inspection mission.

## Training

Run the reproducible training pipeline from the project root:

```bash
venv/bin/python train_ai_models.py
```

It produces versioned feature bundles in `backend/ml/models/advanced_*.pkl`.
Each bundle contains its Isolation Forest, ordered feature names and model version.
The API startup loads models but does not silently retrain them, so deployments
can review, test and promote model artifacts through their release process.

The bundled baseline generators are synthetic and suitable for the simulator/demo environment. No train/test split, precision, recall, F1 score, or production false-positive validation is currently produced by this pipeline.
For production, replace those normal-behavior samples with approved historical
data from `data_lake/`, keep the same feature order, validate false-positive
rates by zone/device class, and promote the resulting artifacts as a versioned
release.

## Prediction lifecycle

`backend.ml.prediction_service.PredictionService` maintains only the minimal
per-device state needed for time-gap and trajectory delta features. It is protected
by a lock and runs for applicable IoT MQTT messages; drone telemetry is currently
handled as state/evidence only. Models are loaded at FastAPI startup by
`load_prediction_models()`.

Model artifacts are optional for the demonstration: an absent, incompatible or
corrupt `.pkl` is logged and ignored per model. The API, MQTT pipeline and
deterministic security rules remain available; the system never claims that a
prediction was made when no valid model was loaded.

For authenticated integration testing and external services, `POST
/api/v1/ai/predict` accepts `telemetry` and optional `network` objects and returns
all domain predictions, model scores and extracted feature vectors. It uses the
same singleton prediction service as the Decision Engine.
