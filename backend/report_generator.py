import os
from fpdf import FPDF
from datetime import datetime

def generate_incident_report(device_id, anomaly_type, position=None, score_ia=None):
    os.makedirs("reports", exist_ok=True)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(200, 10, text="Rapport d'incident - Smart Port Tanger Med", ln=True, align='C')
    pdf.ln(10)
    pdf.cell(200, 10, text=f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
    pdf.cell(200, 10, text=f"Equipement: {device_id}", ln=True)
    pdf.cell(200, 10, text=f"Type d'anomalie: {anomaly_type}", ln=True)
    if position:
        pdf.cell(200, 10, text=f"Position drone: x={position[0]:.2f}, y={position[1]:.2f}", ln=True)
    if score_ia is not None:
        pdf.cell(200, 10, text=f"Score IA: {score_ia:.2f}", ln=True)
    pdf.ln(5)
    pdf.cell(200, 10, text="Actions automatiques declenchees :", ln=True)
    pdf.cell(200, 10, text="- Alerte envoyee au dashboard", ln=True)
    pdf.cell(200, 10, text="- Mission drone creee et executee", ln=True)
    pdf.cell(200, 10, text="- Equipement inspecte", ln=True)
    filename = f"reports/incident_{device_id}_{int(datetime.now().timestamp())}.pdf"
    pdf.output(filename)
    return filename
