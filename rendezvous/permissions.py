"""Règles d'accès du module Rendez-vous, alignées sur les rôles définis dans accounts.User."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect

from .models import STATUTS_ACTIFS


def peut_acceder_rdv(user):
    """Patients, médecins et administrateurs utilisent le module (pas le laboratoire)."""
    return user.is_authenticated and (user.is_admin_user or user.is_doctor or user.is_patient)


def peut_gerer_creneaux(user):
    return user.is_authenticated and (user.is_admin_user or user.is_doctor)


def peut_voir_rdv(user, rdv):
    if user.is_admin_user:
        return True
    if user.is_doctor:
        return rdv.medecin_id == user.pk
    if user.is_patient:
        return rdv.patient_id == user.pk
    return False


def peut_gerer_creneau(user, creneau):
    return user.is_admin_user or (user.is_doctor and creneau.medecin_id == user.pk)


def peut_confirmer(user, rdv):
    return rdv.statut == "EN_ATTENTE" and (user.is_admin_user or rdv.medecin_id == user.pk)


def peut_annuler(user, rdv):
    return rdv.statut in STATUTS_ACTIFS and peut_voir_rdv(user, rdv)


def peut_cloturer(user, rdv):
    """Marquer honoré / absent : médecin du RDV ou admin, une fois l'heure commencée."""
    return (
        rdv.statut in STATUTS_ACTIFS
        and rdv.est_passe
        and (user.is_admin_user or rdv.medecin_id == user.pk)
    )


def _creer_decorateur(verifier, message):
    def decorateur(vue):
        @wraps(vue)
        def enveloppe(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not verifier(request.user):
                messages.error(request, message)
                return redirect("dashboard")
            return vue(request, *args, **kwargs)
        return enveloppe
    return decorateur


rdv_acces_requis = _creer_decorateur(
    peut_acceder_rdv, "Vous n'avez pas accès à la gestion des rendez-vous."
)
creneaux_gestion_requise = _creer_decorateur(
    peut_gerer_creneaux, "Seuls les médecins et l'administrateur gèrent les créneaux."
)
