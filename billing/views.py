from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from .forms import TarifForm, FactureForm, LigneFormSet , PaiementForm
from .models import Tarif, Facture
from .permissions import admin_required, staff_required, billing_access_required, factures_visibles
from django.views.decorators.http import require_POST
from decimal import Decimal
from django.http import Http404
from django.contrib.auth import get_user_model

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


def _tarifs_json():
    return {str(t.pk): {'libelle': t.libelle, 'prix': str(t.prix)}
            for t in Tarif.objects.filter(actif=True)}


@staff_required
def facture_create(request):
    form = FactureForm(request.POST or None, user=request.user)
    formset = LigneFormSet(request.POST or None, prefix='lignes')

    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            facture = form.save(commit=False)
            if request.user.is_doctor:
                facture.medecin = request.user
            facture.save()
            formset.instance = facture
            formset.save()
        messages.success(request, f"Facture {facture.numero} créée.")
        return redirect('facture_detail', pk=facture.pk)

    return render(request, 'billing/facture_form.html',
                  {'form': form, 'formset': formset, 'tarifs_json': _tarifs_json()})



@staff_required
def facture_update(request, pk):
    facture = get_object_or_404(factures_visibles(request.user), pk=pk)
    if facture.statut != Facture.Statut.EN_ATTENTE:
        messages.error(request, "Cette facture n'est plus modifiable.")
        return redirect('facture_detail', pk=pk)

    form = FactureForm(request.POST or None, instance=facture, user=request.user)
    formset = LigneFormSet(request.POST or None, instance=facture, prefix='lignes')
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            form.save()
            formset.save()
        messages.success(request, "Facture modifiée.")
        return redirect('facture_detail', pk=pk)
    return render(request, 'billing/facture_form.html',
                  {'form': form, 'formset': formset, 'facture': facture,
                   'tarifs_json': _tarifs_json()})


@staff_required
@require_POST
def facture_cancel(request, pk):
    facture = get_object_or_404(factures_visibles(request.user), pk=pk)
    if facture.statut != Facture.Statut.EN_ATTENTE:
        messages.error(request, "Impossible d'annuler : la facture a des paiements.")
    else:
        facture.statut = Facture.Statut.ANNULEE
        facture.save(update_fields=['statut'])
        messages.success(request, f"Facture {facture.numero} annulée.")
    return redirect('facture_detail', pk=pk)





@staff_required
def paiement_create(request, pk):
    facture = get_object_or_404(factures_visibles(request.user), pk=pk)
    if facture.statut in (Facture.Statut.ANNULEE, Facture.Statut.PAYEE):
        messages.error(request, "Aucun paiement possible sur cette facture.")
        return redirect('facture_detail', pk=pk)

    form = PaiementForm(request.POST or None, facture=facture)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            paiement = form.save(commit=False)
            paiement.facture = facture
            paiement.enregistre_par = request.user
            paiement.save()
        messages.success(request, "Paiement enregistré.")
        return redirect('facture_detail', pk=pk)
    return render(request, 'billing/paiement_form.html', {'form': form, 'facture': facture})


@billing_access_required
def patient_historique(request, patient_id=None):
    if request.user.is_patient:
        if patient_id not in (None, request.user.pk):
            raise Http404
        patient = request.user
    else:
        patient = get_object_or_404(get_user_model(), pk=patient_id, role='PATIENT')

    factures = (factures_visibles(request.user)
                .filter(patient=patient).prefetch_related('lignes', 'paiements'))
    actives = [f for f in factures if f.statut != Facture.Statut.ANNULEE]
    total_facture = sum((f.total_ttc for f in actives), Decimal('0'))
    total_encaisse = sum((f.total_paye() for f in actives), Decimal('0'))
    return render(request, 'billing/patient_historique.html', {
        'patient': patient, 'factures': factures,
        'total_facture': total_facture, 'total_encaisse': total_encaisse,
        'total_reste': total_facture - total_encaisse,
    })