"""Authenticated inference endpoint for integration and model validation."""
from fastapi import APIRouter

from backend.core.dependencies import CurrentUser
from backend.ml.prediction_service import load_prediction_models, prediction_service
from backend.schemas import AIPredictionRequest

router = APIRouter(prefix="/api/v1/ai", tags=["AI anomaly detection"])


@router.post("/predict")
def predict(payload: AIPredictionRequest, _: dict = CurrentUser):
    if not prediction_service.models:
        load_prediction_models()
    results = prediction_service.analyze(payload.telemetry, payload.network)
    return {"anomaly": any(item.anomalous for item in results), "predictions": [
        {"domain": item.domain, "anomalous": item.anomalous, "score": item.score, "features": item.features}
        for item in results
    ]}
