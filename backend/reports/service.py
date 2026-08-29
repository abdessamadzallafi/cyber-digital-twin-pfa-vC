"""Incident report use case."""
from backend.report_generator import generate_incident_report


class ReportService:
    def generate(self, device_id: str, anomaly_type: str) -> str:
        return generate_incident_report(device_id, anomaly_type)
