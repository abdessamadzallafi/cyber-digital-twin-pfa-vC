"""PDF report generation for a bounded SIEM time window."""
from datetime import datetime, timedelta
from pathlib import Path
from fpdf import FPDF
from sqlalchemy.orm import Session

from backend.database.models import Incident, SiemEvent
from backend.siem.risk import RiskScoreService


class SiemReportService:
    def generate(self, db: Session, window_minutes: int) -> str:
        since = datetime.utcnow() - timedelta(minutes=window_minutes)
        events = db.query(SiemEvent).filter(SiemEvent.occurred_at >= since).order_by(SiemEvent.occurred_at.desc()).all()
        incidents = db.query(Incident).filter(Incident.created_at >= since).order_by(Incident.created_at.desc()).all()
        risk = RiskScoreService().calculate(db, window_minutes)

        output_dir = Path("reports")
        output_dir.mkdir(exist_ok=True)
        filename = output_dir / f"siem_report_{datetime.utcnow():%Y%m%d_%H%M%S}.pdf"
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "Smart Port SIEM Report", new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.set_font("Helvetica", size=11)
        pdf.cell(0, 8, f"Generated UTC: {datetime.utcnow():%Y-%m-%d %H:%M:%S}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 8, f"Window: last {window_minutes} minutes | Risk: {risk['score']}/100 ({risk['level']})", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 8, f"Events: {len(events)} | Incidents: {len(incidents)}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Recent events", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=9)
        for event in events[:50]:
            line = f"[{event.severity.upper()}] {event.source}/{event.event_type} {event.device_id or '-'}: {event.message}"
            pdf.multi_cell(0, 5, line.encode("latin-1", "replace").decode("latin-1"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Incidents", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=9)
        for incident in incidents[:50]:
            pdf.multi_cell(0, 5, f"#{incident.id} [{incident.severity}] {incident.status} - {incident.device_id}: {incident.description}".encode("latin-1", "replace").decode("latin-1"), new_x="LMARGIN", new_y="NEXT")
        pdf.output(str(filename))
        return str(filename)
