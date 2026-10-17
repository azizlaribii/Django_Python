from django import forms
from .models import Tarif


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