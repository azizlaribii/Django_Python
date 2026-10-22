import csv
import io
import zipfile
from datetime import date, datetime
from decimal import Decimal
from xml.etree import ElementTree

from django.db.models import Count, Max, Sum
from django.db.models.functions import TruncDate

from .models import DemandeAnalyse, Prelevement, Resultat


def _user_name(user):
    return user.get_full_name() or user.username


def get_report_data(date_debut=None, date_fin=None):
    demandes = DemandeAnalyse.objects.all()
    if date_debut:
        demandes = demandes.filter(date_demande__date__gte=date_debut)
    if date_fin:
        demandes = demandes.filter(date_demande__date__lte=date_fin)

    status_counts = {
        status: demandes.filter(statut=status).count()
        for status, _ in DemandeAnalyse.Statut.choices
    }
    demandes_terminees = demandes.filter(
        statut=DemandeAnalyse.Statut.TERMINEE,
    ).annotate(date_fin_traitement=Max("analyses__resultats__date_validation"))
    durees = [
        (demande.date_fin_traitement - demande.date_demande).total_seconds()
        for demande in demandes_terminees
        if demande.date_fin_traitement
        and demande.date_fin_traitement >= demande.date_demande
    ]
    duree_moyenne_minutes = (
        sum(durees) / len(durees) / 60 if durees else None
    )

    prelevements = Prelevement.objects.filter(demande__in=demandes)
    nombre_prelevements = prelevements.count()
    echantillons_rejetes = prelevements.filter(
        statut=Prelevement.Statut.REJETE,
    ).count()
    resultats_en_attente = Resultat.objects.filter(
        analyse_demandee__demande__in=demandes,
        statut__in=(Resultat.Statut.EN_ATTENTE_VALIDATION, Resultat.Statut.CORRIGE),
    ).count()

    analyses_populaires = list(
        demandes.exclude(statut=DemandeAnalyse.Statut.ANNULEE).values(
            "analyses__type_analyse__code",
            "analyses__type_analyse__nom",
        ).annotate(nombre=Count("analyses")).filter(
            analyses__type_analyse__isnull=False,
        ).order_by("-nombre", "analyses__type_analyse__nom")[:10]
    )
    par_jour = list(
        demandes.annotate(jour=TruncDate("date_demande"))
        .values("jour").annotate(nombre=Count("pk"))
        .order_by("jour")
    )
    revenus = demandes.exclude(statut=DemandeAnalyse.Statut.ANNULEE).aggregate(
        total=Sum("analyses__type_analyse__tarif"),
    )["total"] or Decimal("0")

    return {
        "demandes": demandes.select_related(
            "patient", "medecin", "laboratoire",
        ).prefetch_related(
            "analyses__type_analyse",
            "analyses__resultats",
            "prelevements",
        ),
        "total_demandes": demandes.count(),
        "statuts": [
            {
                "code": status,
                "label": label,
                "nombre": status_counts[status],
            }
            for status, label in DemandeAnalyse.Statut.choices
        ],
        "par_jour": par_jour,
        "analyses_populaires": analyses_populaires,
        "delai_moyen_minutes": duree_moyenne_minutes,
        "nombre_prelevements": nombre_prelevements,
        "echantillons_rejetes": echantillons_rejetes,
        "taux_rejet": (
            echantillons_rejetes / nombre_prelevements * 100
            if nombre_prelevements else 0
        ),
        "resultats_en_attente": resultats_en_attente,
        "chiffre_affaires": revenus,
    }


