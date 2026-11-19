"""Incident report generation for SecurIoT-Port."""
from datetime import datetime
import os

from fpdf import FPDF


def generate_incident_report(
    device_id,
    anomaly_type,
    score_ia=None,
):
    """Generate a PDF report summarizing a detected incident."""

    os.makedirs("reports", exist_ok=True)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)

    pdf.cell(
        200,
        10,
        text="Rapport d'incident - SecurIoT-Port",
        ln=True,
        align="C",
    )
    pdf.ln(10)

    pdf.cell(
        200,
        10,
        text=f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ln=True,
    )
    pdf.cell(
        200,
        10,
        text=f"Equipement: {device_id}",
        ln=True,
    )
    pdf.cell(
        200,
        10,
        text=f"Type d'anomalie: {anomaly_type}",
        ln=True,
    )

    if score_ia is not None:
        pdf.cell(
            200,
            10,
            text=f"Score IA: {score_ia:.2f}",
            ln=True,
        )

    pdf.ln(5)
    pdf.cell(
        200,
        10,
        text="Actions de supervision et de sécurité :",
        ln=True,
    )
    pdf.cell(
        200,
        10,
        text="- Alerte transmise au dashboard",
        ln=True,
    )
    pdf.cell(
        200,
        10,
        text="- Detection et correlation de l'incident",
        ln=True,
    )
    pdf.cell(
        200,
        10,
        text="- Journalisation dans le SIEM",
        ln=True,
    )

    filename = (
        f"reports/incident_{device_id}_"
        f"{int(datetime.now().timestamp())}.pdf"
    )
    pdf.output(filename)

    return filename
