"""Prescription ko PDF banata hai (reportlab). Ye function views.py ke bahar bhi testable rehta hai."""
from io import BytesIO

from django.utils.html import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BRAND = colors.HexColor("#0f766e")


def build_prescription_pdf(prescription):
    appt = prescription.appointment
    doctor, patient = appt.doctor, appt.patient
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm, title=f"Prescription {appt.reference}")
    styles = getSampleStyleSheet()
    story = [
        Paragraph("CareSlot", styles["Title"]),
        Paragraph("Prescription", styles["Heading2"]),
        Spacer(1, 8),
        Paragraph(f"<b>Patient:</b> {escape(patient.user.get_full_name() or patient.user.email)}", styles["Normal"]),
        Paragraph(f"<b>Date:</b> {appt.appointment_date:%d %b %Y}", styles["Normal"]),
        Paragraph(
            f"<b>Doctor:</b> Dr. {escape(doctor.user.get_full_name() or doctor.user.email)}"
            + (f" ({escape(doctor.qualification)})" if doctor.qualification else ""),
            styles["Normal"],
        ),
        Spacer(1, 14),
    ]

    rows = [["Medicine", "Dosage", "Frequency", "Duration", "Instructions"]]
    for item in prescription.items.all():
        rows.append([item.medicine_name, item.dosage or "-", item.frequency or "-", item.duration or "-", item.instructions or "-"])
    table = Table(rows, colWidths=[110, 55, 75, 60, 130], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8f7")]),
    ]))
    story.append(table)
    story.append(Spacer(1, 14))

    if prescription.advice:
        story.append(Paragraph(f"<b>Advice:</b> {escape(prescription.advice)}", styles["Normal"]))
    if prescription.follow_up_days:
        story.append(Paragraph(f"<b>Follow-up:</b> after {prescription.follow_up_days} days", styles["Normal"]))
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "This is a computer-generated prescription and does not require a signature.",
        styles["Italic"]))

    doc.build(story)
    buf.seek(0)
    return buf
