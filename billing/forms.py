from django import forms
from django.forms import inlineformset_factory
from .models import Tarif, Facture, LigneFacture, Paiement

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
    def clean_remise(self):
        v = self.cleaned_data['remise']
        if v < 0:
            raise forms.ValidationError("La remise ne peut pas être négative.")
        return v

    def clean_tva(self):
        v = self.cleaned_data['tva']
        if not 0 <= v <= 100:
            raise forms.ValidationError("La TVA doit être comprise entre 0 et 100.")
        return v        


class LigneFactureForm(forms.ModelForm):
    class Meta:
        model = LigneFacture
        fields = ['tarif', 'description', 'reference', 'quantite', 'prix_unitaire']
        widgets = {
            'tarif': forms.Select(attrs={'class': 'form-input', 'aria-label': 'Tarif'}),
            'description': forms.TextInput(attrs={'class': 'form-input', 'aria-label': 'Description'}),
            'reference': forms.TextInput(attrs={'class': 'form-input', 'aria-label': 'Référence'}),
            'quantite': forms.NumberInput(attrs={'class': 'form-input', 'min': '1', 'aria-label': 'Quantité'}),
            'prix_unitaire': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.001', 'min': '0', 'aria-label': 'Prix unitaire'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tarif'].queryset = Tarif.objects.filter(actif=True)

    def clean_quantite(self):
        v = self.cleaned_data['quantite']
        if v < 1:
            raise forms.ValidationError("La quantité doit être d'au moins 1.")
        return v

    def clean_prix_unitaire(self):
        v = self.cleaned_data['prix_unitaire']
        if v < 0:
            raise forms.ValidationError("Le prix ne peut pas être négatif.")
        return v    


LigneFormSet = inlineformset_factory(
    Facture, LigneFacture, form=LigneFactureForm,
    extra=1, can_delete=True, min_num=1, validate_min=True,
)



class PaiementForm(forms.ModelForm):
    class Meta:
        model = Paiement
        fields = ['montant', 'mode']
        widgets = {
            'montant': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.001', 'min': '0.001'}),
            'mode': forms.Select(attrs={'class': 'form-input'}),
        }

    def __init__(self, *args, facture=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.facture = facture

    def clean_montant(self):
        montant = self.cleaned_data['montant']
        reste = self.facture.reste_a_payer()
        if montant > reste:
            raise forms.ValidationError(f"Le montant dépasse le reste à payer ({reste:.3f} TND).")
        return montant