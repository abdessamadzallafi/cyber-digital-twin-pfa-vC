"""Cross-domain correlation point for SIEM, IoT and AI signals."""
from typing import Iterable


CRITICAL_SECURITY_ALERTS = {"unknown_device", "bad_token", "wrong_topic", "flood", "network_flood", "unknown_ip"}


def correlate(alerts: Iterable[tuple[str, str]], anomaly_score: float = 0.0) -> dict:
    alerts = list(alerts)
    kinds = {kind for kind, _ in alerts}
    security_incident = bool(kinds & CRITICAL_SECURITY_ALERTS)
    ai_incident = "ml_anomaly" in kinds or anomaly_score >= 0.8
    severity = "critical" if security_incident and ai_incident else "high" if (security_incident or ai_incident) else "info"
    return {
        "severity": severity,
        "open_incident": security_incident or ai_incident,
        "dispatch_drone": ai_incident or "smoke" in kinds,
        "categories": sorted(kinds),
    }
