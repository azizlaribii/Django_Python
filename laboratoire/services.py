from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    AnalyseDemandee,
    DemandeAnalyse,
    HistoriqueAction,
    Prelevement,
    Resultat,
)
from .permissions import can_validate_results


def _audit_values(instance, fields):
    values = {field: getattr(instance, field) for field in fields}
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in values.items()
    }


def enregistrer_action(*, utilisateur, action, objet, objet_id=None, details=None):
    return HistoriqueAction.objects.create(
        utilisateur=utilisateur,
        type_action=action,
        objet_concerne=objet,
        objet_id=objet_id,
        details=details or {},
    )


@transaction.atomic
def enregistrer_prelevement(*, prelevement, utilisateur, donnees):
    if not utilisateur.is_authenticated or not utilisateur.is_laboratory:
        raise ValidationError("La gestion des prélèvements est réservée au laboratoire.")
    if prelevement.demande.statut == DemandeAnalyse.Statut.ANNULEE:
        raise ValidationError("Un prélèvement ne peut pas être modifié pour une demande annulée.")
    tracked_fields = (
        "code_prelevement", "type_prelevement", "date_prelevement", "date_reception",
        "statut", "motif_rejet", "remarque",
    )
    if prelevement.pk:
        original = Prelevement.objects.get(pk=prelevement.pk)
        avant = _audit_values(original, tracked_fields)
        created = False
    else:
        avant = {}
        created = True
    for field, value in donnees.items():
        setattr(prelevement, field, value)
    if prelevement.statut == Prelevement.Statut.PRELEVE and not prelevement.date_prelevement:
        prelevement.date_prelevement = timezone.now()
    if prelevement.statut == Prelevement.Statut.RECU and not prelevement.date_reception:
        prelevement.date_reception = timezone.now()
    prelevement.full_clean()
    prelevement.save()
    enregistrer_action(
        utilisateur=utilisateur,
        action="PRELEVEMENT_CREE" if created else "PRELEVEMENT_MODIFIE",
        objet="Prelevement",
        objet_id=prelevement.pk,
        details={
            "avant": avant,
            "apres": _audit_values(prelevement, tracked_fields),
        },
    )
    return prelevement


@transaction.atomic
def enregistrer_resultat(*, analyse_demandee, prelevement, utilisateur, donnees, resultat=None):
    if not utilisateur.is_authenticated or not utilisateur.is_laboratory:
        raise ValidationError("La saisie des résultats est réservée au laboratoire.")
    analyse_demandee = AnalyseDemandee.objects.select_for_update().select_related(
        "demande", "type_analyse",
    ).get(pk=analyse_demandee.pk)
    if analyse_demandee.demande.statut == DemandeAnalyse.Statut.ANNULEE:
        raise ValidationError("Un résultat ne peut pas être saisi pour une demande annulée.")
    if analyse_demandee.statut == AnalyseDemandee.Statut.ANNULEE:
        raise ValidationError("Une analyse annulée ne peut pas recevoir de résultat.")
    if prelevement and prelevement.demande_id != analyse_demandee.demande_id:
        raise ValidationError("Le prélèvement doit appartenir à la même demande que l’analyse.")
    if prelevement and prelevement.statut in (Prelevement.Statut.REJETE, Prelevement.Statut.ANNULE):
        raise ValidationError("Un prélèvement rejeté ou annulé ne peut pas produire de résultat.")
    if prelevement and prelevement.statut != Prelevement.Statut.RECU:
        raise ValidationError("Le prélèvement doit être reçu au laboratoire avant la saisie du résultat.")

    ancien_statut_analyse = analyse_demandee.statut
    ancien_statut_demande = analyse_demandee.demande.statut
    created = resultat is None
    if created:
        if Resultat.objects.filter(
            analyse_demandee=analyse_demandee, prelevement=prelevement,
        ).exists():
            raise ValidationError("Un résultat existe déjà pour cette analyse et ce prélèvement.")
        resultat = Resultat(
            analyse_demandee=analyse_demandee,
            prelevement=prelevement,
            saisi_par=utilisateur,
        )
    else:
        resultat = Resultat.objects.select_for_update().get(pk=resultat.pk)
    correction = resultat.statut in (Resultat.Statut.VALIDE, Resultat.Statut.CORRIGE)
    if correction:
        was_validated = resultat.statut == Resultat.Statut.VALIDE
        resultat.statut = Resultat.Statut.CORRIGE
        if was_validated:
            resultat.valide_par = None
            resultat.date_validation = None
        action = "RESULTAT_CORRIGE"
    else:
        resultat.statut = Resultat.Statut.EN_ATTENTE_VALIDATION
        action = "RESULTAT_SAISI" if created else "RESULTAT_MODIFIE"

    avant = {
        field: getattr(resultat, field)
        for field in ("valeur", "unite", "valeur_reference", "interpretation", "observation")
    } if not created else {}
    for field, value in donnees.items():
        setattr(resultat, field, value)
    resultat.full_clean()
    resultat.save()
    apres = {
        field: getattr(resultat, field)
        for field in ("valeur", "unite", "valeur_reference", "interpretation", "observation")
    }
    enregistrer_action(
        utilisateur=utilisateur, action=action, objet="Resultat", objet_id=resultat.pk,
        details={"avant": avant, "apres": apres, "statut": resultat.statut},
    )
    if analyse_demandee.statut in (
        AnalyseDemandee.Statut.EN_ATTENTE,
        AnalyseDemandee.Statut.TERMINEE,
    ):
        analyse_demandee.statut = AnalyseDemandee.Statut.EN_COURS
        analyse_demandee.save(update_fields=["statut"])
        enregistrer_action(
            utilisateur=utilisateur, action="ANALYSE_EN_COURS",
            objet="AnalyseDemandee", objet_id=analyse_demandee.pk,
            details={"avant": ancien_statut_analyse, "apres": analyse_demandee.statut},
        )
    if analyse_demandee.demande.statut in (
        DemandeAnalyse.Statut.EN_ATTENTE,
        DemandeAnalyse.Statut.TERMINEE,
    ):
        analyse_demandee.demande.statut = DemandeAnalyse.Statut.EN_COURS
        analyse_demandee.demande.save(update_fields=["statut"])
        enregistrer_action(
            utilisateur=utilisateur, action="DEMANDE_EN_COURS",
            objet="DemandeAnalyse", objet_id=analyse_demandee.demande_id,
            details={"avant": ancien_statut_demande, "apres": analyse_demandee.demande.statut},
        )
    return resultat


