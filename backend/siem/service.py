"""SIEM application service; it composes identity and correlation policies."""
from backend.security.engine import check_security
from smart_port.analytics.correlation_engine import correlate


class SiemService:
    def evaluate(self, device_id: str, token: str, topic: str, anomaly_score: float = 0.0) -> dict:
        alerts = check_security(device_id, token, topic)
        return {"alerts": alerts, "correlation": correlate(alerts, anomaly_score)}
