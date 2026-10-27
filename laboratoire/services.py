from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    AnalyseDemandee,
    DemandeAnalyse,
    HistoriqueAction,
    ParametresLaboratoire,
    Prelevement,
    Resultat,
)
from .permissions import exiger, peut


def enregistrer_action(*, utilisateur, action, objet, objet_id=None, details=None):
    return HistoriqueAction.objects.create(
        utilisateur=utilisateur,
        type_action=action,
        objet_concerne=objet,
        objet_id=objet_id,
        details=details or {},
    )


def _erreur(message):
    raise ValidationError(message)


def _audit_values(instance, fields):
    values = {field: getattr(instance, field) for field in fields}
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in values.items()
    }


@transaction.atomic
def creer_prelevements(demande, utilisateur=None):
    demande = DemandeAnalyse.objects.select_for_update().get(pk=demande.pk)
    utilisateur = utilisateur or demande.cree_par or demande.medecin
    action = "creer_prelevement" if utilisateur.is_laboratory else "creer_demande"
    exiger(utilisateur, action, demande=demande)
    if demande.statut == DemandeAnalyse.Statut.ANNULEE:
        _erreur("Impossible de créer des prélèvements pour une demande annulée.")
    analyses = list(
        demande.analyses.select_related("type_analyse", "prelevement").order_by("pk")
    )
    grouped = {}
    for analyse in analyses:
        if analyse.prelevement_id:
            continue
        grouped.setdefault(analyse.type_analyse.type_echantillon, []).append(analyse)

    created = []
    pending_samples = {
        sample.type_prelevement: sample
        for sample in demande.prelevements.filter(
            statut=Prelevement.Statut.A_EFFECTUER,
        ).order_by("date_creation", "pk")
    }
    for type_echantillon, analyses_groupe in grouped.items():
        prelevement = pending_samples.get(type_echantillon)
        if prelevement is None:
            prelevement = Prelevement.objects.create(
                demande=demande,
                type_prelevement=type_echantillon,
            )
            created.append(prelevement)
            enregistrer_action(
                utilisateur=utilisateur,
                action="PRELEVEMENT_CREE",
                objet="Prelevement",
                objet_id=prelevement.pk,
                details={
                    "code": prelevement.code_prelevement,
                    "type": prelevement.type_prelevement,
                },
            )
        AnalyseDemandee.objects.filter(
            pk__in=[analyse.pk for analyse in analyses_groupe],
        ).update(prelevement=prelevement)
        enregistrer_action(
            utilisateur=utilisateur,
            action="ANALYSES_LIEES_PRELEVEMENT",
            objet="Prelevement",
            objet_id=prelevement.pk,
            details={
                "analyses": [analyse.pk for analyse in analyses_groupe],
            },
        )
    return created


