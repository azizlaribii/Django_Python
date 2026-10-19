"""Logique métier des rendez-vous : toutes les écritures passent par ici.

Les vues, l'admin et les futures API ne modifient jamais le statut d'un rendez-vous
directement, afin que les règles (double réservation, délais, droits) restent
appliquées partout de la même façon.
"""
from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import STATUTS_ACTIFS, Creneau, RendezVous
from .permissions import peut_annuler, peut_cloturer, peut_confirmer, peut_gerer_creneau
from .signals import rdv_statut_change

Statut = RendezVous.Statut

MAX_CRENEAUX_PAR_GENERATION = 500


class RendezVousError(Exception):
    """Règle métier non respectée ; le message est affichable tel quel à l'utilisateur."""


def delai_annulation_patient():
    """Nombre d'heures minimum avant le RDV pour qu'un patient puisse annuler lui-même."""
    return getattr(settings, "RDV_DELAI_ANNULATION_PATIENT_HEURES", 2)


def _emettre(rdv, ancien_statut, par):
    transaction.on_commit(
        lambda: rdv_statut_change.send(sender=RendezVous, rdv=rdv, ancien_statut=ancien_statut, par=par)
    )


# --------------------------------------------------------------------------
# Réservation
# --------------------------------------------------------------------------
def reserver(*, creneau, patient, motif, par):
    """Réserve `creneau` pour `patient`. Lève RendezVousError si c'est impossible."""
    if not patient.is_patient:
        raise RendezVousError("Le rendez-vous doit être pris pour un compte patient.")
    if par.is_patient and par.pk != patient.pk:
        raise RendezVousError("Vous ne pouvez réserver que pour vous-même.")
    if par.is_doctor and creneau.medecin_id != par.pk:
        raise RendezVousError("Vous ne pouvez réserver que sur vos propres créneaux.")
    if not (par.is_patient or par.is_doctor or par.is_admin_user):
        raise RendezVousError("Votre rôle ne permet pas de réserver un rendez-vous.")
    motif = (motif or "").strip()
    if not motif:
        raise RendezVousError("Merci d'indiquer le motif de la consultation.")

    try:
        with transaction.atomic():
            # Verrouille le créneau le temps de la vérification (effectif sur PostgreSQL/MySQL).
            creneau = Creneau.objects.select_for_update().get(pk=creneau.pk)
            if creneau.debut <= timezone.now():
                raise RendezVousError("Ce créneau est déjà passé.")
            if creneau.est_bloque:
                raise RendezVousError("Ce créneau n'est pas ouvert à la réservation.")
            if creneau.rendez_vous.filter(statut__in=STATUTS_ACTIFS).exists():
                raise RendezVousError("Ce créneau est déjà réservé, merci d'en choisir un autre.")
            conflit = (
                RendezVous.objects.actifs()
                .filter(patient=patient, creneau__debut__lt=creneau.fin, creneau__fin__gt=creneau.debut)
                .select_related("creneau")
                .first()
            )
            if conflit:
                raise RendezVousError(
                    f"Le patient a déjà un rendez-vous sur cet horaire ({conflit.creneau})."
                )

            # Un RDV posé par le médecin ou l'admin est confirmé d'office.
            confirme = par.is_doctor or par.is_admin_user
            rdv = RendezVous.objects.create(
                creneau=creneau,
                patient=patient,
                medecin=creneau.medecin,
                motif=motif[:255],
                cree_par=par,
                statut=Statut.CONFIRME if confirme else Statut.EN_ATTENTE,
                date_confirmation=timezone.now() if confirme else None,
            )
            _emettre(rdv, None, par)
            return rdv
    except IntegrityError:
        # Course entre deux réservations simultanées : la contrainte unique a tranché.
        raise RendezVousError("Ce créneau vient d'être réservé par quelqu'un d'autre.")


def confirmer(rdv, *, par):
    if not peut_confirmer(par, rdv):
        raise RendezVousError("Ce rendez-vous ne peut pas être confirmé.")
    if rdv.est_passe:
        raise RendezVousError("L'heure de ce rendez-vous est déjà passée.")
    ancien = rdv.statut
    rdv.statut = Statut.CONFIRME
    rdv.date_confirmation = timezone.now()
    rdv.save(update_fields=["statut", "date_confirmation", "date_modification"])
    _emettre(rdv, ancien, par)
    return rdv


