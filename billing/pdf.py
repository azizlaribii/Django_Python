from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def _nom(u):
    return u.get_full_name() or u.username


def build_facture_pdf(facture):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=f"Facture {facture.numero}",
                            leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    st = getSampleStyleSheet()
    story = [
        Paragraph(f"Facture {escape(facture.numero)}", st['Title']),
        Paragraph(f"Date : {facture.date_emission:%d/%m/%Y} - Statut : {escape(facture.get_statut_display())}", st['Normal']),
        Paragraph(f"Patient : {escape(_nom(facture.patient))}", st['Normal']),
    ]
    if facture.medecin:
        story.append(Paragraph(f"Médecin : {escape(_nom(facture.medecin))}", st['Normal']))
    story.append(Spacer(1, 0.6*cm))

    data = [['Description', 'Qté', 'Prix unitaire', 'Total']]
    for l in facture.lignes.all():
        data.append([Paragraph(escape(l.description), st['Normal']), l.quantite,
                     f"{l.prix_unitaire:.3f}", f"{l.total:.3f}"])
    t = Table(data, colWidths=[8*cm, 2*cm, 3.5*cm, 3.5*cm], repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story += [t, Spacer(1, 0.6*cm)]

    totaux = Table([
        ['Sous-total', f"{facture.sous_total:.3f}"],
        ['Remise', f"- {facture.remise:.3f}"],
        [f"TVA ({facture.tva} %)", f"{facture.montant_tva:.3f}"],
        ['Total TTC (TND)', f"{facture.total_ttc:.3f}"],
        ['Déjà payé', f"{facture.total_paye():.3f}"],
        ['Reste à payer', f"{facture.reste_a_payer():.3f}"],
    ], colWidths=[5*cm, 3.5*cm], hAlign='RIGHT')
    totaux.setStyle(TableStyle([('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                                ('FONTNAME', (0, 3), (-1, 3), 'Helvetica-Bold'),
                                ('LINEABOVE', (0, 3), (-1, 3), 1, colors.black)]))
    story.append(totaux)
    doc.build(story)
    buf.seek(0)
    return buf