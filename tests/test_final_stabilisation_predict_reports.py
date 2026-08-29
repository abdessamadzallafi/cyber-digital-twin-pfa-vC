"""Focused regression tests for final stabilisation fixes."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.main import app
from backend.ml.prediction_service import PredictionService

client = TestClient(app)


def test_ai_predict_returns_json_serializable_values():
    """BUG1: /api/v1/ai/predict must return HTTP 200 with native Python values."""
    # Authenticate
    r = client.post("/token", data={"username": "admin", "password": settings.demo_admin_password})
    assert r.status_code == 200
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    fake_results = [
        MagicMock(domain="temperature", anomalous=True, score=0.8, features={"value": 250.0}),
    ]
    with patch("backend.api.ai.prediction_service.analyze", return_value=fake_results):
        r = client.post(
            "/api/v1/ai/predict",
            headers=headers,
            json={
                "telemetry": {"device_id": "temp_01", "type": "temperature", "value": 250},
                "network": {"packet_count": 10, "bytes_total": 1200, "avg_interval": 0.1, "throughput": 1.2},
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["anomaly"] is True
    assert isinstance(body["anomaly"], bool)
    assert isinstance(body["predictions"], list)
    for item in body["predictions"]:
        assert isinstance(item["anomalous"], bool)
        assert isinstance(item["score"], float)


def test_siem_reports_get_returns_200():
    """BUG2: GET /api/v1/siem/reports must return HTTP 200."""
    r = client.post("/token", data={"username": "admin", "password": settings.demo_admin_password})
    assert r.status_code == 200
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/api/v1/siem/reports", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
