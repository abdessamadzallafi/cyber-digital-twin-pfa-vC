"""Regression tests for SIEM PDF report API behavior."""
from __future__ import annotations

import glob

from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.main import app

client = TestClient(app)


def test_post_siem_reports_returns_200_with_filename():
    r = client.post("/token", data={"username": "admin", "password": settings.demo_admin_password})
    assert r.status_code == 200
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.post("/api/v1/siem/reports", headers=headers, json={"window_minutes": 60})
    assert r.status_code == 200
    body = r.json()
    assert "filename" in body
    assert isinstance(body["filename"], str)
    assert body["filename"].endswith(".pdf")


def test_post_siem_reports_creates_pdf_file():
    r = client.post("/token", data={"username": "admin", "password": settings.demo_admin_password})
    assert r.status_code == 200
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.post("/api/v1/siem/reports", headers=headers, json={"window_minutes": 60})
    assert r.status_code == 200
    filename = r.json()["filename"]
    assert filename.endswith(".pdf")
    assert filename in glob.glob("reports/*.pdf")