@transaction.atomic
def synchroniser(prelevement, utilisateur=None):
    prelevement = Prelevement.objects.select_for_update().select_related(
        "demande",
    ).get(pk=prelevement.pk)
    analyses = list(
        AnalyseDemandee.objects.select_for_update()
        .select_related("demande", "prelevement")
        .filter(prelevement=prelevement)
        .prefetch_related("resultats")
    )
    analyses_actives = [
        analyse for analyse in analyses
        if analyse.statut != AnalyseDemandee.Statut.ANNULEE
    ]

    for analyse in analyses_actives:
        if analyse.resultats.filter(statut=Resultat.Statut.VALIDE).exists():
            new_status = AnalyseDemandee.Statut.TERMINEE
        elif prelevement.statut == Prelevement.Statut.ANNULE:
            new_status = AnalyseDemandee.Statut.ANNULEE
        elif prelevement.statut in (
            Prelevement.Statut.PRELEVE,
            Prelevement.Statut.RECU,
            Prelevement.Statut.TERMINE,
            Prelevement.Statut.REJETE,
        ):
            new_status = AnalyseDemandee.Statut.EN_COURS
        else:
            new_status = AnalyseDemandee.Statut.EN_ATTENTE

        if analyse.statut != new_status:
            old_status = analyse.statut
            analyse.statut = new_status
            analyse.save(update_fields=["statut"])
            enregistrer_action(
                utilisateur=utilisateur,
                action="ANALYSE_STATUT_SYNCHRONISE",
                objet="AnalyseDemandee",
                objet_id=analyse.pk,
                details={"avant": old_status, "apres": new_status},
            )

    if (
        prelevement.statut == Prelevement.Statut.RECU
        and analyses_actives
        and all(
            analyse.resultats.filter(statut=Resultat.Statut.VALIDE).exists()
            for analyse in analyses_actives
        )
    ):
        changer_statut(
            prelevement,
            Prelevement.Statut.TERMINE,
            utilisateur,
        )
        return prelevement

    demande = prelevement.demande
    if demande.statut != DemandeAnalyse.Statut.ANNULEE:
        active_statuses = list(
            demande.analyses.exclude(statut=AnalyseDemandee.Statut.ANNULEE)
            .values_list("statut", flat=True)
        )
        if active_statuses and all(
            status == AnalyseDemandee.Statut.TERMINEE for status in active_statuses
        ):
            new_status = DemandeAnalyse.Statut.TERMINEE
        elif any(
            status in (
                AnalyseDemandee.Statut.EN_COURS,
                AnalyseDemandee.Statut.TERMINEE,
            )
            for status in active_statuses
        ):
            new_status = DemandeAnalyse.Statut.EN_COURS
        else:
            new_status = DemandeAnalyse.Statut.EN_ATTENTE
        if demande.statut != new_status:
            old_status = demande.statut
            demande.statut = new_status
            demande.save(update_fields=["statut", "motif_annulation"])
            enregistrer_action(
                utilisateur=utilisateur,
                action="DEMANDE_STATUT_SYNCHRONISE",
                objet="DemandeAnalyse",
                objet_id=demande.pk,
                details={"avant": old_status, "apres": new_status},
            )
    return prelevement


@transaction.atomic
def changer_statut(prelevement, nouveau, utilisateur, motif="", remarque=""):
    prelevement = Prelevement.objects.select_for_update().select_related(
        "demande",
    ).get(pk=prelevement.pk)
    if nouveau == Prelevement.Statut.ANNULE:
        if not (
            peut(utilisateur, "changer_statut", demande=prelevement.demande)
            or peut(utilisateur, "annuler_demande", demande=prelevement.demande)
        ):
            exiger(utilisateur, "changer_statut", demande=prelevement.demande)
    else:
        exiger(utilisateur, "changer_statut", demande=prelevement.demande)
    transitions = {
        Prelevement.Statut.A_EFFECTUER: {
            Prelevement.Statut.RECU,
            Prelevement.Statut.PRELEVE,
            Prelevement.Statut.ANNULE,
        },
        Prelevement.Statut.PRELEVE: {
            Prelevement.Statut.RECU,
            Prelevement.Statut.REJETE,
        },
        Prelevement.Statut.RECU: {
            Prelevement.Statut.TERMINE,
            Prelevement.Statut.REJETE,
        },
        Prelevement.Statut.REJETE: set(),
        Prelevement.Statut.ANNULE: set(),
        Prelevement.Statut.TERMINE: set(),
    }
    if nouveau not in transitions.get(prelevement.statut, set()):
        _erreur(
            f"Le passage de « {prelevement.get_statut_display()} » à "
            f"« {dict(Prelevement.Statut.choices).get(nouveau, nouveau)} » n’est pas autorisé."
        )

    now = timezone.now()
    if nouveau == Prelevement.Statut.PRELEVE:
        prelevement.date_prelevement = now
        prelevement.preleve_par = utilisateur
    elif nouveau == Prelevement.Statut.RECU:
        if prelevement.date_prelevement is None:
            prelevement.date_prelevement = now
            prelevement.preleve_par = utilisateur
        prelevement.date_reception = now
        prelevement.recu_par = utilisateur
    elif nouveau == Prelevement.Statut.REJETE:
        motif = motif.strip()
        remarque = remarque.strip()
        motifs = ParametresLaboratoire.get_solo().motifs_rejet
        if motif not in motifs:
            _erreur("Sélectionnez un motif de refus proposé.")
        if motif == "Autre" and not remarque:
            _erreur("Précisez le motif lorsque vous choisissez « Autre ».")
        prelevement.motif_rejet = motif
        prelevement.remarque = remarque
    elif nouveau == Prelevement.Statut.ANNULE:
        prelevement.remarque = remarque.strip()

    old_status = prelevement.statut
    prelevement.statut = nouveau
    prelevement.full_clean()
    prelevement.save()
    enregistrer_action(
        utilisateur=utilisateur,
        action="PRELEVEMENT_STATUT_MODIFIE",
        objet="Prelevement",
        objet_id=prelevement.pk,
        details={
            "avant": old_status,
            "apres": nouveau,
            "motif": motif,
            "remarque": remarque,
        },
    )
    synchroniser(prelevement, utilisateur)
    return prelevement