def annuler(rdv, *, par, motif=""):
    if not peut_annuler(par, rdv):
        raise RendezVousError("Ce rendez-vous ne peut pas être annulé.")
    if par.is_patient:
        limite = rdv.creneau.debut - timedelta(hours=delai_annulation_patient())
        if timezone.now() > limite:
            raise RendezVousError(
                f"Annulation en ligne impossible moins de {delai_annulation_patient()} h avant "
                "le rendez-vous. Merci de contacter le cabinet."
            )
    ancien = rdv.statut
    rdv.statut = Statut.ANNULE
    rdv.annule_par = par
    rdv.date_annulation = timezone.now()
    rdv.motif_annulation = (motif or "").strip()[:255]
    rdv.save(update_fields=["statut", "annule_par", "date_annulation", "motif_annulation", "date_modification"])
    _emettre(rdv, ancien, par)
    return rdv


def cloturer(rdv, *, par, statut, notes=""):
    """Après l'heure du RDV : le marquer honoré (TERMINE) ou patient absent (ABSENT)."""
    if statut not in (Statut.TERMINE, Statut.ABSENT):
        raise RendezVousError("Statut de clôture invalide.")
    if not peut_cloturer(par, rdv):
        raise RendezVousError("Ce rendez-vous ne peut pas encore être clôturé.")
    ancien = rdv.statut
    rdv.statut = statut
    if notes:
        rdv.notes_medecin = notes.strip()
    rdv.save(update_fields=["statut", "notes_medecin", "date_modification"])
    _emettre(rdv, ancien, par)
    return rdv


# --------------------------------------------------------------------------
# Créneaux
# --------------------------------------------------------------------------
def _aware(jour, heure):
    return timezone.make_aware(datetime.combine(jour, heure))


def generer_creneaux(*, medecin, date_debut, date_fin, jours, heure_debut, heure_fin,
                     duree_minutes, pause_debut=None, pause_fin=None):
    """Crée une série de créneaux réguliers. Renvoie (nb_crees, nb_ignores).

    Les créneaux passés ou qui chevauchent un créneau existant sont ignorés.
    `jours` est une liste d'entiers 0 (lundi) à 6 (dimanche).
    """
    if not medecin.is_doctor:
        raise RendezVousError("Les créneaux doivent appartenir à un médecin.")
    if date_fin < date_debut:
        raise RendezVousError("La date de fin précède la date de début.")
    if heure_fin <= heure_debut:
        raise RendezVousError("L'heure de fin doit être après l'heure de début.")
    pas = timedelta(minutes=duree_minutes)
    jours = {int(j) for j in jours}

    candidats = []
    jour = date_debut
    while jour <= date_fin:
        if jour.weekday() in jours:
            debut = _aware(jour, heure_debut)
            fin_journee = _aware(jour, heure_fin)
            p_deb = _aware(jour, pause_debut) if pause_debut and pause_fin else None
            p_fin = _aware(jour, pause_fin) if pause_debut and pause_fin else None
            while debut + pas <= fin_journee:
                fin = debut + pas
                if p_deb and debut < p_fin and fin > p_deb:
                    debut = p_fin  # on saute la pause et on reprend juste après
                    continue
                candidats.append((debut, fin))
                debut = fin
        jour += timedelta(days=1)

    if len(candidats) > MAX_CRENEAUX_PAR_GENERATION:
        raise RendezVousError(
            f"Trop de créneaux à générer ({len(candidats)}). Limite : {MAX_CRENEAUX_PAR_GENERATION}, "
            "réduisez la période."
        )

    maintenant = timezone.now()
    existants = list(
        Creneau.objects.du_medecin(medecin)
        .filter(fin__gt=_aware(date_debut, heure_debut), debut__lt=_aware(date_fin, heure_fin))
        .values_list("debut", "fin")
    )
    nouveaux, ignores = [], 0
    for debut, fin in candidats:
        if debut <= maintenant or any(d < fin and f > debut for d, f in existants):
            ignores += 1
            continue
        nouveaux.append(Creneau(medecin=medecin, debut=debut, fin=fin))
    Creneau.objects.bulk_create(nouveaux)
    return len(nouveaux), ignores


def basculer_blocage(creneau, *, par):
    if not peut_gerer_creneau(par, creneau):
        raise RendezVousError("Vous ne pouvez pas modifier ce créneau.")
    if not creneau.est_bloque and creneau.rdv_actif is not None:
        raise RendezVousError("Annulez d'abord le rendez-vous qui occupe ce créneau.")
    creneau.est_bloque = not creneau.est_bloque
    creneau.save(update_fields=["est_bloque"])
    return creneau


def supprimer_creneau(creneau, *, par):
    if not peut_gerer_creneau(par, creneau):
        raise RendezVousError("Vous ne pouvez pas supprimer ce créneau.")
    if creneau.rendez_vous.exists():
        raise RendezVousError(
            "Ce créneau a un historique de rendez-vous : bloquez-le plutôt que de le supprimer."
        )
    creneau.delete()
