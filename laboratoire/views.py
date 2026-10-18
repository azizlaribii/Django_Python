from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import BooleanField, Case, Count, IntegerField, Q, Value, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts.models import AssociationMedecinPatient, ResultatLaboratoire

from .forms import (
    BilanPredefiniForm,
    DemandeAnnulationAdminForm,
    DemandeReaffectationForm,
    DemandeAnalyseForm,
    ParametresLaboratoireForm,
    PrelevementForm,
    RapportFilterForm,
    RejetResultatForm,
    ResultatForm,
    SupervisionFilterForm,
    TypeAnalyseForm,
)
from .models import (
    AnalyseDemandee,
    BilanPredefini,
    DemandeAnalyse,
    HistoriqueAction,
    ParametresLaboratoire,
    Prelevement,
    Resultat,
    TypeAnalyse,
)
from .permissions import (
    can_validate_results,
    can_manage_catalog,
    catalogue_requis,
    consultation_requise,
    is_lab,
    laboratory_team_user_ids,
    laboratoire_requis,
    is_lab_responsable,
    patient_requis,
)
from .services import (
    annuler_demande,
    enregistrer_action,
    enregistrer_prelevement,
    enregistrer_resultat,
    rejeter_resultat,
    valider_resultat,
)
from .reporting import export_csv, export_xlsx, get_report_data
from .pdf import build_report_pdf

User = get_user_model()


def _type_analyse_details(item):
    return {
        "code": item.code,
        "nom": item.nom,
        "description": item.description,
        "unite": item.unite,
        "valeur_reference_min": (
            str(item.valeur_reference_min) if item.valeur_reference_min is not None else None
        ),
        "valeur_reference_max": (
            str(item.valeur_reference_max) if item.valeur_reference_max is not None else None
        ),
        "seuil_critique_bas": (
            str(item.seuil_critique_bas) if item.seuil_critique_bas is not None else None
        ),
        "seuil_critique_haut": (
            str(item.seuil_critique_haut) if item.seuil_critique_haut is not None else None
        ),
        "tarif": str(item.tarif) if item.tarif is not None else None,
        "actif": item.actif,
    }


def _analyses_selectionnees(form):
    analyses = {item.pk: item for item in form.cleaned_data["analyses"]}
    for bilan in form.cleaned_data["bilans"]:
        analyses.update({
            item.pk: item
            for item in bilan.analyses.filter(actif=True)
        })
    return list(analyses.values())


def _history_label(value):
    labels = {
        "EN_ATTENTE": "En attente",
        "EN_COURS": "En cours",
        "TERMINEE": "Terminée",
        "ANNULEE": "Annulée",
        "NORMALE": "Normale",
        "HAUTE": "Haute",
        "URGENTE": "Urgente",
        "A_EFFECTUER": "À effectuer",
        "PRELEVE": "Prélevé",
        "RECU": "Reçu au laboratoire",
        "REJETE": "Rejeté",
        "ANNULE": "Annulé",
        "EN_SAISIE": "En saisie",
        "EN_ATTENTE_VALIDATION": "En attente de validation",
        "CORRIGE": "Correction à valider",
        "VALIDE": "Validé",
        "DISPONIBLE": "Résultats disponibles",
        "TRANSMIS": "Transmis au médecin",
    }
    if isinstance(value, bool):
        return "Oui" if value else "Non"
    if value is None or value == "":
        return "—"
    if isinstance(value, (list, tuple)):
        return ", ".join(f"#{item}" for item in value) or "—"
    if isinstance(value, dict):
        return ", ".join(
            f"{_history_label(key)} : {_history_label(item)}"
            for key, item in value.items()
        )
    if isinstance(value, str) and value in labels:
        return labels[value]
    return str(value)


def _code39_barres(code):
    patterns = {
        "0": "nnnwwnwnn", "1": "wnnwnnnnw", "2": "nnwwnnnnw",
        "3": "wnwwnnnnn", "4": "nnnwwnnnw", "5": "wnnwwnnnn",
        "6": "nnwwwnnnn", "7": "nnnwnnwnw", "8": "wnnwnnwnn",
        "9": "nnwwnnwnn", "A": "wnnnnwnnw", "B": "nnwnnwnnw",
        "C": "wnwnnwnnn", "D": "nnnnwwnnw", "E": "wnnnwwnnn",
        "F": "nnwnwwnnn", "G": "nnnnnwwnw", "H": "wnnnnwwnn",
        "I": "nnwnnwwnn", "J": "nnnnwwwnn", "K": "wnnnnnnww",
        "L": "nnwnnnnww", "M": "wnwnnnnwn", "N": "nnnnwnnww",
        "O": "wnnnwnnwn", "P": "nnwnwnnwn", "Q": "nnnnnnwww",
        "R": "wnnnnnwwn", "S": "nnwnnnwwn", "T": "nnnnwnwwn",
        "U": "wwnnnnnnw", "V": "nwwnnnnnw", "W": "wwwnnnnnn",
        "X": "nwnnwnnnw", "Y": "wwnnwnnnn", "Z": "nwwnwnnnn",
        "-": "nwnnnnwnw", "*": "nwnnwnwnn",
    }
    position = 10
    bars = []
    for character in f"*{code.upper()}*":
        pattern = patterns.get(character)
        if pattern is None:
            continue
        for index, width_code in enumerate(pattern):
            width = 5 if width_code == "w" else 2
            if index % 2 == 0:
                bars.append({"x": position, "width": width})
            position += width + 1
        position += 2
    return bars, position + 10


def _history_detail_sections(details):
    field_labels = {
        "patient_id": "Patient",
        "laboratoire_id": "Laboratoire destinataire",
        "ancien_laboratoire_id": "Ancien laboratoire",
        "priorite": "Priorité",
        "statut": "Statut",
        "valeurs": "Valeurs",
        "commentaire": "Commentaire",
        "motif_annulation": "Motif d’annulation",
        "analyses": "Analyses",
        "code": "Code",
        "nom": "Nom",
        "description": "Description",
        "unite": "Unité",
        "valeur_reference_min": "Référence minimale",
        "valeur_reference_max": "Référence maximale",
        "seuil_critique_bas": "Seuil critique bas",
        "seuil_critique_haut": "Seuil critique haut",
        "tarif": "Tarif",
        "actif": "Actif",
        "adresse": "Adresse",
        "telephone": "Téléphone",
        "entete_compte_rendu": "En-tête du compte rendu",
        "signature_compte_rendu": "Signature du compte rendu",
        "motifs_rejet": "Motifs de rejet",
        "delai_alerte_urgente_minutes": "Délai d’alerte des urgences (minutes)",
        "code_prelevement": "Code du prélèvement",
        "type_prelevement": "Type de prélèvement",
        "date_prelevement": "Date du prélèvement",
        "date_reception": "Date de réception",
        "date_realisation": "Date de réalisation",
        "motif_rejet": "Motif du rejet",
        "remarque": "Remarque",
        "valeur": "Valeur",
        "valeur_reference": "Valeurs de référence",
        "interpretation": "Interprétation",
        "observation": "Observation",
        "commentaire_rejet": "Commentaire de rejet",
        "nouveaux_types": "Nouvelles analyses",
        "types_annules": "Analyses annulées",
        "types_reactives": "Analyses réactivées",
        "ancien_statut": "Ancien statut",
    }
    sections = []
    remaining = dict(details) if isinstance(details, dict) else {}
    for key, title in (("avant", "Avant"), ("apres", "Après")):
        values = remaining.pop(key, None)
        if isinstance(values, dict) and values:
            sections.append({
                "title": title,
                "items": [
                    {
                        "label": field_labels.get(field, field.replace("_", " ").capitalize()),
                        "value": _history_label(value),
                    }
                    for field, value in values.items()
                ],
            })
        elif values is not None:
            sections.append({
                "title": title,
                "items": [{"label": "Valeur", "value": _history_label(values)}],
            })
    if remaining:
        sections.append({
            "title": "Détails",
            "items": [
                {
                    "label": field_labels.get(field, field.replace("_", " ").capitalize()),
                    "value": _history_label(value),
                }
                for field, value in remaining.items()
            ],
        })
    return sections