@transaction.atomic
def refaire_prelevement(ancien, utilisateur):
    ancien = Prelevement.objects.select_for_update().select_related("demande").get(
        pk=ancien.pk,
    )
    exiger(utilisateur, "changer_statut", demande=ancien.demande)
    if ancien.statut != Prelevement.Statut.REJETE:
        _erreur("Seul un prélèvement refusé peut être refait.")
    nouveau = Prelevement.objects.create(
        demande=ancien.demande,
        type_prelevement=ancien.type_prelevement,
        precision_type=ancien.precision_type,
        prelevement_precedent=ancien,
    )
    analyses = list(ancien.analyses.all())
    for analyse in analyses:
        analyse.prelevement = nouveau
        analyse.statut = AnalyseDemandee.Statut.EN_ATTENTE
        analyse.save(update_fields=["prelevement", "statut"])
        enregistrer_action(
            utilisateur=utilisateur,
            action="ANALYSE_PRELEVEMENT_REFAIT",
            objet="AnalyseDemandee",
            objet_id=analyse.pk,
            details={
                "ancien_prelevement_id": ancien.pk,
                "nouveau_prelevement_id": nouveau.pk,
            },
        )
    enregistrer_action(
        utilisateur=utilisateur,
        action="PRELEVEMENT_REFAIT",
        objet="Prelevement",
        objet_id=nouveau.pk,
        details={
            "ancien_prelevement_id": ancien.pk,
            "nouveau_code": nouveau.code_prelevement,
            "analyses": [analyse.pk for analyse in analyses],
        },
    )
    synchroniser(nouveau, utilisateur)
    return nouveau


def _valider_donnees_resultat(analyse, donnees, *, exiger_valeur=True):
    valeur = str(donnees.get("valeur", "")).strip()
    if exiger_valeur and not valeur:
        _erreur("La valeur du résultat est obligatoire.")
    numeric_text = valeur.lstrip("<>≤≥").strip().replace(",", ".")
    if numeric_text:
        try:
            numeric_value = Decimal(numeric_text)
        except InvalidOperation:
            numeric_value = None
        if numeric_value is not None and (
            not numeric_value.is_finite() or numeric_value <= 0
        ):
            _erreur(
                "La valeur du résultat doit être un nombre strictement supérieur à zéro."
            )
    reference = donnees.get("valeur_reference", "")
    unite = donnees.get("unite") or analyse.type_analyse.unite
    interpretation = donnees.get("interpretation", "")
    observation = donnees.get("observation", "")
    commentaire_interne = donnees.get("commentaire_interne", observation)
    commentaire_patient = donnees.get("commentaire_patient", "")
    if not reference:
        minimum = analyse.type_analyse.valeur_reference_min
        maximum = analyse.type_analyse.valeur_reference_max
        if minimum is not None or maximum is not None:
            reference = f"{minimum if minimum is not None else '—'} – {maximum if maximum is not None else '—'} {unite}".strip()
    return {
        "valeur": valeur,
        "unite": unite,
        "valeur_reference": reference,
        "interpretation": interpretation,
        "observation": observation,
        "commentaire_interne": commentaire_interne,
        "commentaire_patient": commentaire_patient,
    }


