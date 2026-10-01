"""One-page patient summary a person can show to the next doctor."""
from __future__ import annotations

import re
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor("#1F3A5F")
RED = colors.HexColor("#B3261E")


def _latin(s) -> str:
    """Built-in PDF fonts cannot draw Devanagari; keep the PDF in plain Latin text."""
    s = str(s or "").replace("\u20b9", "Rs ")
    s = re.sub(r"[^\x00-\x7F]+", " ", s)
    return re.sub(r"\s+", " ", s).strip() or "-"


def build_summary_pdf(path: str, profile: dict, findings: dict) -> None:
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=INK, fontSize=18, spaceAfter=2, alignment=0)
    h2 = ParagraphStyle("h2", parent=ss["Heading3"], textColor=INK, spaceBefore=8, spaceAfter=3)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.grey)

    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm)
    st = []
    st.append(Paragraph("Patient summary for doctor", h1))
    st.append(Paragraph(f"Prepared with IlaajSaathi on {datetime.now():%d %b %Y}. "
                        "Written from what the patient reported - not a diagnosis.", small))

    rows = [
        ["Name", _latin(profile.get("name") or "Not given")],
        ["Age", _latin(profile.get("age") or "Not given")],
        ["City", _latin((profile.get("city") or "Not given").title())],
        ["Health concern", _latin(", ".join(profile.get("conditions") or []) or "Not given")],
        ["Duration", _latin(profile.get("duration") or "Not given")],
        ["Procedure advised earlier", "Yes" if profile.get("surgery_advised") else "No / not mentioned"],
        ["Cost quoted elsewhere", _latin(f"Rs {profile['quoted_cost']:,}" if profile.get("quoted_cost") else "Not given")],
        ["Current medicines", _latin(", ".join(profile.get("medicines") or []) or "None mentioned")],
        ["Treatment budget", _latin(f"Rs {profile['budget']:,}" if profile.get("budget") else "Not given")],
    ]
    t = Table(rows, colWidths=[45 * mm, 130 * mm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
        ("FONT", (1, 0), (1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (0, -1), INK),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    st.append(Spacer(1, 6))
    st.append(t)

    rf = findings.get("red_flags") or {}
    st.append(Paragraph("Warning signs reported", h2))
    if rf.get("red_flags"):
        for f in rf["red_flags"]:
            st.append(Paragraph(f"<font color='#B3261E'>&#9679;</font> {_latin(f['label'])}", body))
    else:
        st.append(Paragraph("None reported.", body))
    if rf.get("urgent"):
        st.append(Paragraph(f"<b>Emergency facility needed:</b> {_latin(rf.get('facility_label'))}", body))

    st.append(Paragraph("Patient's own words", h2))
    words = _latin(profile.get("story_en") or profile.get("raw_text") or "")
    if len(words) < 8:
        words = "Patient described the problem in Hindi; key details are in the table above."
    st.append(Paragraph(words[:900], body))

    q = (findings.get("questions") or {}).get("questions") or []
    if q:
        st.append(Paragraph("Questions the patient wants answered", h2))
        for i, x in enumerate(q, 1):
            st.append(Paragraph(f"{i}. {_latin(x)}", body))

    st.append(Spacer(1, 10))
    st.append(Paragraph("IlaajSaathi helps patients find safe, affordable care. It does not diagnose or prescribe. "
                        "In an emergency call 108.", small))
    doc.build(st)
