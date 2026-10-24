from django import forms
from django.forms import inlineformset_factory

from .models import Tarif, Facture, LigneFacture


class TarifForm(forms.ModelForm):
    class Meta:
        model = Tarif
        fields = ['code', 'libelle', 'categorie', 'prix', 'actif']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-input'}),
            'libelle': forms.TextInput(attrs={'class': 'form-input'}),
            'categorie': forms.Select(attrs={'class': 'form-input'}),
            'prix': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.001', 'min': '0'}),
        }


class FactureForm(forms.ModelForm):
    class Meta:
        model = Facture
        fields = ['patient', 'medecin', 'remise', 'tva']
        widgets = {
            'patient': forms.Select(attrs={'class': 'form-input'}),
            'medecin': forms.Select(attrs={'class': 'form-input'}),
            'remise': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.001', 'min': '0'}),
            'tva': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0', 'max': '100'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Un docteur ne choisit pas le médecin : c'est lui.
        if user is not None and user.is_doctor:
            del self.fields['medecin']


class LigneFactureForm(forms.ModelForm):
    class Meta:
        model = LigneFacture
        fields = ['tarif', 'description', 'reference', 'quantite', 'prix_unitaire']
        widgets = {
            'tarif': forms.Select(attrs={'class': 'form-input'}),
            'description': forms.TextInput(attrs={'class': 'form-input'}),
            'reference': forms.TextInput(attrs={'class': 'form-input'}),
            'quantite': forms.NumberInput(attrs={'class': 'form-input', 'min': '1'}),
            'prix_unitaire': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.001', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tarif'].queryset = Tarif.objects.filter(actif=True)


LigneFormSet = inlineformset_factory(
    Facture, LigneFacture, form=LigneFactureForm,
    extra=1, can_delete=True, min_num=1, validate_min=True,
)