from functools import wraps
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def role_required(test):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not test(request.user):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def _is_admin(u):
    return u.is_admin_user

def _is_billing_staff(u):
    return u.is_admin_user or (u.is_doctor and u.is_verified)

def _can_see_billing(u):
    return _is_billing_staff(u) or u.is_patient


admin_required = role_required(_is_admin)
staff_required = role_required(_is_billing_staff)
billing_access_required = role_required(_can_see_billing)


def factures_visibles(user):
    """Les factures que cet utilisateur a le droit de voir."""
    from .models import Facture
    qs = Facture.objects.select_related('patient', 'medecin')
    if user.is_admin_user:
        return qs
    if user.is_doctor and user.is_verified:
        return qs.filter(medecin=user)
    if user.is_patient:
        return qs.filter(patient=user)
    return qs.none()