@transaction.atomic
def enregistrer_resultats_brouillon(*, resultats, utilisateur, prelevement):
    exiger(utilisateur, "resultat", demande=prelevement.demande)
    if prelevement.statut != Prelevement.Statut.RECU:
        _erreur("Le tube doit être reçu avant la saisie du résultat.")
    if not resultats:
        _erreur("Ajoutez au moins une valeur avant d’enregistrer le brouillon.")

    saved = []
    for analyse, donnees in resultats.items():
        analyse = AnalyseDemandee.objects.select_for_update().select_related(
            "demande", "type_analyse", "prelevement",
        ).get(pk=analyse.pk)
        exiger(utilisateur, "resultat", demande=analyse.demande)
        if analyse.demande.statut == DemandeAnalyse.Statut.ANNULEE:
            _erreur("La demande est annulée.")
        if analyse.statut == AnalyseDemandee.Statut.ANNULEE:
            _erreur("Cette analyse est annulée.")
        if analyse.prelevement_id != prelevement.pk:
            _erreur("Le prélèvement ne correspond pas à cette analyse.")

        resultat = Resultat.objects.filter(analyse_demandee=analyse).first()
        if resultat and resultat.statut == Resultat.Statut.VALIDE:
            _erreur("Ce résultat est déjà validé ; utilisez la correction tracée.")
        if resultat is None:
            resultat = Resultat(
                analyse_demandee=analyse,
                prelevement=prelevement,
                saisi_par=utilisateur,
            )

        data = _valider_donnees_resultat(
            analyse,
            donnees,
            exiger_valeur=False,
        )
        for field, value in data.items():
            setattr(resultat, field, value)
        resultat.prelevement = prelevement
        resultat.saisi_par = utilisateur
        resultat.statut = Resultat.Statut.EN_SAISIE
        resultat.valide_par = None
        resultat.date_validation = None
        resultat.full_clean(exclude=["valeur"])
        resultat.save()
        enregistrer_action(
            utilisateur=utilisateur,
            action="RESULTAT_BROUILLON_ENREGISTRE",
            objet="Resultat",
            objet_id=resultat.pk,
            details={
                "analyse_id": analyse.pk,
                "prelevement_id": prelevement.pk,
                "valeur": resultat.valeur,
            },
        )
        saved.append(resultat)
    synchroniser(prelevement, utilisateur)
    return saved


@transaction.atomic
def envoyer_resultats(
    *,
    utilisateur,
    resultats=None,
    analyse_demandee=None,
    donnees=None,
    prelevement=None,
):
    exiger(utilisateur, "resultat")
    entries = resultats
    if entries is None:
        if analyse_demandee is None or donnees is None:
            _erreur("Les résultats à envoyer sont manquants.")
        entries = {analyse_demandee: donnees}
    if not hasattr(entries, "items") or not entries:
        _erreur("Ajoutez au moins un résultat avant l’envoi.")

    saved = []
    for analyse, values in entries.items():
        analyse = AnalyseDemandee.objects.select_for_update().select_related(
            "demande", "type_analyse", "prelevement",
        ).get(pk=analyse.pk)
        exiger(utilisateur, "resultat", demande=analyse.demande)
        if analyse.demande.statut == DemandeAnalyse.Statut.ANNULEE:
            _erreur("La demande est annulée.")
        if analyse.statut == AnalyseDemandee.Statut.ANNULEE:
            _erreur("Cette analyse est annulée.")
        associated_sample = prelevement or analyse.prelevement
        if associated_sample is None:
            _erreur("Aucun prélèvement n’est associé à cette analyse.")
        if associated_sample.demande_id != analyse.demande_id:
            _erreur("Le prélèvement ne correspond pas à la demande.")
        if associated_sample.statut != Prelevement.Statut.RECU:
            _erreur("Le tube doit être reçu avant la saisie du résultat.")

        result = Resultat.objects.filter(analyse_demandee=analyse).first()
        if result and result.statut == Resultat.Statut.VALIDE:
            _erreur("Ce résultat est déjà validé ; utilisez la correction tracée.")
        if result is None:
            result = Resultat(
                analyse_demandee=analyse,
                prelevement=associated_sample,
                saisi_par=utilisateur,
            )
        result.prelevement = associated_sample
        result.saisi_par = utilisateur
        for key, value in _valider_donnees_resultat(analyse, values).items():
            setattr(result, key, value)
        result.statut = Resultat.Statut.VALIDE
        result.valide_par = utilisateur
        result.date_validation = timezone.now()
        result.full_clean()
        result.save()
        enregistrer_action(
            utilisateur=utilisateur,
            action="RESULTAT_ENVOYE",
            objet="Resultat",
            objet_id=result.pk,
            details={
                "valeur": result.valeur,
                "unite": result.unite,
                "prelevement_id": associated_sample.pk,
                "version": result.version,
            },
        )
        saved.append(result)
        synchroniser(associated_sample, utilisateur)
    return saved[0] if len(saved) == 1 else saved