def _date_text(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return "" if value is None else str(value)


def _export_sheets(report):
    summary = [["Indicateur", "Valeur"]]
    summary.extend([
        ["Demandes sur la période", report["total_demandes"]],
        ["Délai moyen de traitement (minutes)", report["delai_moyen_minutes"] or 0],
        ["Échantillons", report["nombre_prelevements"]],
        ["Échantillons rejetés", report["echantillons_rejetes"]],
        ["Taux de rejet (%)", round(report["taux_rejet"], 2)],
        ["Résultats en attente de validation", report["resultats_en_attente"]],
        ["Chiffre d’affaires théorique (€)", report["chiffre_affaires"]],
    ])
    summary.append([])
    summary.append(["Répartition par statut", "Nombre"])
    summary.extend([[row["label"], row["nombre"]] for row in report["statuts"]])
    summary.append([])
    summary.append(["Demandes par jour", "Nombre"])
    summary.extend([
        [_date_text(row["jour"]), row["nombre"]]
        for row in report["par_jour"]
    ])

    requests = [[
        "ID", "Date", "Patient", "Médecin", "Analyses", "Priorité",
        "Statut", "Laboratoire", "Échantillons rejetés", "Résultats à valider",
        "Montant théorique (€)", "Motif d’annulation",
    ]]
    for demande in report["demandes"]:
        analyses = list(demande.analyses.all())
        analyse_names = [analyse.type_analyse.nom for analyse in analyses]
        echantillons_rejetes = sum(
            prelevement.statut == Prelevement.Statut.REJETE
            for prelevement in demande.prelevements.all()
        )
        resultats_en_attente = sum(
            resultat.statut in (
                Resultat.Statut.EN_ATTENTE_VALIDATION,
                Resultat.Statut.CORRIGE,
            )
            for analyse in analyses
            for resultat in analyse.resultats.all()
        )
        requests.append([
            demande.pk,
            _date_text(demande.date_demande),
            _user_name(demande.patient),
            _user_name(demande.medecin),
            ", ".join(analyse_names),
            demande.get_priorite_display(),
            demande.get_statut_display(),
            _user_name(demande.laboratoire) if demande.laboratoire else "",
            echantillons_rejetes,
            resultats_en_attente,
            sum(
                (analyse.type_analyse.tarif or Decimal("0")) for analyse in analyses
            ) if demande.statut != DemandeAnalyse.Statut.ANNULEE else Decimal("0"),
            demande.motif_annulation,
        ])

    top_analyses = [["Code", "Analyse", "Demandes"]]
    top_analyses.extend([
        [
            row["analyses__type_analyse__code"],
            row["analyses__type_analyse__nom"],
            row["nombre"],
        ]
        for row in report["analyses_populaires"]
    ])
    return [
        ("Synthese", summary),
        ("Demandes", requests),
        ("Analyses", top_analyses),
    ]


def export_csv(report):
    output = io.StringIO(newline="")
    writer = csv.writer(output)

    def safe_cell(value):
        if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(
            ("=", "+", "-", "@"),
        ):
            return "'" + value
        return value

    sheets = _export_sheets(report)
    writer.writerow(["Indicateur", "Valeur"])
    writer.writerows([[safe_cell(value) for value in row] for row in sheets[0][1][1:]])
    writer.writerow([])
    writer.writerow([safe_cell(value) for value in sheets[1][1][0]])
    writer.writerows([[safe_cell(value) for value in row] for row in sheets[1][1][1:]])
    writer.writerow([])
    writer.writerow([safe_cell(value) for value in sheets[2][1][0]])
    writer.writerows([[safe_cell(value) for value in row] for row in sheets[2][1][1:]])
    return "\ufeff" + output.getvalue()


def _column_name(number):
    name = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _worksheet_xml(rows):
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    root = ElementTree.Element(f"{{{namespace}}}worksheet")
    sheet_data = ElementTree.SubElement(root, f"{{{namespace}}}sheetData")
    for row_index, values in enumerate(rows, start=1):
        row_element = ElementTree.SubElement(
            sheet_data, f"{{{namespace}}}row", {"r": str(row_index)},
        )
        for column_index, value in enumerate(values, start=1):
            cell_attributes = {"r": f"{_column_name(column_index)}{row_index}"}
            if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
                cell = ElementTree.SubElement(
                    row_element, f"{{{namespace}}}c", cell_attributes,
                )
                ElementTree.SubElement(cell, f"{{{namespace}}}v").text = str(value)
                continue
            cell = ElementTree.SubElement(
                row_element, f"{{{namespace}}}c",
                {**cell_attributes, "t": "inlineStr"},
            )
            inline = ElementTree.SubElement(cell, f"{{{namespace}}}is")
            text = ElementTree.SubElement(inline, f"{{{namespace}}}t")
            text.text = "" if value is None else str(value)
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def export_xlsx(report):
    spreadsheet_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relation_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    content_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    sheets = _export_sheets(report)

    workbook = ElementTree.Element(f"{{{spreadsheet_ns}}}workbook")
    workbook_sheets = ElementTree.SubElement(workbook, f"{{{spreadsheet_ns}}}sheets")
    for index, (name, _) in enumerate(sheets, start=1):
        ElementTree.SubElement(
            workbook_sheets,
            f"{{{spreadsheet_ns}}}sheet",
            {
                "name": name,
                "sheetId": str(index),
                f"{{{relation_ns}}}id": f"rId{index}",
            },
        )

    relationships = ElementTree.Element(
        f"{{{package_rel_ns}}}Relationships",
    )
    for index, _ in enumerate(sheets, start=1):
        ElementTree.SubElement(
            relationships,
            f"{{{package_rel_ns}}}Relationship",
            {
                "Id": f"rId{index}",
                "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
                "Target": f"worksheets/sheet{index}.xml",
            },
        )

    content_types = ElementTree.Element(f"{{{content_ns}}}Types")
    ElementTree.SubElement(
        content_types, f"{{{content_ns}}}Default",
        {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"},
    )
    ElementTree.SubElement(
        content_types, f"{{{content_ns}}}Default",
        {"Extension": "xml", "ContentType": "application/xml"},
    )
    ElementTree.SubElement(
        content_types, f"{{{content_ns}}}Override",
        {
            "PartName": "/xl/workbook.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        },
    )
    for index, _ in enumerate(sheets, start=1):
        ElementTree.SubElement(
            content_types, f"{{{content_ns}}}Override",
            {
                "PartName": f"/xl/worksheets/sheet{index}.xml",
                "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
            },
        )

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            ElementTree.tostring(content_types, encoding="utf-8", xml_declaration=True),
        )
        archive.writestr(
            "_rels/.rels",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                'Target="xl/workbook.xml"/></Relationships>'
            ),
        )
        archive.writestr(
            "xl/workbook.xml",
            ElementTree.tostring(workbook, encoding="utf-8", xml_declaration=True),
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            ElementTree.tostring(relationships, encoding="utf-8", xml_declaration=True),
        )
        for index, (_, rows) in enumerate(sheets, start=1):
            archive.writestr(
                f"xl/worksheets/sheet{index}.xml", _worksheet_xml(rows),
            )
    return output.getvalue()
