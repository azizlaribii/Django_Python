from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts.models import ResultatLaboratoire

from .forms import DemandeAnalyseForm, PrelevementForm, ResultatForm, TypeAnalyseForm
from .models import (
    AnalyseDemandee,
    DemandeAnalyse,
    HistoriqueAction,
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
    patient_requis,
)
from .services import (
    annuler_demande,
    enregistrer_action,
    enregistrer_prelevement,
    enregistrer_resultat,
    valider_resultat,
)


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
        "tarif": str(item.tarif) if item.tarif is not None else None,
        "actif": item.actif,
    }


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


def _history_detail_sections(details):
    field_labels = {
        "patient_id": "Patient",
        "laboratoire_id": "Laboratoire destinataire",
        "ancien_laboratoire_id": "Ancien laboratoire",
        "priorite": "Priorité",
        "statut": "Statut",
        "valeurs": "Valeurs",
        "commentaire": "Commentaire",
        "analyses": "Analyses",
        "code": "Code",
        "nom": "Nom",
        "description": "Description",
        "unite": "Unité",
        "valeur_reference_min": "Référence minimale",
        "valeur_reference_max": "Référence maximale",
        "tarif": "Tarif",
        "actif": "Actif",
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
        "nouveaux_types": "Nouvelles analyses",
        "types_annules": "Analyses annulées",
        "types_reactives": "Analyses réactivées",
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
        "DEMANDE_EN_COURS": "Demande en cours",
        "DEMANDE_TERMINEE": "Demande terminée",
        "TYPE_ANALYSE_CREE": "Analyse ajoutée au catalogue",
        "TYPE_ANALYSE_MODIFIE": "Analyse du catalogue modifiée",
        "PRELEVEMENT_CREE": "Prélèvement enregistré",
        "PRELEVEMENT_MODIFIE": "Prélèvement modifié",
        "RESULTAT_SAISI": "Résultat saisi",
        "RESULTAT_MODIFIE": "Résultat modifié",
        "RESULTAT_CORRIGE": "Résultat corrigé",
        "RESULTAT_VALIDE": "Résultat validé",
        "RESULTAT_LEGACY_MODIFIE": "Résultat du laboratoire mis à jour",
        "ANALYSE_EN_COURS": "Analyse en cours",
        "ANALYSE_TERMINEE": "Analyse terminée",
    }
    object_labels = {
        "DemandeAnalyse": "Demande d’analyse",
        "TypeAnalyse": "Type d’analyse",
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
    if date_debut:
        demandes = demandes.filter(date_demande__date__gte=date_debut)
    if date_fin:
        demandes = demandes.filter(date_demande__date__lte=date_fin)
    return render(request, "laboratoire/demande_list.html", {
        "demandes": demandes,
        "q": q,
        "statut": statut,
        "statut_choices": DemandeAnalyse.Statut.choices,
        "date_debut": request.GET.get("date_debut", ""),
        "date_fin": request.GET.get("date_fin", ""),
        "can_create": request.user.is_doctor,
        "can_manage_catalog": can_manage_catalog(request.user),
        "can_validate": can_validate_results(request.user),
        "stats": {
            "total": demandes.count(),
            "en_attente": demandes.filter(statut=DemandeAnalyse.Statut.EN_ATTENTE).count(),
            "en_cours": demandes.filter(statut=DemandeAnalyse.Statut.EN_COURS).count(),
            "terminees": demandes.filter(statut=DemandeAnalyse.Statut.TERMINEE).count(),
        },
    })


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
                for analyse in form.cleaned_data["analyses"]
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
    })


@patient_requis
def mes_resultats(request):
    resultats = Resultat.objects.filter(
        analyse_demandee__demande__patient=request.user,
        statut=Resultat.Statut.VALIDE,
    ).select_related(
        "analyse_demandee__demande__medecin",
        "analyse_demandee__type_analyse",
        "prelevement",
        "valide_par",
    ).order_by("-date_validation", "-pk")
    resultats_legacy = ResultatLaboratoire.objects.filter(
        dossier__patient=request.user,
        statut__in=("DISPONIBLE", "TRANSMIS"),
    ).select_related("laboratoire", "medecin_prescripteur").order_by(
        "-date_realisation", "-date_prescription", "-pk",
    )
    return render(request, "laboratoire/mes_resultats.html", {
        "resultats": resultats,
        "resultats_legacy": resultats_legacy,
        "resultats_count": resultats.count() + resultats_legacy.count(),
    })


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
            requested = {item.pk for item in form.cleaned_data["analyses"]}
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
                for item in form.cleaned_data["analyses"] if item.pk not in existing_rows
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