@transaction.atomic
def corriger_resultat(*, resultat, utilisateur, donnees, motif):
    exiger(utilisateur, "resultat")
    motif = motif.strip()
    if not motif:
        _erreur("Le motif de correction est obligatoire.")
    resultat = Resultat.objects.select_for_update().select_related(
        "analyse_demandee__demande",
        "analyse_demandee__type_analyse",
        "analyse_demandee__prelevement",
    ).get(pk=resultat.pk)
    if resultat.statut != Resultat.Statut.VALIDE:
        _erreur("Seul un résultat validé peut être corrigé.")
    analyse = resultat.analyse_demandee
    if not peut(utilisateur, "resultat", demande=analyse.demande):
        _erreur("Vous n’avez pas accès à la correction de ce résultat.")

    previous = {
        "valeur": resultat.valeur,
        "unite": resultat.unite,
        "valeur_reference": resultat.valeur_reference,
        "interpretation": resultat.interpretation,
        "observation": resultat.observation,
        "commentaire_interne": resultat.commentaire_interne,
        "commentaire_patient": resultat.commentaire_patient,
        "version": resultat.version,
    }
    for key, value in _valider_donnees_resultat(analyse, donnees).items():
        setattr(resultat, key, value)
    resultat.version += 1
    resultat.motif_correction = motif
    resultat.saisi_par = utilisateur
    resultat.valide_par = utilisateur
    resultat.date_validation = timezone.now()
    resultat.full_clean()
    resultat.save()
    enregistrer_action(
        utilisateur=utilisateur,
        action="RESULTAT_CORRIGE",
        objet="Resultat",
        objet_id=resultat.pk,
        details={
            "avant": previous,
            "apres": {
                "valeur": resultat.valeur,
                "unite": resultat.unite,
                "commentaire_interne": resultat.commentaire_interne,
                "commentaire_patient": resultat.commentaire_patient,
                "version": resultat.version,
            },
            "motif": motif,
        },
    )
    if analyse.prelevement_id:
        synchroniser(analyse.prelevement, utilisateur)
    return resultat


@transaction.atomic
def enregistrer_prelevement(*, prelevement, utilisateur, donnees):
    exiger(utilisateur, "changer_statut")
    if prelevement.pk:
        _erreur("Les prélèvements existants ne peuvent pas être modifiés directement.")
    for field, value in donnees.items():
        if field in ("statut", "date_prelevement", "date_reception"):
            continue
        setattr(prelevement, field, value)
    prelevement.statut = Prelevement.Statut.A_EFFECTUER
    prelevement.date_prelevement = None
    prelevement.date_reception = None
    prelevement.full_clean()
    prelevement.save()
    enregistrer_action(
        utilisateur=utilisateur,
        action="PRELEVEMENT_CREE",
        objet="Prelevement",
        objet_id=prelevement.pk,
        details={
            "code": prelevement.code_prelevement,
            "type": prelevement.type_prelevement,
            "statut": prelevement.statut,
        },
    )
    return prelevement