def _prepare_history_action(action):
    action_labels = {
        "DEMANDE_CREEE": "Demande créée",
        "DEMANDE_MODIFIEE": "Demande modifiée",
        "DEMANDE_ANNULEE": "Demande annulée",
        "DEMANDE_LABO_DEMO_REAFFECTEE": "Demande de démonstration attribuée au laboratoire",
        "DEMANDE_REAFFECTEE": "Demande réaffectée par l’administration",
        "DEMANDE_EN_COURS": "Demande en cours",
        "DEMANDE_TERMINEE": "Demande terminée",
        "TYPE_ANALYSE_CREE": "Analyse ajoutée au catalogue",
        "TYPE_ANALYSE_MODIFIE": "Analyse du catalogue modifiée",
        "BILAN_CREE": "Bilan prédéfini créé",
        "BILAN_MODIFIE": "Bilan prédéfini modifié",
        "PARAMETRES_LABORATOIRE_MODIFIES": "Paramètres du laboratoire modifiés",
        "PRELEVEMENT_CREE": "Prélèvement enregistré",
        "PRELEVEMENT_MODIFIE": "Prélèvement modifié",
        "RESULTAT_SAISI": "Résultat saisi",
        "RESULTAT_MODIFIE": "Résultat modifié",
        "RESULTAT_CORRIGE": "Résultat corrigé",
        "RESULTAT_VALIDE": "Résultat validé",
        "RESULTAT_REJETE": "Résultat rejeté au technicien",
        "RESULTAT_LEGACY_MODIFIE": "Résultat du laboratoire mis à jour",
        "ANALYSE_EN_COURS": "Analyse en cours",
        "ANALYSE_TERMINEE": "Analyse terminée",
    }
    object_labels = {
        "DemandeAnalyse": "Demande d’analyse",
        "TypeAnalyse": "Type d’analyse",
        "BilanPredefini": "Bilan prédéfini",
        "ParametresLaboratoire": "Paramètres du laboratoire",
        "Prelevement": "Prélèvement",
        "Resultat": "Résultat",
        "ResultatLaboratoire": "Résultat du laboratoire",
        "AnalyseDemandee": "Analyse prescrite",
    }
    action.action_label = action_labels.get(
        action.type_action, action.type_action.replace("_", " ").capitalize(),
    )
    action.object_label = object_labels.get(action.objet_concerne, action.objet_concerne)
    if action.utilisateur:
        action.actor_label = action.utilisateur.get_full_name() or action.utilisateur.username
    else:
        action.actor_label = "Système / compte supprimé"
    action.detail_sections = _history_detail_sections(action.details)


def _demande_visible(user, queryset=None):
    queryset = queryset if queryset is not None else DemandeAnalyse.objects.all()
    if user.is_laboratory:
        return queryset.filter(
            Q(laboratoire__in=laboratory_team_user_ids(user))
            | Q(laboratoire__isnull=True)
        )
    if user.is_doctor:
        return queryset.filter(medecin=user)
    if user.is_admin_user:
        return queryset
    return queryset.none()


