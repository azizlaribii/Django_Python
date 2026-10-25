from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .models import DemandeAnalyse, Prelevement, Resultat


def is_lab(user):
    return user.is_authenticated and user.is_laboratory


def is_admin(user):
    return user.is_authenticated and (
        user.is_admin_user or user.is_staff or user.is_superuser
    )


def is_lab_responsable(user):
    return is_lab(user)


def can_validate_results(user):
    return is_lab(user)


def peut(user, action, *, demande=None, resultat=None):
    if not user or not user.is_authenticated:
        return False
    if action == "historique":
        return is_admin(user)
    if action == "compte_rendu":
        return (
            user.is_doctor
            and demande is not None
            and demande.medecin_id == user.pk
        )
    if action == "lire_demande" and is_admin(user):
        return True
    if action == "lire_resultat" and is_admin(user):
        return resultat is not None
    if is_admin(user):
        return False
    if action in ("changer_statut", "resultat"):
        return user.is_laboratory
    if action == "creer_demande":
        return user.is_doctor
    if action == "creer_prelevement":
        return user.is_laboratory
    if action == "annuler_demande":
        return user.is_doctor and (
            demande is None or demande.medecin_id == user.pk
        )
    if action == "lire_demande":
        if demande is None:
            return user.is_doctor or user.is_laboratory
        return (
            (user.is_doctor and demande.medecin_id == user.pk)
            or user.is_laboratory
        )
    if action == "lire_resultat":
        if resultat is None:
            return False
        if user.is_patient:
            return (
                resultat.statut == Resultat.Statut.VALIDE
                and resultat.analyse_demandee.demande.patient_id == user.pk
            )
        if user.is_doctor:
            return (
                resultat.analyse_demandee.demande.medecin_id == user.pk
                and resultat.statut == Resultat.Statut.VALIDE
            )
        return user.is_laboratory and peut(
            user,
            "lire_demande",
            demande=resultat.analyse_demandee.demande,
        )
    return False


def exiger(user, action, *, demande=None, resultat=None):
    if not peut(user, action, demande=demande, resultat=resultat):
        raise PermissionDenied("Vous n’avez pas l’autorisation d’effectuer cette action.")


def demandes_visibles(user):
    queryset = DemandeAnalyse.objects.all()
    if not user.is_authenticated:
        return queryset.none()
    if user.is_admin_user or user.is_staff or user.is_superuser:
        return queryset
    if user.is_doctor:
        return queryset.filter(medecin=user)
    if user.is_laboratory:
        return queryset
    return queryset.none()


def prelevements_visibles(user):
    return Prelevement.objects.filter(
        demande__in=demandes_visibles(user),
    )


def resultats_visibles(user):
    queryset = Resultat.objects.all()
    if not user.is_authenticated:
        return queryset.none()
    if user.is_admin_user or user.is_staff or user.is_superuser:
        return queryset
    if user.is_laboratory:
        return queryset
    if user.is_doctor:
        return queryset.filter(
            analyse_demandee__demande__medecin=user,
            statut=Resultat.Statut.VALIDE,
        )
    if user.is_patient:
        return queryset.filter(
            analyse_demandee__demande__patient=user,
            statut=Resultat.Statut.VALIDE,
        )
    return queryset.none()


def laboratory_team_user_ids(user):
    User = get_user_model()
    if is_lab(user):
        return User.objects.filter(pk=user.pk).values_list("pk", flat=True)
    if is_admin(user):
        return User.objects.filter(
            role=User.Role.LABORATOIRE,
        ).values_list("pk", flat=True)
    return User.objects.none().values_list("pk", flat=True)


def can_manage_catalog(user):
    return user.is_authenticated and (
        user.is_admin_user or user.is_staff or user.is_superuser
    )


def can_view_requests(user):
    return user.is_authenticated and (
        is_lab(user) or user.is_doctor or is_admin(user)
    )


def role_required(check, message):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not check(request.user):
                messages.error(request, message)
                return redirect("dashboard")
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


laboratoire_requis = role_required(
    lambda user: is_lab(user) or is_admin(user),
    "Cette action est réservée au laboratoire.",
)
patient_requis = role_required(
    lambda user: user.is_authenticated and user.is_patient,
    "Cette page est réservée aux patients.",
)
catalogue_requis = role_required(can_manage_catalog, "Accès réservé à l’administration.")
consultation_requise = role_required(can_view_requests, "Vous n’avez pas accès au module laboratoire.")