@transaction.atomic
def valider_resultat(*, resultat, utilisateur):
    if not can_validate_results(utilisateur):
        raise ValidationError(
            "La validation est réservée aux professionnels du laboratoire."
        )
    resultat = Resultat.objects.select_for_update().select_related(
        "analyse_demandee__demande",
    ).get(pk=resultat.pk)
    if resultat.statut not in (
        Resultat.Statut.EN_ATTENTE_VALIDATION,
        Resultat.Statut.CORRIGE,
    ):
        raise ValidationError("Ce résultat n’est pas en attente de validation.")
    resultat.statut = Resultat.Statut.VALIDE
    resultat.valide_par = utilisateur
    resultat.date_validation = timezone.now()
    resultat.save(update_fields=["statut", "valide_par", "date_validation", "date_modification"])
    enregistrer_action(
        utilisateur=utilisateur, action="RESULTAT_VALIDE", objet="Resultat",
        objet_id=resultat.pk, details={"statut": resultat.statut},
    )
    analyse = resultat.analyse_demandee
    if not analyse.resultats.exclude(statut=Resultat.Statut.VALIDE).exists():
        ancien_statut = analyse.statut
        analyse.statut = AnalyseDemandee.Statut.TERMINEE
        analyse.save(update_fields=["statut"])
        enregistrer_action(
            utilisateur=utilisateur, action="ANALYSE_TERMINEE",
            objet="AnalyseDemandee", objet_id=analyse.pk,
            details={"avant": ancien_statut, "apres": analyse.statut},
        )
    if not analyse.demande.analyses.exclude(
        statut__in=(AnalyseDemandee.Statut.TERMINEE, AnalyseDemandee.Statut.ANNULEE),
    ).exists():
        ancien_statut = analyse.demande.statut
        analyse.demande.statut = DemandeAnalyse.Statut.TERMINEE
        analyse.demande.save(update_fields=["statut"])
        enregistrer_action(
            utilisateur=utilisateur, action="DEMANDE_TERMINEE",
            objet="DemandeAnalyse", objet_id=analyse.demande_id,
            details={"avant": ancien_statut, "apres": analyse.demande.statut},
        )
    return resultat


@transaction.atomic
def annuler_demande(*, demande, utilisateur):
    if demande.statut != DemandeAnalyse.Statut.EN_ATTENTE:
        raise ValidationError("Seule une demande en attente peut être annulée.")
    demande.statut = DemandeAnalyse.Statut.ANNULEE
    demande.save(update_fields=["statut"])
    demande.analyses.exclude(statut=AnalyseDemandee.Statut.TERMINEE).update(
        statut=AnalyseDemandee.Statut.ANNULEE
    )
    enregistrer_action(
        utilisateur=utilisateur, action="DEMANDE_ANNULEE", objet="DemandeAnalyse",
        objet_id=demande.pk, details={"statut": demande.statut},
    )
    return demande