@consultation_requise
def demande_list(request):
    demandes = _demande_visible(
        request.user,
        DemandeAnalyse.objects.select_related("patient", "medecin", "laboratoire"),
    )
    q = request.GET.get("q", "").strip()
    statut = request.GET.get("statut", "")
    priorite = request.GET.get("priorite", "")
    date_debut = parse_date(request.GET.get("date_debut", "") or "")
    date_fin = parse_date(request.GET.get("date_fin", "") or "")
    if q:
        demandes = demandes.filter(
            Q(patient__first_name__icontains=q)
            | Q(patient__last_name__icontains=q)
            | Q(patient__username__icontains=q)
            | Q(commentaire__icontains=q)
        ).distinct()
    if statut in DemandeAnalyse.Statut.values:
        demandes = demandes.filter(statut=statut)
    if priorite in DemandeAnalyse.Priorite.values:
        demandes = demandes.filter(priorite=priorite)
    if date_debut:
        demandes = demandes.filter(date_demande__date__gte=date_debut)
    if date_fin:
        demandes = demandes.filter(date_demande__date__lte=date_fin)
    delai_alerte = ParametresLaboratoire.objects.filter(pk=1).values_list(
        "delai_alerte_urgente_minutes", flat=True,
    ).first() or 60
    demandes = demandes.annotate(
        priorite_tri=Case(
            When(priorite=DemandeAnalyse.Priorite.URGENTE, then=Value(0)),
            When(priorite=DemandeAnalyse.Priorite.HAUTE, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        ),
        urgent_en_retard=Case(
            When(
                priorite=DemandeAnalyse.Priorite.URGENTE,
                statut__in=[
                    DemandeAnalyse.Statut.EN_ATTENTE,
                    DemandeAnalyse.Statut.EN_COURS,
                ],
                date_demande__lt=timezone.now() - timedelta(minutes=delai_alerte),
                then=Value(True),
            ),
            default=Value(False),
            output_field=BooleanField(),
        ),
    ).order_by("priorite_tri", "-date_demande", "-pk")
    return render(request, "laboratoire/demande_list.html", {
        "demandes": demandes,
        "q": q,
        "statut": statut,
        "priorite": priorite,
        "priorite_choices": DemandeAnalyse.Priorite.choices,
        "statut_choices": DemandeAnalyse.Statut.choices,
        "date_debut": request.GET.get("date_debut", ""),
        "date_fin": request.GET.get("date_fin", ""),
        "delai_alerte_urgente": delai_alerte,
        "can_create": request.user.is_doctor,
        "can_manage_catalog": can_manage_catalog(request.user),
        "can_validate": can_validate_results(request.user),
        "can_reject_results": can_validate_results(request.user),
        "stats": {
            "total": demandes.count(),
            "en_attente": demandes.filter(statut=DemandeAnalyse.Statut.EN_ATTENTE).count(),
            "en_cours": demandes.filter(statut=DemandeAnalyse.Statut.EN_COURS).count(),
            "terminees": demandes.filter(statut=DemandeAnalyse.Statut.TERMINEE).count(),
            "urgentes_en_retard": demandes.filter(urgent_en_retard=True).count(),
        },
    })


@catalogue_requis
def supervision(request):
    form = SupervisionFilterForm(request.GET)
    filters = form.cleaned_data if form.is_valid() else {}
    delai_alerte = ParametresLaboratoire.objects.filter(pk=1).values_list(
        "delai_alerte_urgente_minutes", flat=True,
    ).first() or 60
    demandes = DemandeAnalyse.objects.select_related(
        "patient", "medecin", "laboratoire",
    ).annotate(
        urgent_en_retard=Case(
            When(
                priorite=DemandeAnalyse.Priorite.URGENTE,
                statut__in=[
                    DemandeAnalyse.Statut.EN_ATTENTE,
                    DemandeAnalyse.Statut.EN_COURS,
                ],
                date_demande__lt=timezone.now() - timedelta(minutes=delai_alerte),
                then=Value(True),
            ),
            default=Value(False),
            output_field=BooleanField(),
        ),
        nombre_echantillons_rejetes=Count(
            "prelevements",
            filter=Q(prelevements__statut=Prelevement.Statut.REJETE),
            distinct=True,
        ),
        nombre_resultats_a_valider=Count(
            "analyses__resultats",
            filter=Q(analyses__resultats__statut__in=[
                Resultat.Statut.EN_ATTENTE_VALIDATION,
                Resultat.Statut.CORRIGE,
            ]),
            distinct=True,
        ),
    ).prefetch_related("analyses__type_analyse")
    if filters.get("date_debut"):
        demandes = demandes.filter(date_demande__date__gte=filters["date_debut"])
    if filters.get("date_fin"):
        demandes = demandes.filter(date_demande__date__lte=filters["date_fin"])
    if filters.get("statut"):
        demandes = demandes.filter(statut=filters["statut"])
    if filters.get("priorite"):
        demandes = demandes.filter(priorite=filters["priorite"])
    if filters.get("patient"):
        patient_query = filters["patient"]
        demandes = demandes.filter(
            Q(patient__username__icontains=patient_query)
            | Q(patient__first_name__icontains=patient_query)
            | Q(patient__last_name__icontains=patient_query)
        )
    if filters.get("medecin"):
        demandes = demandes.filter(medecin=filters["medecin"])
    if filters.get("laboratoire"):
        demandes = demandes.filter(laboratoire=filters["laboratoire"])
    if filters.get("bloquees"):
        demandes = demandes.filter(
            laboratoire__isnull=True,
            statut__in=[
                DemandeAnalyse.Statut.EN_ATTENTE,
                DemandeAnalyse.Statut.EN_COURS,
            ],
        )
    if filters.get("urgentes_en_retard"):
        demandes = demandes.filter(urgent_en_retard=True)
    if filters.get("echantillons_rejetes"):
        demandes = demandes.filter(nombre_echantillons_rejetes__gt=0)
    if filters.get("resultats_a_valider"):
        demandes = demandes.filter(nombre_resultats_a_valider__gt=0)

    return render(request, "laboratoire/supervision.html", {
        "form": form,
        "demandes": demandes,
        "nombre_demandes": demandes.count(),
        "nombre_bloquees": demandes.filter(
            laboratoire__isnull=True,
            statut__in=[
                DemandeAnalyse.Statut.EN_ATTENTE,
                DemandeAnalyse.Statut.EN_COURS,
            ],
        ).count(),
        "nombre_urgentes_en_retard": demandes.filter(urgent_en_retard=True).count(),
        "nombre_echantillons_rejetes": Prelevement.objects.filter(
            demande__in=demandes,
            statut=Prelevement.Statut.REJETE,
        ).count(),
        "nombre_resultats_a_valider": Resultat.objects.filter(
            analyse_demandee__demande__in=demandes,
            statut__in=(Resultat.Statut.EN_ATTENTE_VALIDATION, Resultat.Statut.CORRIGE),
        ).count(),
        "delai_alerte_urgente": delai_alerte,
        "laboratoires": User.objects.filter(
            role=User.Role.LABORATOIRE, is_active=True,
        ).order_by("username"),
        "statut_choices": DemandeAnalyse.Statut.choices,
        "priorite_choices": DemandeAnalyse.Priorite.choices,
    })


@catalogue_requis
@require_POST
def demande_reaffecter(request, pk):
    demande = get_object_or_404(DemandeAnalyse, pk=pk)
    form = DemandeReaffectationForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Sélectionnez un laboratoire actif pour réaffecter la demande.")
        return redirect("laboratoire:supervision")
    if demande.statut not in (
        DemandeAnalyse.Statut.EN_ATTENTE,
        DemandeAnalyse.Statut.EN_COURS,
    ):
        messages.error(request, "Seule une demande ouverte peut être réaffectée.")
        return redirect("laboratoire:supervision")
    nouveau_laboratoire = form.cleaned_data["laboratoire"]
    ancien_laboratoire_id = demande.laboratoire_id
    ancien_statut = demande.statut
    if ancien_laboratoire_id == nouveau_laboratoire.pk:
        messages.info(request, "Cette demande est déjà affectée à ce laboratoire.")
        return redirect("laboratoire:supervision")
    with transaction.atomic():
        demande.laboratoire = nouveau_laboratoire
        if demande.statut == DemandeAnalyse.Statut.EN_ATTENTE:
            demande.statut = DemandeAnalyse.Statut.EN_COURS
        demande.save(update_fields=["laboratoire", "statut"])
        enregistrer_action(
            utilisateur=request.user,
            action="DEMANDE_REAFFECTEE",
            objet="DemandeAnalyse",
            objet_id=demande.pk,
            details={
                "ancien_laboratoire_id": ancien_laboratoire_id,
                "laboratoire_id": nouveau_laboratoire.pk,
                "ancien_statut": ancien_statut,
                "statut": demande.statut,
            },
        )
    messages.success(request, f"La demande #{demande.pk} a été réaffectée.")
    return redirect("laboratoire:supervision")


@catalogue_requis
@require_POST
def demande_annuler_admin(request, pk):
    demande = get_object_or_404(DemandeAnalyse, pk=pk)
    form = DemandeAnnulationAdminForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Un motif est obligatoire pour annuler la demande.")
        return redirect("laboratoire:supervision")
    if demande.statut not in (
        DemandeAnalyse.Statut.EN_ATTENTE,
        DemandeAnalyse.Statut.EN_COURS,
    ):
        messages.error(request, "Seule une demande ouverte peut être annulée.")
        return redirect("laboratoire:supervision")
    ancien_statut = demande.statut
    motif = form.cleaned_data["motif"]
    with transaction.atomic():
        demande.statut = DemandeAnalyse.Statut.ANNULEE
        demande.motif_annulation = motif
        demande.save(update_fields=["statut", "motif_annulation"])
        demande.analyses.exclude(statut=AnalyseDemandee.Statut.TERMINEE).update(
            statut=AnalyseDemandee.Statut.ANNULEE,
        )
        enregistrer_action(
            utilisateur=request.user,
            action="DEMANDE_ANNULEE",
            objet="DemandeAnalyse",
            objet_id=demande.pk,
            details={
                "avant": {"statut": ancien_statut},
                "apres": {"statut": demande.statut, "motif_annulation": motif},
            },
        )
    messages.success(request, f"La demande #{demande.pk} a été annulée et tracée.")
    return redirect("laboratoire:supervision")


@catalogue_requis
def rapports(request):
    form = RapportFilterForm(request.GET)
    report = get_report_data(**form.cleaned_data) if form.is_valid() else None
    return render(request, "laboratoire/rapports.html", {
        "form": form,
        "report": report,
    })


@catalogue_requis
def rapports_export(request, format):
    if format not in ("csv", "xlsx"):
        return HttpResponse("Format d’export non pris en charge.", status=400)
    form = RapportFilterForm(request.GET)
    if not form.is_valid():
        return HttpResponse("Les filtres de période sont invalides.", status=400)
    report = get_report_data(**form.cleaned_data)
    if format == "csv":
        response = HttpResponse(
            export_csv(report), content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = 'attachment; filename="rapport-laboratoire.csv"'
        return response
    response = HttpResponse(
        export_xlsx(report),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="rapport-laboratoire.xlsx"'
    return response


@consultation_requise
def demande_create(request):
    if not request.user.is_doctor:
        messages.error(request, "Seul un médecin peut prescrire une demande d’analyses.")
        return redirect("laboratoire:demande_list")
    form = DemandeAnalyseForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            demande = form.save(commit=False)
            demande.medecin = request.user
            demande.cree_par = request.user
            demande.save()
            AnalyseDemandee.objects.bulk_create([
                AnalyseDemandee(demande=demande, type_analyse=analyse)
                for analyse in _analyses_selectionnees(form)
            ])
            enregistrer_action(
                utilisateur=request.user, action="DEMANDE_CREEE",
                objet="DemandeAnalyse", objet_id=demande.pk,
                details={
                    "patient_id": demande.patient_id,
                    "laboratoire_id": demande.laboratoire_id,
                    "priorite": demande.priorite,
                    "analyses": [a.type_analyse_id for a in demande.analyses.all()],
                },
            )
        messages.success(request, "La demande d’analyses a été créée.")
        return redirect("laboratoire:demande_detail", pk=demande.pk)
    return render(request, "laboratoire/form.html", {
        "form": form, "titre": "Nouvelle demande d’analyses",
    })


@consultation_requise
def demande_detail(request, pk):
    demande = get_object_or_404(
        DemandeAnalyse.objects.select_related("patient", "medecin", "laboratoire"),
        pk=pk,
    )
    if not _demande_visible(request.user, DemandeAnalyse.objects.filter(pk=pk)).exists():
        messages.error(request, "Vous n’avez pas accès à cette demande.")
        return redirect("laboratoire:demande_list")
    analyses = list(demande.analyses.select_related("type_analyse").prefetch_related(
        "resultats__prelevement", "resultats__saisi_par", "resultats__valide_par",
    ))
    for analyse in analyses:
        analyse.resultat_prelevement_ids = {
            resultat.prelevement_id
            for resultat in analyse.resultats.all()
            if resultat.prelevement_id is not None
        }
        analyse.resultat_sans_prelevement = any(
            resultat.prelevement_id is None for resultat in analyse.resultats.all()
        )
    return render(request, "laboratoire/demande_detail.html", {
        "demande": demande,
        "analyses": analyses,
        "prelevements": demande.prelevements.all(),
        "can_edit": request.user.is_doctor and demande.medecin_id == request.user.pk
                    and demande.statut == DemandeAnalyse.Statut.EN_ATTENTE,
        "can_work": is_lab(request.user) and demande.statut != DemandeAnalyse.Statut.ANNULEE,
        "can_validate": can_validate_results(request.user),
        "can_download_pdf": (
            (request.user.is_doctor and demande.medecin_id == request.user.pk)
            or is_lab_responsable(request.user)
        )
        and Resultat.objects.filter(
            analyse_demandee__demande=demande,
            statut=Resultat.Statut.VALIDE,
        ).exists(),
    })


@consultation_requise
def doctor_notifications(request):
    if not request.user.is_doctor:
        messages.error(request, "Ces alertes sont réservées aux médecins.")
        return redirect("laboratoire:demande_list")

    notifications = []
    resultats = Resultat.objects.filter(
        analyse_demandee__demande__medecin=request.user,
        statut=Resultat.Statut.VALIDE,
    ).select_related(
        "analyse_demandee__demande__patient", "analyse_demandee__type_analyse",
    ).order_by("-date_validation")[:300]
    for resultat in resultats:
        demande_id = resultat.analyse_demandee.demande_id
        analyse_nom = resultat.analyse_demandee.type_analyse.nom
        date_alerte = resultat.date_validation or resultat.date_saisie
        notifications.append({
            "type": "resultat",
            "titre": f"Résultat validé disponible — {analyse_nom}",
            "patient": resultat.analyse_demandee.demande.patient,
            "date": date_alerte,
            "url": reverse("laboratoire:demande_detail", args=[demande_id]),
        })
        if resultat.potentiellement_critique:
            notifications.append({
                "type": "critique",
                "titre": f"Valeur potentiellement critique — {analyse_nom}",
                "patient": resultat.analyse_demandee.demande.patient,
                "date": date_alerte,
                "url": reverse("laboratoire:demande_detail", args=[demande_id]),
            })

    rejets = Prelevement.objects.filter(
        demande__medecin=request.user,
        statut=Prelevement.Statut.REJETE,
    ).select_related("demande__patient").order_by("-date_prelevement", "-pk")[:100]
    for prelevement in rejets:
        notifications.append({
            "type": "rejet",
            "titre": f"Échantillon rejeté — {prelevement.motif_rejet}",
            "patient": prelevement.demande.patient,
            "date": prelevement.date_prelevement or prelevement.demande.date_demande,
            "url": reverse(
                "laboratoire:demande_detail", args=[prelevement.demande_id],
            ),
        })
    notifications.sort(key=lambda item: item["date"], reverse=True)
    return render(request, "laboratoire/doctor_notifications.html", {
        "notifications": notifications[:100],
    })


@consultation_requise
def doctor_patient_history(request, patient_id):
    if not request.user.is_doctor:
        messages.error(request, "Cet historique est réservé aux médecins.")
        return redirect("laboratoire:demande_list")
    association = get_object_or_404(
        AssociationMedecinPatient.objects.select_related("patient"),
        medecin=request.user, patient_id=patient_id,
    )
    patient = association.patient
    resultats = Resultat.objects.filter(
        analyse_demandee__demande__patient=patient,
        statut=Resultat.Statut.VALIDE,
    ).select_related(
        "analyse_demandee__type_analyse",
        "analyse_demandee__demande",
    ).order_by("-date_validation", "-pk")
    types_analyse = TypeAnalyse.objects.filter(
        demandes__demande__patient=patient,
        demandes__resultats__statut=Resultat.Statut.VALIDE,
    ).distinct().order_by("nom")
    selected_type = request.GET.get("analyse", "")
    if selected_type.isdigit():
        resultats = resultats.filter(analyse_demandee__type_analyse_id=selected_type)
    else:
        selected_type = ""

    chronological = list(reversed(list(resultats))) if selected_type else []
    numeric_points = []
    for resultat in chronological:
        try:
            value = Decimal(resultat.valeur.strip().replace(",", "."))
        except (InvalidOperation, TypeError, ValueError):
            continue
        numeric_points.append((resultat, value))

    chart_points = []
    if numeric_points:
        values = [float(value) for _, value in numeric_points]
        low, high = min(values), max(values)
        padding = (high - low) * 0.1 or 1
        low -= padding
        high += padding
        last_index = len(values) - 1
        for index, ((resultat, value), numeric_value) in enumerate(
            zip(numeric_points, values),
        ):
            x = 30 + (540 * index / last_index if last_index else 270)
            y = 220 - (190 * (numeric_value - low) / (high - low))
            chart_points.append({
                "x": round(x, 1),
                "y": round(y, 1),
                "date": resultat.date_validation or resultat.date_saisie,
                "value": str(value),
                "unit": resultat.unite or resultat.analyse_demandee.type_analyse.unite,
            })

    return render(request, "laboratoire/doctor_patient_history.html", {
        "patient": patient,
        "resultats": resultats,
        "legacy_resultats": ResultatLaboratoire.objects.filter(
            dossier__patient=patient,
            medecin_prescripteur=request.user,
            statut__in=("DISPONIBLE", "TRANSMIS"),
        ).select_related("laboratoire").order_by(
            "-date_realisation", "-date_prescription", "-pk",
        ),
        "types_analyse": types_analyse,
        "selected_type": selected_type,
        "chart_points": chart_points,
        "chart_polyline": " ".join(
            f'{point["x"]},{point["y"]}' for point in chart_points
        ),
    })


@consultation_requise
def doctor_report_pdf(request, pk):
    if request.user.is_doctor:
        demande_lookup = {"medecin": request.user}
    elif is_lab_responsable(request.user):
        demande_lookup = {}
    else:
        messages.error(
            request,
            "Le compte rendu est réservé au médecin prescripteur ou au biologiste responsable.",
        )
        return redirect("laboratoire:demande_list")
    demandes = DemandeAnalyse.objects.select_related("patient", "medecin", "laboratoire")
    if is_lab_responsable(request.user):
        demandes = demandes.filter(
            Q(laboratoire__in=laboratory_team_user_ids(request.user))
            | Q(laboratoire__isnull=True)
        )
    demande = get_object_or_404(demandes, pk=pk, **demande_lookup)
    resultats = Resultat.objects.filter(
        analyse_demandee__demande=demande,
        statut=Resultat.Statut.VALIDE,
    ).select_related(
        "analyse_demandee__type_analyse", "valide_par",
    ).order_by("analyse_demandee__type_analyse__nom")
    if not resultats.exists():
        messages.error(request, "Aucun résultat validé n’est disponible pour ce compte rendu.")
        return redirect("laboratoire:demande_detail", pk=pk)

    lines = [
        "COMPTE RENDU D'ANALYSES",
        "",
        f"Demande : #{demande.pk}",
        f"Patient : {demande.patient.get_full_name() or demande.patient.username}",
        f"Medecin : {demande.medecin.get_full_name() or demande.medecin.username}",
        f"Prescrite le : {demande.date_demande:%d/%m/%Y %H:%M}",
        f"Laboratoire : {demande.laboratoire.username if demande.laboratoire else 'Non attribue'}",
        "",
        "RESULTATS VALIDES",
        "",
    ]
    from .models import ParametresLaboratoire

    parametres = ParametresLaboratoire.objects.filter(pk=1).first()
    if parametres:
        if parametres.nom:
            lines.insert(1, parametres.nom)
        if parametres.adresse:
            lines.insert(2, parametres.adresse)
        if parametres.telephone:
            lines.insert(3, f"Telephone : {parametres.telephone}")
        if parametres.entete_compte_rendu:
            lines.insert(0, parametres.entete_compte_rendu)
    for resultat in resultats:
        analyse = resultat.analyse_demandee.type_analyse
        lines.extend([
            f"Analyse : {analyse.nom} ({analyse.code})",
            f"Resultat : {resultat.valeur} {resultat.unite or analyse.unite}",
            f"Valeurs de reference : {resultat.valeur_reference or 'Non renseignees'}",
            f"Valide le : {resultat.date_validation:%d/%m/%Y %H:%M}" if resultat.date_validation else "Valide",
            f"Interpretation automatique : {resultat.interpretation_automatique}",
            f"Biologiste validateur : {resultat.valide_par.get_full_name() or resultat.valide_par.username}" if resultat.valide_par else "Biologiste validateur : Responsable du laboratoire",
        ])
        if resultat.interpretation:
            lines.append(f"Interpretation : {resultat.interpretation}")
        if resultat.observation:
            lines.append(f"Observation : {resultat.observation}")
        lines.append("")
    if parametres and parametres.signature_compte_rendu:
        lines.extend(["", parametres.signature_compte_rendu])
    pdf = build_report_pdf(lines)
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="compte-rendu-demande-{demande.pk}.pdf"'
    return response


@patient_requis
def mes_resultats(request):
    date_debut = parse_date(request.GET.get("date_debut", "") or "")
    date_fin = parse_date(request.GET.get("date_fin", "") or "")
    analyse_id = request.GET.get("analyse", "")
    resultats = Resultat.objects.filter(
        analyse_demandee__demande__patient=request.user,
        statut=Resultat.Statut.VALIDE,
    ).select_related(
        "analyse_demandee__demande__medecin",
        "analyse_demandee__type_analyse",
        "prelevement",
        "valide_par",
    ).order_by("-date_validation", "-pk")
    if date_debut:
        resultats = resultats.filter(date_validation__date__gte=date_debut)
    if date_fin:
        resultats = resultats.filter(date_validation__date__lte=date_fin)

    types_analyse = TypeAnalyse.objects.filter(
        demandes__demande__patient=request.user,
        demandes__resultats__statut=Resultat.Statut.VALIDE,
    ).distinct().order_by("nom")
    if analyse_id.isdigit() and types_analyse.filter(pk=analyse_id).exists():
        resultats = resultats.filter(analyse_demandee__type_analyse_id=analyse_id)
    else:
        analyse_id = ""

    resultats_chart = list(reversed(list(resultats))) if analyse_id else []
    chart_points = []
    numeric_points = []
    for resultat in resultats_chart:
        try:
            value = Decimal(resultat.valeur.strip().replace(",", "."))
        except (InvalidOperation, TypeError, ValueError):
            continue
        numeric_points.append((resultat, value))
    if numeric_points:
        values = [float(value) for _, value in numeric_points]
        low, high = min(values), max(values)
        padding = (high - low) * 0.1 or 1
        low -= padding
        high += padding
        last_index = len(values) - 1
        for index, ((resultat, value), numeric_value) in enumerate(
            zip(numeric_points, values),
        ):
            chart_points.append({
                "x": round(30 + (540 * index / last_index if last_index else 270), 1),
                "y": round(220 - (190 * (numeric_value - low) / (high - low)), 1),
                "date": resultat.date_validation or resultat.date_saisie,
                "value": str(value),
                "unit": resultat.unite or resultat.analyse_demandee.type_analyse.unite,
            })

    resultats_legacy = ResultatLaboratoire.objects.filter(
        dossier__patient=request.user,
        statut__in=("DISPONIBLE", "TRANSMIS"),
    ).select_related("laboratoire", "medecin_prescripteur").order_by(
        "-date_realisation", "-date_prescription", "-pk",
    )
    if date_debut:
        resultats_legacy = resultats_legacy.filter(date_prescription__gte=date_debut)
    if date_fin:
        resultats_legacy = resultats_legacy.filter(date_prescription__lte=date_fin)
    if request.GET.get("type_legacy", "").strip():
        resultats_legacy = resultats_legacy.filter(
            type_analyse__icontains=request.GET["type_legacy"].strip(),
        )

    demandes = DemandeAnalyse.objects.filter(
        patient=request.user,
    ).select_related("medecin", "laboratoire").prefetch_related(
        "analyses__type_analyse",
    ).order_by("-date_demande")
    notifications = Resultat.objects.filter(
        analyse_demandee__demande__patient=request.user,
        statut=Resultat.Statut.VALIDE,
        date_validation__gte=timezone.now() - timedelta(days=7),
    ).select_related(
        "analyse_demandee__type_analyse",
        "analyse_demandee__demande",
    ).order_by("-date_validation")
    return render(request, "laboratoire/mes_resultats.html", {
        "resultats": resultats,
        "resultats_legacy": resultats_legacy,
        "resultats_count": resultats.count() + resultats_legacy.count(),
        "demandes": demandes,
        "types_analyse": types_analyse,
        "selected_analyse": analyse_id,
        "date_debut": request.GET.get("date_debut", ""),
        "date_fin": request.GET.get("date_fin", ""),
        "type_legacy": request.GET.get("type_legacy", ""),
        "notifications": notifications,
        "chart_points": chart_points,
        "chart_polyline": " ".join(
            f'{point["x"]},{point["y"]}' for point in chart_points
        ),
    })


@patient_requis
def patient_report_pdf(request, pk):
    demande = get_object_or_404(
        DemandeAnalyse.objects.select_related("patient", "medecin", "laboratoire"),
        pk=pk,
        patient=request.user,
    )
    resultats = Resultat.objects.filter(
        analyse_demandee__demande=demande,
        statut=Resultat.Statut.VALIDE,
    ).select_related("analyse_demandee__type_analyse").order_by(
        "analyse_demandee__type_analyse__nom",
    )
    if not resultats.exists():
        messages.error(request, "Aucun résultat validé n’est disponible pour ce compte rendu.")
        return redirect("laboratoire:mes_resultats")

    parametres = ParametresLaboratoire.objects.filter(pk=1).first()
    lines = [
        "COMPTE RENDU D'ANALYSES",
        f"Patient : {demande.patient.get_full_name() or demande.patient.username}",
        f"Medecin : {demande.medecin.get_full_name() or demande.medecin.username}",
        f"Prescrite le : {demande.date_demande:%d/%m/%Y %H:%M}",
        "",
        "RESULTATS VALIDES",
        "",
    ]
    if parametres:
        if parametres.nom:
            lines.insert(1, parametres.nom)
        if parametres.adresse:
            lines.insert(2, parametres.adresse)
        if parametres.telephone:
            lines.insert(3, f"Telephone : {parametres.telephone}")
        if parametres.entete_compte_rendu:
            lines.insert(0, parametres.entete_compte_rendu)
    for resultat in resultats:
        analyse = resultat.analyse_demandee.type_analyse
        lines.extend([
            f"Analyse : {analyse.nom} ({analyse.code})",
            f"Resultat : {resultat.valeur} {resultat.unite or analyse.unite}",
            f"Valeurs de reference : {resultat.valeur_reference or 'Non renseignees'}",
            f"Valide le : {resultat.date_validation:%d/%m/%Y %H:%M}" if resultat.date_validation else "Valide",
            f"Interpretation automatique : {resultat.interpretation_automatique}",
            f"Biologiste validateur : {resultat.valide_par.get_full_name() or resultat.valide_par.username}" if resultat.valide_par else "Responsable du laboratoire",
        ])
        if resultat.interpretation:
            lines.append(f"Interpretation : {resultat.interpretation}")
        if resultat.observation:
            lines.append(f"Observation : {resultat.observation}")
        lines.append("")
    if parametres and parametres.signature_compte_rendu:
        lines.extend(["", parametres.signature_compte_rendu])

    response = HttpResponse(
        build_report_pdf(lines),
        content_type="application/pdf",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="mon-compte-rendu-demande-{demande.pk}.pdf"'
    )
    return response


@patient_requis
def patient_legacy_report_pdf(request, pk):
    resultat = get_object_or_404(
        ResultatLaboratoire.objects.select_related(
            "dossier__patient", "medecin_prescripteur", "laboratoire",
        ),
        pk=pk,
        dossier__patient=request.user,
        statut__in=("DISPONIBLE", "TRANSMIS"),
    )
    parametres = ParametresLaboratoire.objects.filter(pk=1).first()
    lines = [
        "COMPTE RENDU D'ANALYSES",
        f"Patient : {resultat.dossier.patient.get_full_name() or resultat.dossier.patient.username}",
        f"Analyse : {resultat.type_analyse}",
        f"Reference : {resultat.reference}",
        f"Prescrite le : {resultat.date_prescription:%d/%m/%Y}",
    ]
    if resultat.date_realisation:
        lines.append(f"Realisee le : {resultat.date_realisation:%d/%m/%Y}")
    if resultat.laboratoire:
        lines.append(f"Laboratoire : {resultat.laboratoire.username}")
    lines.extend(["", "RESULTATS", resultat.valeurs or "Valeurs non renseignees"])
    if resultat.interpretation:
        lines.extend(["", "INTERPRETATION", resultat.interpretation])
    if parametres:
        if parametres.nom:
            lines.insert(1, parametres.nom)
        if parametres.adresse:
            lines.insert(2, parametres.adresse)
        if parametres.telephone:
            lines.insert(3, f"Telephone : {parametres.telephone}")
        if parametres.entete_compte_rendu:
            lines.insert(0, parametres.entete_compte_rendu)
        if parametres.signature_compte_rendu:
            lines.extend(["", parametres.signature_compte_rendu])

    response = HttpResponse(
        build_report_pdf(lines),
        content_type="application/pdf",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="mon-compte-rendu-{resultat.pk}.pdf"'
    )
    return response


@consultation_requise
def demande_update(request, pk):
    demande = get_object_or_404(DemandeAnalyse, pk=pk, medecin=request.user)
    if not request.user.is_doctor or demande.statut != DemandeAnalyse.Statut.EN_ATTENTE:
        messages.error(request, "Cette demande ne peut plus être modifiée.")
        return redirect("laboratoire:demande_detail", pk=pk)
    form = DemandeAnalyseForm(request.POST or None, instance=demande, user=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            before = {
                field: getattr(demande, field)
                for field in ("patient_id", "laboratoire_id", "priorite", "commentaire")
            }
            form.save()
            existing_rows = {
                item.type_analyse_id: item
                for item in demande.analyses.all()
            }
            active = {
                type_id for type_id, item in existing_rows.items()
                if item.statut != AnalyseDemandee.Statut.ANNULEE
            }
            selected_types = _analyses_selectionnees(form)
            requested = {item.pk for item in selected_types}
            removed = active - requested
            if removed:
                demande.analyses.filter(type_analyse_id__in=removed).update(
                    statut=AnalyseDemandee.Statut.ANNULEE,
                )
            revived = requested.intersection(existing_rows.keys()) - active
            if revived:
                demande.analyses.filter(type_analyse_id__in=revived).update(
                    statut=AnalyseDemandee.Statut.EN_ATTENTE,
                )
            additions = [
                AnalyseDemandee(demande=demande, type_analyse=item)
                for item in selected_types if item.pk not in existing_rows
            ]
            AnalyseDemandee.objects.bulk_create(additions)
            enregistrer_action(
                utilisateur=request.user, action="DEMANDE_MODIFIEE",
                objet="DemandeAnalyse", objet_id=demande.pk,
                details={
                    "avant": before,
                    "apres": {
                        "patient_id": demande.patient_id,
                        "laboratoire_id": demande.laboratoire_id,
                        "priorite": demande.priorite,
                        "commentaire": demande.commentaire,
                    },
                    "nouveaux_types": [a.type_analyse_id for a in additions],
                    "types_annules": sorted(removed),
                    "types_reactives": sorted(revived),
                },
            )
        messages.success(request, "La demande a été mise à jour.")
        return redirect("laboratoire:demande_detail", pk=pk)
    form.fields["analyses"].initial = demande.analyses.exclude(
        statut=AnalyseDemandee.Statut.ANNULEE,
    ).values_list("type_analyse_id", flat=True)
    return render(request, "laboratoire/form.html", {
        "form": form, "titre": f"Modifier la demande #{demande.pk}",
    })


@consultation_requise
@require_POST
def demande_cancel(request, pk):
    demande = get_object_or_404(DemandeAnalyse, pk=pk, medecin=request.user)
    try:
        annuler_demande(demande=demande, utilisateur=request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, "La demande a été annulée avec traçabilité.")
    return redirect("laboratoire:demande_detail", pk=pk)


@catalogue_requis
def type_list(request):
    return render(request, "laboratoire/type_list.html", {
        "types": TypeAnalyse.objects.all(),
    })


@catalogue_requis
def type_create(request):
    form = TypeAnalyseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            item = form.save()
            enregistrer_action(
                utilisateur=request.user, action="TYPE_ANALYSE_CREE",
                objet="TypeAnalyse", objet_id=item.pk,
                details={"apres": _type_analyse_details(item)},
            )
        messages.success(request, "Le type d’analyse a été ajouté au catalogue.")
        return redirect("laboratoire:type_list")
    return render(request, "laboratoire/form.html", {"form": form, "titre": "Ajouter une analyse"})


@catalogue_requis
def type_update(request, pk):
    item = get_object_or_404(TypeAnalyse, pk=pk)
    form = TypeAnalyseForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        before = _type_analyse_details(item)
        with transaction.atomic():
            item = form.save()
            enregistrer_action(
                utilisateur=request.user, action="TYPE_ANALYSE_MODIFIE",
                objet="TypeAnalyse", objet_id=item.pk,
                details={
                    "avant": before,
                    "apres": _type_analyse_details(item),
                },
            )
        messages.success(request, "Le type d’analyse a été mis à jour.")
        return redirect("laboratoire:type_list")
    return render(request, "laboratoire/form.html", {
        "form": form, "titre": f"Modifier {item.nom}",
    })


@catalogue_requis
def bilan_list(request):
    return render(request, "laboratoire/bilan_list.html", {
        "bilans": BilanPredefini.objects.prefetch_related("analyses"),
    })


@catalogue_requis
def bilan_create(request):
    form = BilanPredefiniForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            bilan = form.save()
            enregistrer_action(
                utilisateur=request.user, action="BILAN_CREE",
                objet="BilanPredefini", objet_id=bilan.pk,
                details={
                    "nom": bilan.nom,
                    "analyses": list(bilan.analyses.values_list("pk", flat=True)),
                    "actif": bilan.actif,
                },
            )
        messages.success(request, "Le bilan prédéfini a été créé.")
        return redirect("laboratoire:bilan_list")
    return render(request, "laboratoire/form.html", {
        "form": form, "titre": "Créer un bilan prédéfini",
    })


@catalogue_requis
def bilan_update(request, pk):
    bilan = get_object_or_404(BilanPredefini, pk=pk)
    form = BilanPredefiniForm(request.POST or None, instance=bilan)
    if request.method == "POST" and form.is_valid():
        avant = {
            "nom": bilan.nom,
            "analyses": list(bilan.analyses.values_list("pk", flat=True)),
            "actif": bilan.actif,
        }
        with transaction.atomic():
            bilan = form.save()
            enregistrer_action(
                utilisateur=request.user, action="BILAN_MODIFIE",
                objet="BilanPredefini", objet_id=bilan.pk,
                details={
                    "avant": avant,
                    "apres": {
                        "nom": bilan.nom,
                        "analyses": list(bilan.analyses.values_list("pk", flat=True)),
                        "actif": bilan.actif,
                    },
                },
            )
        messages.success(request, "Le bilan prédéfini a été mis à jour.")
        return redirect("laboratoire:bilan_list")
    return render(request, "laboratoire/form.html", {
        "form": form, "titre": f"Modifier {bilan.nom}",
    })


@catalogue_requis
def parametres_laboratoire(request):
    parametres = ParametresLaboratoire.get_solo()
    form = ParametresLaboratoireForm(
        request.POST or None,
        request.FILES or None,
        instance=parametres,
    )
    if request.method == "POST" and form.is_valid():
        avant = {
            "nom": parametres.nom,
            "adresse": parametres.adresse,
            "telephone": parametres.telephone,
            "logo": parametres.logo.name if parametres.logo else "",
            "entete_compte_rendu": parametres.entete_compte_rendu,
            "signature_compte_rendu": parametres.signature_compte_rendu,
            "motifs_rejet": parametres.motifs_rejet,
            "delai_alerte_urgente_minutes": parametres.delai_alerte_urgente_minutes,
        }
        with transaction.atomic():
            parametres = form.save()
            enregistrer_action(
                utilisateur=request.user, action="PARAMETRES_LABORATOIRE_MODIFIES",
                objet="ParametresLaboratoire", objet_id=parametres.pk,
                details={
                    "avant": avant,
                    "apres": {
                        "nom": parametres.nom,
                        "adresse": parametres.adresse,
                        "telephone": parametres.telephone,
                        "logo": parametres.logo.name if parametres.logo else "",
                        "entete_compte_rendu": parametres.entete_compte_rendu,
                        "signature_compte_rendu": parametres.signature_compte_rendu,
                        "motifs_rejet": parametres.motifs_rejet,
                        "delai_alerte_urgente_minutes": parametres.delai_alerte_urgente_minutes,
                    },
                },
            )
        messages.success(request, "Les paramètres du laboratoire ont été enregistrés.")
        return redirect("laboratoire:parametres")
    return render(request, "laboratoire/form.html", {
        "form": form, "titre": "Paramètres du laboratoire",
    })


@laboratoire_requis
def prelevement_create(request, demande_id):
    demande = get_object_or_404(_demande_visible(request.user), pk=demande_id)
    if demande.statut == DemandeAnalyse.Statut.ANNULEE:
        messages.error(request, "La demande est annulée.")
        return redirect("laboratoire:demande_detail", pk=demande.pk)
    form = PrelevementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        prelevement = form.save(commit=False)
        prelevement.demande = demande
        try:
            enregistrer_prelevement(
                prelevement=prelevement, utilisateur=request.user,
                donnees={
                    field: form.cleaned_data[field]
                    for field in form.fields
                },
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            if demande.statut == DemandeAnalyse.Statut.EN_ATTENTE:
                demande.statut = DemandeAnalyse.Statut.EN_COURS
                demande.save(update_fields=["statut"])
                enregistrer_action(
                    utilisateur=request.user, action="DEMANDE_EN_COURS",
                    objet="DemandeAnalyse", objet_id=demande.pk,
                    details={"statut": demande.statut},
                )
            messages.success(request, "Le prélèvement a été enregistré.")
            return redirect("laboratoire:demande_detail", pk=demande.pk)
    return render(request, "laboratoire/form.html", {
        "form": form, "titre": f"Prélèvement — demande #{demande.pk}",
    })


@laboratoire_requis
def prelevement_update(request, pk):
    prelevement = get_object_or_404(
        Prelevement.objects.select_related("demande").filter(
            Q(demande__laboratoire__in=laboratory_team_user_ids(request.user))
            | Q(demande__laboratoire__isnull=True)
        ),
        pk=pk,
    )
    form = PrelevementForm(request.POST or None, instance=prelevement)
    if request.method == "POST" and form.is_valid():
        try:
            enregistrer_prelevement(
                prelevement=prelevement, utilisateur=request.user,
                donnees={field: form.cleaned_data[field] for field in form.fields},
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Le prélèvement a été mis à jour.")
            return redirect("laboratoire:demande_detail", pk=prelevement.demande_id)
    return render(request, "laboratoire/form.html", {
        "form": form, "titre": f"Modifier le prélèvement {prelevement.code_prelevement}",
    })


@laboratoire_requis
def prelevement_etiquette(request, pk):
    prelevement = get_object_or_404(
        Prelevement.objects.select_related(
            "demande__patient", "demande__medecin",
        ).filter(
            Q(demande__laboratoire__in=laboratory_team_user_ids(request.user))
            | Q(demande__laboratoire__isnull=True)
        ),
        pk=pk,
    )
    bars, barcode_width = _code39_barres(prelevement.code_prelevement)
    return render(request, "laboratoire/etiquette_prelevement.html", {
        "prelevement": prelevement,
        "bars": bars,
        "barcode_width": barcode_width,
    })


@laboratoire_requis
def resultat_create(request, analyse_id):
    analyse = get_object_or_404(
        AnalyseDemandee.objects.select_related("demande", "type_analyse").filter(
            Q(demande__laboratoire__in=laboratory_team_user_ids(request.user))
            | Q(demande__laboratoire__isnull=True)
        ),
        pk=analyse_id,
    )
    if analyse.statut == AnalyseDemandee.Statut.ANNULEE:
        messages.error(request, "Cette analyse a été annulée et ne peut plus recevoir de résultat.")
        return redirect("laboratoire:demande_detail", pk=analyse.demande_id)
    prelevement_id = request.GET.get("prelevement")
    prelevement = None
    if prelevement_id:
        prelevement = get_object_or_404(
            Prelevement, pk=prelevement_id, demande=analyse.demande,
        )
    form = ResultatForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if Resultat.objects.filter(
            analyse_demandee=analyse, prelevement=prelevement,
        ).exists():
            form.add_error(None, "Un résultat existe déjà pour cette analyse et ce prélèvement.")
        else:
            analyse_type = analyse.type_analyse
            donnees = {field: form.cleaned_data[field] for field in form.fields}
            if not donnees["unite"]:
                donnees["unite"] = analyse_type.unite
            if not donnees["valeur_reference"] and (
                analyse_type.valeur_reference_min is not None
                or analyse_type.valeur_reference_max is not None
            ):
                minimum = (
                    str(analyse_type.valeur_reference_min)
                    if analyse_type.valeur_reference_min is not None else "—"
                )
                maximum = (
                    str(analyse_type.valeur_reference_max)
                    if analyse_type.valeur_reference_max is not None else "—"
                )
                donnees["valeur_reference"] = (
                    f"{minimum} – {maximum} {analyse_type.unite}"
                ).strip()
            try:
                resultat = enregistrer_resultat(
                    analyse_demandee=analyse, prelevement=prelevement,
                    utilisateur=request.user,
                    donnees=donnees,
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, "Le résultat a été saisi et envoyé pour validation.")
                return redirect("laboratoire:demande_detail", pk=analyse.demande_id)
    return render(request, "laboratoire/form.html", {
        "form": form, "titre": f"Résultat — {analyse.type_analyse.nom}",
    })


@laboratoire_requis
def resultat_update(request, pk):
    resultat = get_object_or_404(
        Resultat.objects.select_related("analyse_demandee__demande", "prelevement").filter(
            Q(analyse_demandee__demande__laboratoire__in=laboratory_team_user_ids(request.user))
            | Q(analyse_demandee__demande__laboratoire__isnull=True)
        ),
        pk=pk,
    )
    if resultat.statut in (
        Resultat.Statut.VALIDE,
        Resultat.Statut.CORRIGE,
    ) and not is_lab_responsable(request.user):
        messages.error(
            request,
            "Un résultat déjà validé ne peut être corrigé que par le biologiste responsable.",
        )
        return redirect("laboratoire:demande_detail", pk=resultat.analyse_demandee.demande_id)
    if resultat.statut == Resultat.Statut.VALIDE and not request.POST:
        messages.info(request, "Une correction de résultat validé sera soumise à une nouvelle validation.")
    form = ResultatForm(request.POST or None, instance=resultat)
    if request.method == "POST" and form.is_valid():
        try:
            enregistrer_resultat(
                analyse_demandee=resultat.analyse_demandee,
                prelevement=resultat.prelevement,
                utilisateur=request.user,
                donnees={field: form.cleaned_data[field] for field in form.fields},
                resultat=resultat,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "La modification est tracée et soumise à validation.")
            return redirect("laboratoire:demande_detail", pk=resultat.analyse_demandee.demande_id)
    return render(request, "laboratoire/form.html", {
        "form": form, "titre": f"Modifier le résultat #{resultat.pk}",
    })


@laboratoire_requis
def validation_queue(request):
    if not can_validate_results(request.user):
        messages.error(
            request,
            "La file de validation est réservée au groupe Biologiste responsable.",
        )
        return redirect("laboratoire:demande_list")
    resultats = Resultat.objects.filter(
        statut__in=[
            Resultat.Statut.EN_ATTENTE_VALIDATION,
            Resultat.Statut.CORRIGE,
        ],
    ).filter(
        Q(analyse_demandee__demande__laboratoire__in=laboratory_team_user_ids(request.user))
        | Q(analyse_demandee__demande__laboratoire__isnull=True)
    ).select_related(
        "analyse_demandee__demande__patient",
        "analyse_demandee__demande__medecin",
        "analyse_demandee__type_analyse",
        "saisi_par",
        "valide_par",
    ).order_by(
        Case(
            When(
                analyse_demandee__demande__priorite=DemandeAnalyse.Priorite.URGENTE,
                then=Value(0),
            ),
            When(
                analyse_demandee__demande__priorite=DemandeAnalyse.Priorite.HAUTE,
                then=Value(1),
            ),
            default=Value(2),
            output_field=IntegerField(),
        ),
        "date_saisie",
    )
    return render(request, "laboratoire/validation_queue.html", {
        "resultats": resultats,
        "nombre_critiques": sum(
            resultat.potentiellement_critique for resultat in resultats
        ),
    })


@laboratoire_requis
@require_POST
def resultat_reject(request, pk):
    resultat = get_object_or_404(
        Resultat.objects.select_related(
            "analyse_demandee__demande",
        ).filter(
            Q(analyse_demandee__demande__laboratoire__in=laboratory_team_user_ids(request.user))
            | Q(analyse_demandee__demande__laboratoire__isnull=True)
        ),
        pk=pk,
    )
    form = RejetResultatForm(request.POST)
    if not can_validate_results(request.user):
        messages.error(
            request,
            "Seul un biologiste responsable peut rejeter un résultat.",
        )
    elif form.is_valid():
        try:
            rejeter_resultat(
                resultat=resultat,
                utilisateur=request.user,
                commentaire=form.cleaned_data["commentaire"],
            )
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, "Le résultat a été retourné à l’opérateur avec commentaire.")
    else:
        messages.error(request, "Un commentaire valide est obligatoire pour rejeter le résultat.")
    return redirect("laboratoire:validation_queue")


@laboratoire_requis
@require_POST
def resultat_validate(request, pk):
    resultat = get_object_or_404(
        Resultat.objects.select_related("analyse_demandee__demande").filter(
            Q(analyse_demandee__demande__laboratoire__in=laboratory_team_user_ids(request.user))
            | Q(analyse_demandee__demande__laboratoire__isnull=True)
        ), pk=pk,
    )
    try:
        valider_resultat(resultat=resultat, utilisateur=request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, "Le résultat a été validé.")
    return redirect("laboratoire:demande_detail", pk=resultat.analyse_demandee.demande_id)


@consultation_requise
def historique(request):
    if not (request.user.is_laboratory or request.user.is_admin_user):
        messages.error(request, "L’historique est réservé au laboratoire et à l’administration.")
        return redirect("laboratoire:demande_list")
    actions = HistoriqueAction.objects.select_related("utilisateur")
    q = request.GET.get("q", "").strip()
    if q:
        actions = actions.filter(
            Q(objet_concerne__icontains=q) | Q(type_action__icontains=q)
            | Q(utilisateur__username__icontains=q)
            | Q(utilisateur__first_name__icontains=q)
            | Q(utilisateur__last_name__icontains=q)
        )
    actions = list(actions[:200])
    for action in actions:
        _prepare_history_action(action)
    return render(request, "laboratoire/historique.html", {
        "actions": actions,
        "action_count": len(actions),
        "q": q,
    })
