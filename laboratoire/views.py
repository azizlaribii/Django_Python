from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import (
    BooleanField, Case, Count, IntegerField, Prefetch, Q, Value, When,
)
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from accounts.models import AssociationMedecinPatient, ResultatLaboratoire

from .forms import (
    BilanPredefiniForm,
    DemandeAnnulationForm,
    DemandeListFilterForm,
    DemandeAnalyseForm,
    DoctorHistoryFilterForm,
    HistoriqueFilterForm,
    ParametresLaboratoireForm,
    PrelevementListFilterForm,
    PrelevementResultatsForm,
    RapportFilterForm,
    RejetPrelevementForm,
    RejetResultatForm,
    ResultatsPatientFilterForm,
    ResultatForm,
    SupervisionFilterForm,
    TypeAnalyseForm,
)
from .models import (
    AnalyseDemandee,
    BilanPredefini,
    CompteRendu,
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
    demandes_visibles,
    exiger,
    is_lab,
    is_lab_responsable,
    is_admin,
    laboratory_team_user_ids,
    laboratoire_requis,
    patient_requis,
    peut,
    prelevements_visibles,
    resultats_visibles,
)
from .services import (
    annuler_demande,
    changer_statut,
    corriger_resultat,
    creer_prelevements,
    enregistrer_action,
    enregistrer_resultats_brouillon,
    enregistrer_resultat,
    envoyer_resultats,
    refaire_prelevement,
    synchroniser,
    valider_resultat,
)
from .services_resume import (
    ResumeAPIError,
    generer_resume,
    preparer_donnees,
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
        "type_echantillon": item.type_echantillon,
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
        "type_echantillon": "Type d’échantillon",
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
    visible_ids = demandes_visibles(user).values("pk")
    return queryset.filter(pk__in=visible_ids)


def _onglet_prelevement(statut):
    if statut in {
        Prelevement.Statut.A_EFFECTUER,
        Prelevement.Statut.PRELEVE,
    }:
        return "a_traiter"
    if statut == Prelevement.Statut.RECU:
        return "resultats"
    return "clotures"


def _redirect_prelevement_list(onglet, statut=None):
    query = {"onglet": onglet}
    if statut:
        query["statut"] = statut
    return redirect(
        f"{reverse('laboratoire:prelevement_list')}?{urlencode(query)}"
    )


@consultation_requise
def demande_list(request):
    exiger(request.user, "lire_demande")
    if request.user.is_laboratory:
        return redirect("laboratoire:prelevement_list")
    demandes = _demande_visible(
        request.user,
        DemandeAnalyse.objects.select_related("patient", "medecin", "laboratoire")
        .annotate(
            nombre_analyses=Count(
                "analyses",
                filter=~Q(analyses__statut=AnalyseDemandee.Statut.ANNULEE),
                distinct=True,
            ),
        )
        .prefetch_related(
            Prefetch(
                "analyses",
                queryset=AnalyseDemandee.objects.select_related(
                    "type_analyse",
                ).exclude(
                    statut=AnalyseDemandee.Statut.ANNULEE,
                ).prefetch_related(Prefetch(
                    "resultats",
                    queryset=resultats_visibles(request.user).select_related(
                        "prelevement",
                    ),
                )),
            ),
            Prefetch(
                "prelevements",
                queryset=Prelevement.objects.prefetch_related(Prefetch(
                    "analyses",
                    queryset=AnalyseDemandee.objects.select_related(
                        "type_analyse",
                    ).prefetch_related(Prefetch(
                        "resultats",
                        queryset=resultats_visibles(request.user),
                    )),
                )),
            ),
        ),
    )
    filter_form = DemandeListFilterForm(request.GET)
    filters = filter_form.cleaned_data if filter_form.is_valid() else {}
    q = filters.get("q", "")
    statut = filters.get("statut", "")
    priorite = filters.get("priorite", "")
    date_debut = filters.get("date_debut")
    date_fin = filters.get("date_fin")
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
    stats_prelevements = None
    demandes_avec_resultats_publies = set()
    if request.user.is_doctor:
        demandes_avec_resultats_publies = set(
            Resultat.objects.filter(
                analyse_demandee__demande__medecin=request.user,
                statut=Resultat.Statut.VALIDE,
            ).values_list(
                "analyse_demandee__demande_id",
                flat=True,
            ).distinct()
        )
    if request.user.is_laboratory:
        prelevements = prelevements_visibles(request.user)
        stats_prelevements = {
            "a_preparer": prelevements.filter(
                statut=Prelevement.Statut.A_EFFECTUER,
            ).count(),
            "a_receptionner": prelevements.filter(
                statut=Prelevement.Statut.PRELEVE,
            ).count(),
            "resultats_a_saisir": prelevements.filter(
                statut=Prelevement.Statut.RECU,
            ).count(),
            "termines": prelevements.filter(
                statut=Prelevement.Statut.TERMINE,
            ).count(),
            "refuses": prelevements.filter(
                statut=Prelevement.Statut.REJETE,
            ).count(),
        }
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
        "filter_form": filter_form,
        "q": q,
        "statut": statut,
        "priorite": priorite,
        "priorite_choices": DemandeAnalyse.Priorite.choices,
        "statut_choices": DemandeAnalyse.Statut.choices,
        "date_debut": request.GET.get("date_debut", ""),
        "date_fin": request.GET.get("date_fin", ""),
        "delai_alerte_urgente": delai_alerte,
        "stats_prelevements": stats_prelevements,
        "demandes_avec_resultats_publies": demandes_avec_resultats_publies,
        "ia_resume_configuree": bool(
            getattr(settings, "GOOGLE_API_KEY", "").strip()
            or getattr(settings, "GEMINI_API_KEY", "").strip()
            or getattr(settings, "ANTHROPIC_API_KEY", "").strip()
        ),
        "can_create": request.user.is_doctor,
        "can_work": peut(request.user, "changer_statut"),
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
    demandes = DemandeAnalyse.objects.select_related(
        "patient", "medecin",
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
    return render(request, "laboratoire/supervision.html", {
        "form": form,
        "demandes": demandes,
        "nombre_demandes": demandes.count(),
        "nombre_en_attente": demandes.filter(
            statut=DemandeAnalyse.Statut.EN_ATTENTE,
        ).count(),
        "nombre_en_cours": demandes.filter(
            statut=DemandeAnalyse.Statut.EN_COURS,
        ).count(),
        "nombre_terminees": demandes.filter(
            statut=DemandeAnalyse.Statut.TERMINEE,
        ).count(),
        "statut_choices": DemandeAnalyse.Statut.choices,
        "priorite_choices": DemandeAnalyse.Priorite.choices,
    })


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
    exiger(request.user, "creer_demande")
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
            creer_prelevements(demande, request.user)
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
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({
                "success": True,
                "redirect_url": reverse("laboratoire:demande_list"),
            })
        return redirect("laboratoire:demande_list")
    if request.GET.get("modal") == "1":
        return render(
            request,
            "laboratoire/demande_form_modal.html",
            {
                "form": form,
                "form_action": f"{reverse('laboratoire:demande_create')}?modal=1",
                "submit_label": "Enregistrer la demande",
            },
        )
    return render(request, "laboratoire/demande_form.html", {
        "form": form, "titre": "Nouvelle demande d’analyses",
    })


@consultation_requise
@never_cache
def demande_detail(request, pk):
    demande = get_object_or_404(
        DemandeAnalyse.objects.select_related("patient", "medecin", "laboratoire"),
        pk=pk,
    )
    exiger(request.user, "lire_demande", demande=demande)
    if request.user.is_laboratory:
        return redirect("laboratoire:prelevement_list")
    analyses = list(
        demande.analyses.select_related(
            "type_analyse", "prelevement",
        ).prefetch_related(Prefetch(
            "resultats",
            queryset=resultats_visibles(request.user).select_related(
                "prelevement", "saisi_par", "valide_par",
            ),
        ))
    )
    analyses_retirees = [
        analyse for analyse in analyses
        if analyse.statut == AnalyseDemandee.Statut.ANNULEE
    ]
    analyses = [
        analyse for analyse in analyses
        if analyse.statut != AnalyseDemandee.Statut.ANNULEE
    ]
    is_prescriber = (
        request.user.is_doctor and demande.medecin_id == request.user.pk
    )
    samples_not_started = not demande.prelevements.exclude(
        statut=Prelevement.Statut.A_EFFECTUER,
    ).exists()
    can_edit = (
        is_prescriber
        and demande.statut == DemandeAnalyse.Statut.EN_ATTENTE
        and samples_not_started
    )
    if not is_prescriber or can_edit:
        edit_block_message = ""
    elif demande.statut != DemandeAnalyse.Statut.EN_ATTENTE:
        edit_block_message = (
            "Cette demande n’est plus modifiable, car son traitement a commencé."
        )
    else:
        edit_block_message = (
            "Cette demande n’est plus modifiable, car un prélèvement a été pris en charge."
        )
    return render(request, "laboratoire/demande_detail.html", {
        "demande": demande,
        "analyses": analyses,
        "analyses_retirees": analyses_retirees,
        "prelevements": demande.prelevements.all(),
        "can_edit": can_edit,
        "edit_block_message": edit_block_message,
        "can_work": is_lab(request.user) and demande.statut != DemandeAnalyse.Statut.ANNULEE,
        "can_validate": is_lab(request.user),
        "compte_rendu": CompteRendu.objects.filter(demande=demande).first(),
        "can_manage_compte_rendu": peut(
            request.user,
            "compte_rendu",
            demande=demande,
        ),
        "has_published_results": Resultat.objects.filter(
            analyse_demandee__demande=demande,
            statut=Resultat.Statut.VALIDE,
        ).exists(),
        "can_download_pdf": (
            (request.user.is_doctor and demande.medecin_id == request.user.pk)
            or is_lab(request.user)
            or is_admin(request.user)
        )
        and Resultat.objects.filter(
            analyse_demandee__demande=demande,
            statut=Resultat.Statut.VALIDE,
        ).exists(),
        "ia_resume_configuree": bool(
            getattr(settings, "GOOGLE_API_KEY", "").strip()
            or getattr(settings, "GEMINI_API_KEY", "").strip()
            or getattr(settings, "ANTHROPIC_API_KEY", "").strip()
        ),
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


@login_required
@require_POST
def generer_resume_view(request, pk):
    demande = get_object_or_404(DemandeAnalyse, pk=pk)
    exiger(request.user, "compte_rendu", demande=demande)
    compte_rendu = CompteRendu.objects.filter(demande=demande).first()
    if compte_rendu and compte_rendu.statut == CompteRendu.Statut.APPROUVE:
        messages.info(request, "Le compte rendu est déjà approuvé et ne peut plus être modifié.")
        return redirect("laboratoire:compte_rendu", pk=demande.pk)

    lignes = preparer_donnees(demande)
    if not lignes:
        messages.error(request, "Aucun résultat publié n’est disponible pour créer le résumé.")
        return redirect("laboratoire:demande_detail", pk=demande.pk)

    try:
        generation = generer_resume(lignes)
    except ResumeAPIError as error:
        messages.error(request, str(error))
        return redirect(
            "laboratoire:compte_rendu"
            if compte_rendu
            else "laboratoire:demande_detail",
            pk=demande.pk,
        )
    with transaction.atomic():
        if compte_rendu is None:
            compte_rendu = CompteRendu(
                demande=demande,
                medecin=request.user,
            )
        compte_rendu.texte_genere = generation.texte
        compte_rendu.texte_final = generation.texte
        compte_rendu.note_medecin = ""
        compte_rendu.source = CompteRendu.Source.IA
        compte_rendu.statut = CompteRendu.Statut.BROUILLON
        compte_rendu.approuve_le = None
        compte_rendu.save()
        enregistrer_action(
            utilisateur=request.user,
            action="COMPTE_RENDU_GENERE",
            objet="CompteRendu",
            objet_id=compte_rendu.pk,
            details={
                "demande_id": demande.pk,
                "source": compte_rendu.source,
                "nombre_resultats_publies": len(lignes),
                "fournisseur_ia": generation.fournisseur,
                "modele_ia": generation.modele,
            },
        )
    messages.success(
        request,
        f"Le résumé descriptif a été généré par {generation.fournisseur}. "
        "Comparez les résultats puis relisez-le avant approbation.",
    )
    return redirect("laboratoire:compte_rendu", pk=demande.pk)


@login_required
@never_cache
def compte_rendu(request, pk):
    demande = get_object_or_404(DemandeAnalyse, pk=pk)
    exiger(request.user, "compte_rendu", demande=demande)
    compte_rendu = CompteRendu.objects.select_related(
        "demande",
        "medecin",
    ).filter(
        demande=demande,
        medecin=request.user,
    ).first()
    lignes = preparer_donnees(demande)
    texte_final = (
        compte_rendu.texte_final
        if compte_rendu
        and (
            compte_rendu.source == CompteRendu.Source.IA
            or compte_rendu.statut == CompteRendu.Statut.APPROUVE
        )
        else ""
    )
    note_medecin = compte_rendu.note_medecin if compte_rendu else ""
    if request.method == "POST":
        if compte_rendu is None:
            messages.error(request, "Générez d’abord le résumé IA.")
            return redirect("laboratoire:compte_rendu", pk=demande.pk)
        if compte_rendu.statut == CompteRendu.Statut.APPROUVE:
            messages.error(request, "Ce compte rendu est approuvé et ne peut plus être modifié.")
            return redirect("laboratoire:compte_rendu", pk=demande.pk)
        if request.POST.get("action") == "approuver":
            if compte_rendu.source != CompteRendu.Source.IA:
                messages.error(
                    request,
                    "Générez d’abord un résumé par IA avant de l’approuver.",
                )
                return redirect("laboratoire:compte_rendu", pk=demande.pk)
            if not compte_rendu.texte_final.strip():
                messages.error(request, "Le résumé IA est vide et ne peut pas être approuvé.")
                return redirect("laboratoire:compte_rendu", pk=demande.pk)
            with transaction.atomic():
                compte_rendu.statut = CompteRendu.Statut.APPROUVE
                compte_rendu.approuve_le = timezone.now()
                compte_rendu.save(update_fields=[
                    "statut", "approuve_le",
                ])
                enregistrer_action(
                    utilisateur=request.user,
                    action="COMPTE_RENDU_APPROUVE",
                    objet="CompteRendu",
                    objet_id=compte_rendu.pk,
                    details={
                        "demande_id": demande.pk,
                        "source": compte_rendu.source,
                    },
                )
            messages.success(request, "Le compte rendu a été approuvé.")
            return redirect("laboratoire:compte_rendu", pk=demande.pk)
        messages.error(request, "Cette action n’est pas disponible.")
        return redirect("laboratoire:compte_rendu", pk=demande.pk)
    return render(request, "laboratoire/compte_rendu.html", {
        "demande": demande,
        "compte_rendu": compte_rendu,
        "lignes": lignes,
        "texte_final": texte_final,
        "note_medecin": note_medecin,
        "has_outliers": any(
            ligne["statut"] in {"bas", "élevé"} for ligne in lignes
        ),
        "stats_evolution": {
            "total": len(lignes),
            "comparables": sum(
                ligne["variation_pct"] is not None for ligne in lignes
            ),
            "stable": sum(ligne["tendance"] == "stable" for ligne in lignes),
            "en_hausse": sum(
                ligne["tendance"] == "en hausse" for ligne in lignes
            ),
            "en_baisse": sum(
                ligne["tendance"] == "en baisse" for ligne in lignes
            ),
            "insuffisantes": sum(
                ligne["tendance"] == "insuffisante" for ligne in lignes
            ),
        },
        "resume_ia_configuree": bool(
            getattr(settings, "GOOGLE_API_KEY", "").strip()
            or getattr(settings, "GEMINI_API_KEY", "").strip()
            or getattr(settings, "ANTHROPIC_API_KEY", "").strip()
        ),
        "lecture_seule": (
            compte_rendu is not None
            and compte_rendu.statut == CompteRendu.Statut.APPROUVE
        ),
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
        analyse_demandee__demande__medecin=request.user,
        statut=Resultat.Statut.VALIDE,
    ).select_related(
        "analyse_demandee__type_analyse",
        "analyse_demandee__demande",
    ).order_by("-date_validation", "-pk")
    types_analyse = TypeAnalyse.objects.filter(
        demandes__demande__patient=patient,
        demandes__demande__medecin=request.user,
        demandes__resultats__statut=Resultat.Statut.VALIDE,
    ).distinct().order_by("nom")
    filter_form = DoctorHistoryFilterForm(
        request.GET, types_analyse=types_analyse,
    )
    filters = filter_form.cleaned_data if filter_form.is_valid() else {}
    selected_type = filters.get("analyse", "")
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
        "filter_form": filter_form,
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
    elif is_lab_responsable(request.user) or is_admin(request.user):
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
    exiger(request.user, "lire_demande", demande=demande)
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
            f"Validé par : {resultat.valide_par.get_full_name() or resultat.valide_par.username}" if resultat.valide_par else "Validé par le laboratoire",
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
    types_analyse = TypeAnalyse.objects.filter(
        demandes__demande__patient=request.user,
        demandes__resultats__statut=Resultat.Statut.VALIDE,
    ).distinct().order_by("nom")
    filter_form = ResultatsPatientFilterForm(
        request.GET, types_analyse=types_analyse,
    )
    filters = filter_form.cleaned_data if filter_form.is_valid() else {}
    date_debut = filters.get("date_debut")
    date_fin = filters.get("date_fin")
    analyse_id = filters.get("analyse", "")
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
    type_legacy = filters.get("type_legacy", "")
    if type_legacy:
        resultats_legacy = resultats_legacy.filter(
            type_analyse__icontains=type_legacy,
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
        "filter_form": filter_form,
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
    for resultat in resultats:
        exiger(request.user, "lire_resultat", resultat=resultat)

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
            f"Validé par : {resultat.valide_par.get_full_name() or resultat.valide_par.username}" if resultat.valide_par else "Validé par le laboratoire",
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
    exiger(request.user, "annuler_demande", demande=demande)
    if (
        demande.statut != DemandeAnalyse.Statut.EN_ATTENTE
        or demande.prelevements.exclude(statut=Prelevement.Statut.A_EFFECTUER).exists()
    ):
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
            creer_prelevements(demande, request.user)
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
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({
                "success": True,
                "redirect_url": reverse("laboratoire:demande_detail", args=[pk]),
            })
        return redirect("laboratoire:demande_detail", pk=pk)
    form.fields["analyses"].initial = demande.analyses.exclude(
        statut=AnalyseDemandee.Statut.ANNULEE,
    ).values_list("type_analyse_id", flat=True)
    if request.GET.get("modal") == "1":
        return render(request, "laboratoire/demande_form_modal.html", {
            "form": form,
            "form_action": f"{reverse('laboratoire:demande_update', args=[pk])}?modal=1",
            "submit_label": "Enregistrer les modifications",
        })
    return render(request, "laboratoire/demande_form.html", {
        "form": form, "titre": f"Modifier la demande #{demande.pk}",
    })


@consultation_requise
@require_POST
def demande_cancel(request, pk):
    demande = get_object_or_404(DemandeAnalyse, pk=pk, medecin=request.user)
    exiger(request.user, "annuler_demande", demande=demande)
    form = DemandeAnnulationForm(request.POST)
    if not form.is_valid():
        messages.error(request, form.errors["motif"][0])
        return redirect("laboratoire:demande_detail", pk=pk)
    try:
        annuler_demande(
            demande=demande,
            utilisateur=request.user,
            motif=form.cleaned_data["motif"],
        )
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, "La demande a été annulée avec traçabilité.")
    return redirect("laboratoire:demande_detail", pk=pk)


@consultation_requise
@require_POST
def demande_delete(request, pk):
    """Supprime définitivement une demande (médecin seulement, sans prélèvement)."""
    demande = get_object_or_404(DemandeAnalyse, pk=pk, medecin=request.user)
    exiger(request.user, "annuler_demande", demande=demande)

    # Vérifications de sécurité
    if demande.statut not in [DemandeAnalyse.Statut.EN_ATTENTE]:
        messages.error(request, "Seule une demande en attente peut être supprimée.")
        return redirect("laboratoire:demande_detail", pk=pk)

    if demande.prelevements.exists():
        messages.error(request, "Impossible de supprimer une demande avec des prélèvements enregistrés.")
        return redirect("laboratoire:demande_detail", pk=pk)

    # Traçabilité avant suppression
    with transaction.atomic():
        enregistrer_action(
            utilisateur=request.user,
            action="DEMANDE_SUPPRIMEE",
            objet="DemandeAnalyse",
            objet_id=demande.pk,
            details={
                "patient_id": demande.patient_id,
                "laboratoire_id": demande.laboratoire_id,
                "priorite": demande.priorite,
                "analyses": [a.type_analyse_id for a in demande.analyses.all()],
            },
        )
        demande.delete()

    messages.success(request, "La demande a été supprimée définitivement.")
    return redirect("laboratoire:demande_list")


@consultation_requise
def type_list(request):
    """Catalogue accessible en lecture pour tous, en modification pour admin/responsable."""
    archives_affichees = (
        can_manage_catalog(request.user)
        and request.GET.get("archives") == "1"
    )
    return render(request, "laboratoire/type_list.html", {
        "types": TypeAnalyse.objects.filter(actif=not archives_affichees),
        "can_manage_catalog": can_manage_catalog(request.user),
        "archives_affichees": archives_affichees,
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
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({
                "success": True,
                "redirect_url": reverse("laboratoire:type_list"),
            })
        return redirect("laboratoire:type_list")
    if request.GET.get("modal") == "1":
        return render(request, "laboratoire/catalog_form_modal.html", {
            "form": form,
            "form_action": f"{reverse('laboratoire:type_create')}?modal=1",
            "submit_label": "Ajouter l’analyse",
        })
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
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({
                "success": True,
                "redirect_url": reverse("laboratoire:type_list"),
            })
        return redirect("laboratoire:type_list")
    if request.GET.get("modal") == "1":
        return render(request, "laboratoire/catalog_form_modal.html", {
            "form": form,
            "form_action": f"{reverse('laboratoire:type_update', args=[pk])}?modal=1",
            "submit_label": "Enregistrer les modifications",
        })
    return render(request, "laboratoire/form.html", {
        "form": form, "titre": f"Modifier {item.nom}",
    })


@catalogue_requis
@require_POST
def type_toggle_active(request, pk):
    item = get_object_or_404(TypeAnalyse, pk=pk)
    before = _type_analyse_details(item)
    item.actif = not item.actif
    with transaction.atomic():
        item.save(update_fields=["actif"])
        enregistrer_action(
            utilisateur=request.user,
            action="TYPE_ANALYSE_REACTIVE" if item.actif else "TYPE_ANALYSE_ARCHIVE",
            objet="TypeAnalyse",
            objet_id=item.pk,
            details={"avant": before, "apres": _type_analyse_details(item)},
        )
    messages.success(
        request,
        "L’analyse a été réactivée." if item.actif else "L’analyse a été archivée et désactivée.",
    )
    return redirect("laboratoire:type_list")


@catalogue_requis
def bilan_list(request):
    archives_affichees = request.GET.get("archives") == "1"
    return render(request, "laboratoire/bilan_list.html", {
        "bilans": BilanPredefini.objects.filter(
            actif=not archives_affichees,
        ).prefetch_related("analyses"),
        "archives_affichees": archives_affichees,
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
                    "description": bilan.description,
                    "analyses": list(bilan.analyses.values_list("pk", flat=True)),
                    "actif": bilan.actif,
                },
            )
        messages.success(request, "Le bilan prédéfini a été créé.")
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({
                "success": True,
                "redirect_url": reverse("laboratoire:bilan_list"),
            })
        return redirect("laboratoire:bilan_list")
    if request.GET.get("modal") == "1":
        return render(request, "laboratoire/catalog_form_modal.html", {
            "form": form,
            "form_action": f"{reverse('laboratoire:bilan_create')}?modal=1",
            "submit_label": "Créer le bilan",
        })
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
            "description": bilan.description,
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
                        "description": bilan.description,
                        "analyses": list(bilan.analyses.values_list("pk", flat=True)),
                        "actif": bilan.actif,
                    },
                },
            )
        messages.success(request, "Le bilan prédéfini a été mis à jour.")
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({
                "success": True,
                "redirect_url": reverse("laboratoire:bilan_list"),
            })
        return redirect("laboratoire:bilan_list")
    if request.GET.get("modal") == "1":
        return render(request, "laboratoire/catalog_form_modal.html", {
            "form": form,
            "form_action": f"{reverse('laboratoire:bilan_update', args=[pk])}?modal=1",
            "submit_label": "Enregistrer les modifications",
        })
    return render(request, "laboratoire/form.html", {
        "form": form, "titre": f"Modifier {bilan.nom}",
    })


@catalogue_requis
@require_POST
def bilan_toggle_active(request, pk):
    bilan = get_object_or_404(BilanPredefini, pk=pk)
    avant = {
        "nom": bilan.nom,
        "description": bilan.description,
        "analyses": list(bilan.analyses.values_list("pk", flat=True)),
        "actif": bilan.actif,
    }
    bilan.actif = not bilan.actif
    with transaction.atomic():
        bilan.save(update_fields=["actif"])
        enregistrer_action(
            utilisateur=request.user,
            action="BILAN_REACTIVE" if bilan.actif else "BILAN_ARCHIVE",
            objet="BilanPredefini",
            objet_id=bilan.pk,
            details={
                "avant": avant,
                "apres": {
                    "nom": bilan.nom,
                    "description": bilan.description,
                    "analyses": list(bilan.analyses.values_list("pk", flat=True)),
                    "actif": bilan.actif,
                },
            },
        )
    messages.success(
        request,
        "Le bilan a été réactivé." if bilan.actif else "Le bilan a été archivé et désactivé.",
    )
    return redirect("laboratoire:bilan_list")


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
def prelevement_list(request):
    exiger(request.user, "lire_demande")
    scoped = prelevements_visibles(request.user).select_related(
        "demande__patient", "demande__medecin",
    ).prefetch_related("analyses__resultats")
    prelevements = scoped
    filter_form = PrelevementListFilterForm(request.GET)
    filters = filter_form.cleaned_data if filter_form.is_valid() else {}
    q = filters.get("q", "")
    statut = filters.get("statut", "")
    onglet = filters.get("onglet", "a_traiter")
    statuts_par_onglet = {
        "a_traiter": [
            Prelevement.Statut.A_EFFECTUER,
            Prelevement.Statut.PRELEVE,
        ],
        "resultats": [Prelevement.Statut.RECU],
        "clotures": [
            Prelevement.Statut.TERMINE,
            Prelevement.Statut.REJETE,
            Prelevement.Statut.ANNULE,
        ],
    }
    if onglet not in statuts_par_onglet:
        onglet = "a_traiter"
    statuts_onglet = statuts_par_onglet[onglet]
    if statut not in statuts_onglet:
        statut = ""

    if q:
        prelevements = prelevements.filter(
            Q(code_prelevement__icontains=q)
            | Q(demande__patient__first_name__icontains=q)
            | Q(demande__patient__last_name__icontains=q)
            | Q(demande__patient__username__icontains=q)
        ).distinct()
    if statut:
        prelevements = prelevements.filter(statut=statut)
    else:
        prelevements = prelevements.filter(statut__in=statuts_onglet)

    date_debut = filters.get("date_debut")
    date_fin = filters.get("date_fin")
    if date_debut:
        prelevements = prelevements.filter(date_creation__date__gte=date_debut)
    if date_fin:
        prelevements = prelevements.filter(date_creation__date__lte=date_fin)

    prelevements = prelevements.annotate(
        priorite_tri=Case(
            When(demande__priorite=DemandeAnalyse.Priorite.URGENTE, then=Value(0)),
            When(demande__priorite=DemandeAnalyse.Priorite.HAUTE, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        ),
    ).order_by("priorite_tri", "-date_creation")
    refuser_id = request.GET.get("refuser", "")
    refuser_prelevement = None
    if refuser_id.isdigit() and peut(request.user, "changer_statut"):
        refuser_prelevement = scoped.filter(
            pk=refuser_id,
            statut__in=[
                Prelevement.Statut.PRELEVE,
                Prelevement.Statut.RECU,
            ],
        ).first()
    onglets = [
        ("a_traiter", "À traiter"),
        ("resultats", "Résultats à saisir"),
        ("clotures", "Clôturés"),
    ]
    return render(request, "laboratoire/prelevement_list.html", {
        "prelevements": prelevements,
        "filter_form": filter_form,
        "q": q,
        "statut": statut,
        "onglet": onglet,
        "onglets": onglets,
        "onglet_label": dict(onglets)[onglet],
        "statut_choices": [
            choice for choice in Prelevement.Statut.choices
            if choice[0] in statuts_onglet
        ],
        "motifs_rejet": ParametresLaboratoire.get_solo().motifs_rejet,
        "can_work": peut(request.user, "changer_statut"),
        "refuser_prelevement": refuser_prelevement,
        "date_debut": request.GET.get("date_debut", ""),
        "date_fin": request.GET.get("date_fin", ""),
    })


@laboratoire_requis
@require_POST
def prelevement_etape(request, pk):
    prelevement = get_object_or_404(
        prelevements_visibles(request.user).select_related("demande"),
        pk=pk,
    )
    exiger(request.user, "changer_statut", demande=prelevement.demande)
    etape = request.POST.get("etape")
    if etape == "RECU":
        nouveau_statut = Prelevement.Statut.RECU
    elif etape == "PRELEVE" and prelevement.statut == Prelevement.Statut.A_EFFECTUER:
        nouveau_statut = Prelevement.Statut.PRELEVE
    elif etape == "RESULTATS" and prelevement.statut == Prelevement.Statut.RECU:
        return redirect("laboratoire:prelevement_resultats", pk=prelevement.pk)
    else:
        messages.error(request, "Cette étape n’est pas disponible pour ce prélèvement.")
        return _redirect_prelevement_list(
            _onglet_prelevement(prelevement.statut),
            prelevement.statut,
        )
    try:
        changer_statut(prelevement, nouveau_statut, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return _redirect_prelevement_list(
            _onglet_prelevement(prelevement.statut),
            prelevement.statut,
        )
    else:
        messages.success(
            request,
            "La réception du prélèvement est confirmée. "
            "Vous pouvez imprimer l’étiquette et saisir les résultats.",
        )
    return _redirect_prelevement_list(
        _onglet_prelevement(nouveau_statut),
        nouveau_statut,
    )


@laboratoire_requis
@require_POST
def prelevement_rejeter(request, pk):
    prelevement = get_object_or_404(
        prelevements_visibles(request.user).select_related("demande"),
        pk=pk,
    )
    exiger(request.user, "changer_statut", demande=prelevement.demande)
    form = RejetPrelevementForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choisissez un motif de refus valide.")
        return _redirect_prelevement_list(
            _onglet_prelevement(prelevement.statut),
            prelevement.statut,
        )
    try:
        changer_statut(
            prelevement,
            Prelevement.Statut.REJETE,
            request.user,
            motif=form.cleaned_data["motif"],
            remarque=form.cleaned_data["remarque"],
        )
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return _redirect_prelevement_list(
            _onglet_prelevement(prelevement.statut),
            prelevement.statut,
        )
    else:
        messages.success(request, "Le prélèvement a été refusé et tracé.")
    return _redirect_prelevement_list("clotures", Prelevement.Statut.REJETE)


@laboratoire_requis
@require_POST
def prelevement_refaire(request, pk):
    prelevement = get_object_or_404(
        prelevements_visibles(request.user).select_related("demande"),
        pk=pk,
    )
    exiger(request.user, "changer_statut", demande=prelevement.demande)
    try:
        refaire_prelevement(prelevement, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return _redirect_prelevement_list("clotures", Prelevement.Statut.REJETE)
    else:
        messages.success(request, "Un nouveau prélèvement a été créé.")
    return _redirect_prelevement_list("a_traiter", Prelevement.Statut.A_EFFECTUER)


@laboratoire_requis
def prelevement_resultats(request, pk):
    prelevement = get_object_or_404(
        prelevements_visibles(request.user).select_related("demande"),
        pk=pk,
    )
    exiger(request.user, "resultat", demande=prelevement.demande)
    if prelevement.statut != Prelevement.Statut.RECU:
        messages.error(request, "Le tube doit être reçu avant la saisie des résultats.")
        return _redirect_prelevement_list(
            _onglet_prelevement(prelevement.statut),
            prelevement.statut,
        )
    analyses = list(
        prelevement.analyses.select_related("type_analyse").exclude(
            statut=AnalyseDemandee.Statut.ANNULEE,
        ).order_by("type_analyse__nom")
    )
    a_saisir = [
        analyse for analyse in analyses
        if not analyse.resultats.filter(statut=Resultat.Statut.VALIDE).exists()
    ]
    if not analyses:
        messages.error(
            request,
            "Aucune analyse active n’est associée à ce prélèvement. "
            "La saisie est impossible ; contactez le responsable du laboratoire.",
        )
        return _redirect_prelevement_list("resultats", Prelevement.Statut.RECU)
    if not a_saisir:
        messages.info(request, "Tous les résultats de ce prélèvement sont déjà validés.")
        return _redirect_prelevement_list("clotures", Prelevement.Statut.TERMINE)
    action = request.POST.get("action") if request.method == "POST" else ""
    publier = action == "valider"
    form = PrelevementResultatsForm(
        request.POST or None,
        analyses=a_saisir,
        publier=publier,
    )
    resultat_rows = [
        {
            "analyse": analyse,
            "fields": [
                form[f"valeur_{analyse.pk}"],
                form[f"unite_{analyse.pk}"],
                form[f"valeur_reference_{analyse.pk}"],
                form[f"observation_{analyse.pk}"],
            ],
            "brouillon": analyse.resultats.filter(
                statut=Resultat.Statut.EN_SAISIE,
            ).first(),
        }
        for analyse in a_saisir
    ]
    if request.method == "POST" and form.is_valid():
        values = {
            analyse: {
                "valeur": form.cleaned_data.get(f"valeur_{analyse.pk}", ""),
                "unite": form.cleaned_data.get(f"unite_{analyse.pk}", ""),
                "valeur_reference": form.cleaned_data.get(
                    f"valeur_reference_{analyse.pk}", "",
                ),
                "observation": form.cleaned_data.get(
                    f"observation_{analyse.pk}", "",
                ),
            }
            for analyse in a_saisir
        }
        try:
            if publier:
                envoyer_resultats(
                    resultats=values,
                    utilisateur=request.user,
                    prelevement=prelevement,
                )
            else:
                enregistrer_resultats_brouillon(
                    resultats=values,
                    utilisateur=request.user,
                    prelevement=prelevement,
                )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            if publier:
                messages.success(request, "Les résultats ont été validés et publiés.")
                return _redirect_prelevement_list(
                    "clotures", Prelevement.Statut.TERMINE,
                )
            messages.success(
                request,
                "Le brouillon a été enregistré. Les résultats ne sont pas encore publiés.",
            )
            return redirect("laboratoire:prelevement_resultats", pk=prelevement.pk)
    return render(request, "laboratoire/prelevement_resultats.html", {
        "form": form,
        "prelevement": prelevement,
        "resultat_rows": resultat_rows,
    })


@laboratoire_requis
@require_POST
def prelevement_create(request, demande_id):
    demande = get_object_or_404(_demande_visible(request.user), pk=demande_id)
    exiger(request.user, "changer_statut", demande=demande)
    try:
        creer_prelevements(demande, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, "Les prélèvements nécessaires ont été créés.")
    return redirect("laboratoire:prelevement_list")


@laboratoire_requis
def prelevement_update(request, pk):
    prelevement = get_object_or_404(
        prelevements_visibles(request.user).select_related("demande"),
        pk=pk,
    )
    exiger(request.user, "changer_statut", demande=prelevement.demande)
    messages.info(
        request,
        "La modification directe des prélèvements est désactivée. "
        "Utilisez les actions correspondant à leur étape.",
    )
    return _redirect_prelevement_list(
        _onglet_prelevement(prelevement.statut),
        prelevement.statut,
    )


@laboratoire_requis
def prelevement_etiquette(request, pk):
    prelevement = get_object_or_404(
        Prelevement.objects.select_related(
            "demande__patient", "demande__medecin",
        ).filter(pk__in=prelevements_visibles(request.user).values("pk")),
        pk=pk,
    )
    exiger(request.user, "lire_demande", demande=prelevement.demande)
    if prelevement.statut not in {
        Prelevement.Statut.RECU,
        Prelevement.Statut.TERMINE,
    }:
        messages.info(
            request,
            "L’étiquette sera disponible après la confirmation de réception du prélèvement.",
        )
        return _redirect_prelevement_list(
            _onglet_prelevement(prelevement.statut),
            prelevement.statut,
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
        AnalyseDemandee.objects.select_related(
            "demande", "type_analyse", "prelevement",
        ).filter(demande__in=demandes_visibles(request.user)),
        pk=analyse_id,
    )
    exiger(request.user, "resultat", demande=analyse.demande)
    if analyse.statut == AnalyseDemandee.Statut.ANNULEE:
        messages.error(request, "Cette analyse a été annulée et ne peut plus recevoir de résultat.")
        return redirect("laboratoire:demande_detail", pk=analyse.demande_id)
    prelevement = analyse.prelevement
    if not prelevement or prelevement.statut != Prelevement.Statut.RECU:
        messages.error(request, "Le prélèvement doit être reçu avant la saisie du résultat.")
        return redirect("laboratoire:demande_detail", pk=analyse.demande_id)
    analyse_type = analyse.type_analyse
    initial_data = {}
    if analyse_type.unite:
        initial_data["unite"] = analyse_type.unite
    result = Resultat.objects.filter(analyse_demandee=analyse).first()
    if result and result.statut == Resultat.Statut.VALIDE:
        messages.info(request, "Ce résultat existe déjà ; utilisez la correction tracée.")
        return redirect("laboratoire:resultat_update", pk=result.pk)
    instance = result or Resultat(
        analyse_demandee=analyse,
        prelevement=prelevement,
        saisi_par=request.user,
    )
    form = ResultatForm(request.POST or None, instance=instance, initial=initial_data)
    if request.method == "POST" and form.is_valid():
        donnees = {
            key: form.cleaned_data[key]
            for key in ("valeur", "unite", "valeur_reference", "interpretation", "observation")
        }
        try:
            enregistrer_resultats_brouillon(
                resultats={analyse: donnees},
                utilisateur=request.user,
                prelevement=prelevement,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(
                request,
                "Le brouillon a été enregistré. Il reste à valider avant publication.",
            )
            return redirect(
                "laboratoire:prelevement_resultats",
                pk=prelevement.pk,
            )
    return render(request, "laboratoire/form.html", {
        "form": form, "titre": f"Résultat — {analyse.type_analyse.nom}",
    })


@laboratoire_requis
def resultat_update(request, pk):
    resultat = get_object_or_404(
        resultats_visibles(request.user).select_related(
            "analyse_demandee__demande",
            "analyse_demandee__type_analyse",
            "analyse_demandee__prelevement",
            "prelevement",
        ),
        pk=pk,
    )
    exiger(
        request.user,
        "resultat",
        demande=resultat.analyse_demandee.demande,
    )
    form = ResultatForm(request.POST or None, instance=resultat)
    if request.method == "POST" and form.is_valid():
        donnees = {
            key: form.cleaned_data[key]
            for key in ("valeur", "unite", "valeur_reference", "interpretation", "observation")
        }
        try:
            if resultat.statut == Resultat.Statut.EN_SAISIE:
                enregistrer_resultats_brouillon(
                    resultats={resultat.analyse_demandee: donnees},
                    utilisateur=request.user,
                    prelevement=resultat.prelevement,
                )
            else:
                corriger_resultat(
                    resultat=resultat,
                    utilisateur=request.user,
                    donnees=donnees,
                    motif=form.cleaned_data["motif_correction"],
                )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            if resultat.statut == Resultat.Statut.EN_SAISIE:
                messages.success(request, "Le brouillon du résultat a été mis à jour.")
                return redirect(
                    "laboratoire:prelevement_resultats",
                    pk=resultat.prelevement_id,
                )
            messages.success(request, "La correction est enregistrée, versionnée et tracée.")
            return redirect("laboratoire:demande_detail", pk=resultat.analyse_demandee.demande_id)
    return render(request, "laboratoire/form.html", {
        "form": form, "titre": f"Modifier le résultat #{resultat.pk}",
    })


@laboratoire_requis
def validation_queue(request):
    exiger(request.user, "lire_demande")
    messages.info(request, "La validation des résultats est effectuée directement par le laboratoire.")
    return redirect("laboratoire:prelevement_list")


@laboratoire_requis
@require_POST
def resultat_reject(request, pk):
    exiger(request.user, "resultat")
    messages.info(request, "Un résultat ne se rejette pas : utilisez la correction tracée si nécessaire.")
    return redirect("laboratoire:prelevement_list")


@laboratoire_requis
@require_POST
def resultat_validate(request, pk):
    resultat = get_object_or_404(
        resultats_visibles(request.user).select_related(
            "analyse_demandee__demande",
        ),
        pk=pk,
    )
    exiger(request.user, "resultat", demande=resultat.analyse_demandee.demande)
    if resultat.statut != Resultat.Statut.EN_SAISIE:
        messages.info(request, "Ce résultat est déjà validé.")
        return redirect("laboratoire:demande_detail", pk=resultat.analyse_demandee.demande_id)
    try:
        valider_resultat(resultat=resultat, utilisateur=request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, "Le résultat a été validé et publié.")
    return redirect("laboratoire:demande_detail", pk=resultat.analyse_demandee.demande_id)


@consultation_requise
def historique(request):
    exiger(request.user, "historique")
    actions = HistoriqueAction.objects.select_related("utilisateur")
    filter_form = HistoriqueFilterForm(request.GET)
    filters = filter_form.cleaned_data if filter_form.is_valid() else {}
    q = filters.get("q", "")
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
        "filter_form": filter_form,
        "action_count": len(actions),
        "q": q,
    })
