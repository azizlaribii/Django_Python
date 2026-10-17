from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from .forms import TarifForm
from .models import Tarif


# READ : liste
@login_required
def tarif_list(request):
    tarifs = Tarif.objects.all()
    return render(request, 'billing/tarif_list.html', {'tarifs': tarifs})


# CREATE
@login_required
def tarif_create(request):
    form = TarifForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, "Tarif créé avec succès.")
        return redirect('tarif_list')
    return render(request, 'billing/tarif_form.html', {'form': form})


# UPDATE
@login_required
def tarif_update(request, pk):
    tarif = get_object_or_404(Tarif, pk=pk)
    form = TarifForm(request.POST or None, instance=tarif)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, "Tarif modifié.")
        return redirect('tarif_list')
    return render(request, 'billing/tarif_form.html', {'form': form, 'tarif': tarif})


# DELETE
@login_required
def tarif_delete(request, pk):
    tarif = get_object_or_404(Tarif, pk=pk)
    if request.method == 'POST':
        tarif.delete()
        messages.success(request, "Tarif supprimé.")
        return redirect('tarif_list')
    return render(request, 'billing/tarif_confirm_delete.html', {'tarif': tarif})