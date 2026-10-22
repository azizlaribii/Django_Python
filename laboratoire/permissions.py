from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import redirect


def is_lab(user):
    return user.is_authenticated and user.is_laboratory


def is_lab_responsable(user):
    return is_lab(user) and user.groups.filter(
        name="Biologiste responsable",
    ).exists()


def can_validate_results(user):
    return is_lab_responsable(user)


def laboratory_team_user_ids(user):
    User = get_user_model()
    if not is_lab(user):
        return User.objects.none().values_list("pk", flat=True)
    return User.objects.filter(role="LABORATOIRE").filter(
        Q(pk=user.pk)
        | Q(groups__name__startswith="Équipe Laboratoire "),
    ).values_list("pk", flat=True).distinct()


def can_manage_catalog(user):
    return user.is_authenticated and user.is_admin_user


def can_view_requests(user):
    return user.is_authenticated and (
        user.is_laboratory or user.is_doctor or user.is_admin_user
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


laboratoire_requis = role_required(is_lab, "Cette action est réservée au laboratoire.")
patient_requis = role_required(
    lambda user: user.is_authenticated and user.is_patient,
    "Cette page est réservée aux patients.",
)
catalogue_requis = role_required(can_manage_catalog, "Accès réservé à l’administration.")
consultation_requise = role_required(can_view_requests, "Vous n’avez pas accès au module laboratoire.")
