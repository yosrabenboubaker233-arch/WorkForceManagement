"""
Génération du bulletin de paie au format PDF, conforme à la maquette
fournie dans le cahier des charges (v9) : bloc EMPLOYEUR/SALARIÉ,
tableau des gains, tableau des retenues, net à payer, mode de paiement.
"""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER


def _fmt(amount):
    try:
        return f"{float(amount):,.3f}".replace(",", " ").replace(".", ",") + " DT"
    except (TypeError, ValueError):
        return f"{amount} DT"


def render_payslip_pdf(payslip):
    """Construit le PDF du bulletin de paie et renvoie les octets."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PayslipTitle", parent=styles["Heading1"], alignment=TA_CENTER, fontSize=16, spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "PayslipSubtitle", parent=styles["Normal"], alignment=TA_CENTER, fontSize=10, textColor=colors.grey,
    )
    section_style = ParagraphStyle(
        "Section", parent=styles["Heading3"], fontSize=10, spaceBefore=6, spaceAfter=4, textColor=colors.HexColor("#1f2937"),
    )

    elements = [
        Paragraph("BULLETIN DE PAIE", title_style),
        Paragraph(f"Mois : {payslip['mois_annee']}", subtitle_style),
        Spacer(1, 8),
    ]

    # --- Bloc EMPLOYEUR / SALARIÉ ---
    employer_salarie_data = [
        ["EMPLOYEUR", "SALARIÉ"],
        [f"Société : {payslip['employeur']}", f"Nom : {payslip['salarie']}"],
        [f"Matricule fiscal : {payslip['matricule_fiscal']}", f"Matricule : {payslip['matricule']}"],
        [f"N° CNSS : {payslip['cnss_employeur']}", f"Fonction : {payslip['poste'] or '—'}"],
        [f"Adresse : {payslip['adresse_employeur']}", f"Département : {payslip['departement'] or '—'}"],
    ]
    t1 = Table(employer_salarie_data, colWidths=[85 * mm, 85 * mm])
    t1.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#1f2937")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(t1)
    elements.append(Spacer(1, 10))

    # --- GAINS ---
    elements.append(Paragraph("RÉMUNÉRATION — GAINS", section_style))
    gains_data = [["Élément", "Montant"]]
    gains_data.append(["Salaire de base", _fmt(payslip["salaire_base"])])
    if payslip["prime_presence"]:
        gains_data.append(["Prime de présence", _fmt(payslip["prime_presence"])])
    if payslip["indemnite_transport"]:
        gains_data.append(["Indemnité de transport", _fmt(payslip["indemnite_transport"])])
    if payslip["autres_primes"]:
        gains_data.append(["Autres primes / avantages", _fmt(payslip["autres_primes"])])
    if payslip["montant_heures_sup"]:
        gains_data.append([f"Heures supplémentaires ({payslip['heures_sup']} h)", _fmt(payslip["montant_heures_sup"])])
    gains_data.append(["SALAIRE BRUT", _fmt(payslip["salaire_brut"])])

    t2 = Table(gains_data, colWidths=[130 * mm, 40 * mm])
    t2.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#dcfce7")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#9ca3af")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(t2)
    elements.append(Spacer(1, 10))

    # --- RETENUES ---
    elements.append(Paragraph("RETENUES SALARIALES", section_style))
    retenues_data = [["Élément", "Montant"]]
    retenues_data.append(["CNSS", f"-{_fmt(payslip['cnss'])}"])
    retenues_data.append(["IRPP", f"-{_fmt(payslip['irpp'])}"])
    retenues_data.append(["CSS", f"-{_fmt(payslip['css'])}"])
    if payslip["retenue_absences"]:
        retenues_data.append(["Absences non justifiées", f"-{_fmt(payslip['retenue_absences'])}"])
    retenues_data.append(["TOTAL RETENUES", f"-{_fmt(payslip['total_retenues'])}"])

    t3 = Table(retenues_data, colWidths=[130 * mm, 40 * mm])
    t3.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fee2e2")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#9ca3af")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(t3)
    elements.append(Spacer(1, 10))

    # --- NET À PAYER ---
    net_data = [["SALAIRE NET À PAYER", _fmt(payslip["salaire_net"])]]
    t4 = Table(net_data, colWidths=[130 * mm, 40 * mm])
    t4.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 12),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(t4)
    elements.append(Spacer(1, 10))

    elements.append(Paragraph(f"Mode de paiement : {payslip['mode_paiement']}", styles["Normal"]))
    elements.append(Paragraph(f"Banque : {payslip['banque']}", styles["Normal"]))
    elements.append(Spacer(1, 14))

    disclaimer_style = ParagraphStyle(
        "Disclaimer", parent=styles["Normal"], fontSize=7, textColor=colors.grey,
    )
    elements.append(Paragraph(
        "NB : ce bulletin est généré à partir d'un moteur de paie simplifié "
        "à des fins de prototype académique (taux CNSS/CSS et barème IRPP "
        "paramétrables). Les paramètres réglementaires doivent être actualisés "
        "selon la législation en vigueur avant tout usage réel.",
        disclaimer_style,
    ))

    doc.build(elements)
    return buffer.getvalue()
