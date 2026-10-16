from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect


def peut_consulter_stock(user):
    return user.is_authenticated and (user.is_admin_user or user.is_laboratory or user.is_doctor)


def peut_gerer_stock(user):
    return user.is_authenticated and (user.is_admin_user or user.is_laboratory)


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


stock_consultation_requise = _creer_decorateur(
    peut_consulter_stock, "Vous n’avez pas accès à la gestion des stocks."
)
stock_gestion_requise = _creer_decorateur(
    peut_gerer_stock, "Seuls l’administrateur et le laboratoire peuvent modifier le stock."
)