@transaction.atomic
def enregistrer_resultat(*, analyse_demandee, prelevement, utilisateur, donnees, resultat=None):
    if resultat is not None and resultat.statut == Resultat.Statut.VALIDE:
        return corriger_resultat(
            resultat=resultat,
            utilisateur=utilisateur,
            donnees=donnees,
            motif=donnees.get("motif_correction", ""),
        )
    return envoyer_resultats(
        analyse_demandee=analyse_demandee,
        utilisateur=utilisateur,
        donnees=donnees,
        prelevement=prelevement,
    )


def valider_resultat(*, resultat, utilisateur):
    if not peut(utilisateur, "resultat"):
        _erreur("La validation des résultats est réservée au laboratoire.")
    if resultat.statut == Resultat.Statut.VALIDE:
        _erreur("Ce résultat est déjà validé.")
    return envoyer_resultats(
        analyse_demandee=resultat.analyse_demandee,
        utilisateur=utilisateur,
        donnees={
            "valeur": resultat.valeur,
            "unite": resultat.unite,
            "valeur_reference": resultat.valeur_reference,
            "interpretation": resultat.interpretation,
            "observation": resultat.observation,
            "commentaire_interne": resultat.commentaire_interne,
            "commentaire_patient": resultat.commentaire_patient,
        },
        prelevement=resultat.prelevement,
    )


def rejeter_resultat(*, resultat, utilisateur, commentaire):
    _erreur("Les résultats ne sont plus rejetés séparément : corrigez-les avec un motif.")


@transaction.atomic
def annuler_demande(*, demande, utilisateur, motif=""):
    exiger(utilisateur, "annuler_demande", demande=demande)
    demande = DemandeAnalyse.objects.select_for_update().get(pk=demande.pk)
    if demande.statut not in (
        DemandeAnalyse.Statut.EN_ATTENTE,
        DemandeAnalyse.Statut.EN_COURS,
    ):
        _erreur("Seule une demande à faire ou en cours peut être annulée.")
    if motif:
        demande.motif_annulation = motif.strip()
    if not demande.motif_annulation.strip():
        _erreur("Le motif est obligatoire pour annuler une demande.")
    if demande.prelevements.exclude(
        statut=Prelevement.Statut.A_EFFECTUER,
    ).exists():
        _erreur("La demande ne peut plus être annulée après le début d’un prélèvement.")
    demande.full_clean()
    old_status = demande.statut
    for prelevement in demande.prelevements.filter(
        statut=Prelevement.Statut.A_EFFECTUER,
    ):
        changer_statut(
            prelevement,
            Prelevement.Statut.ANNULE,
            utilisateur,
            remarque=demande.motif_annulation,
        )
    demande.statut = DemandeAnalyse.Statut.ANNULEE
    demande.save(update_fields=["statut", "motif_annulation"])
    for analyse in demande.analyses.exclude(
        statut__in=[
            AnalyseDemandee.Statut.TERMINEE,
            AnalyseDemandee.Statut.ANNULEE,
        ],
    ):
        old_analysis_status = analyse.statut
        analyse.statut = AnalyseDemandee.Statut.ANNULEE
        analyse.save(update_fields=["statut"])
        enregistrer_action(
            utilisateur=utilisateur,
            action="ANALYSE_ANNULEE",
            objet="AnalyseDemandee",
            objet_id=analyse.pk,
            details={"avant": old_analysis_status, "apres": analyse.statut},
        )
    enregistrer_action(
        utilisateur=utilisateur,
        action="DEMANDE_ANNULEE",
        objet="DemandeAnalyse",
        objet_id=demande.pk,
        details={
            "avant": old_status,
            "apres": demande.statut,
            "motif": demande.motif_annulation,
        },
    )
    return demande
