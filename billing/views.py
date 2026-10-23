from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from .forms import TarifForm
from .models import Tarif
from .permissions import admin_required, billing_access_required, factures_visibles


# ───────────── TARIFS (admin seulement) ─────────────

@admin_required
def tarif_list(request):
    tarifs = Tarif.objects.all()
    return render(request, 'billing/tarif_list.html', {'tarifs': tarifs})


@admin_required
def tarif_create(request):
    form = TarifForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, "Tarif créé avec succès.")
        return redirect('tarif_list')
    return render(request, 'billing/tarif_form.html', {'form': form})


@admin_required
def tarif_update(request, pk):
    tarif = get_object_or_404(Tarif, pk=pk)
    form = TarifForm(request.POST or None, instance=tarif)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, "Tarif modifié.")
        return redirect('tarif_list')
    return render(request, 'billing/tarif_form.html', {'form': form, 'tarif': tarif})


@admin_required
def tarif_delete(request, pk):
    tarif = get_object_or_404(Tarif, pk=pk)
    if request.method == 'POST':
        tarif.delete()
        messages.success(request, "Tarif supprimé.")
        return redirect('tarif_list')
    return render(request, 'billing/tarif_confirm_delete.html', {'tarif': tarif})


# ───────────── FACTURES ─────────────

@billing_access_required
def facture_list(request):
    factures = factures_visibles(request.user)
    return render(request, 'billing/facture_list.html', {'factures': factures})


@billing_access_required
def facture_detail(request, pk):
    facture = get_object_or_404(factures_visibles(request.user), pk=pk)
    peut_gerer = request.user.is_admin_user or request.user.is_doctor
    return render(request, 'billing/facture_detail.html',
                  {'facture': facture, 'peut_gerer': peut_gerer})