from django import forms
from django.utils import timezone

from .models import MOTIFS_ENTREE, MOTIFS_SORTIE, Categorie, MouvementStock, Produit


def _styler(form):
    for field in form.fields.values():
        w = field.widget
        if isinstance(w, forms.Select):
            w.attrs.setdefault("class", "form-select")
        else:
            w.attrs.setdefault("class", "form-input")


class ProduitForm(forms.ModelForm):
    quantite_initiale = forms.IntegerField(
        label="Quantité initiale en stock", min_value=0, initial=0, required=False,
        help_text="Enregistrée comme première entrée dans l’historique.",
    )

    class Meta:
        model = Produit
        fields = [
            "nom", "reference", "categorie", "unite", "quantite_initiale",
            "seuil_alerte", "date_peremption", "fournisseur", "emplacement",
            "prix_unitaire", "description",
        ]
        widgets = {
            "date_peremption": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:  # la quantité ne se modifie que par des mouvements
            del self.fields["quantite_initiale"]
        _styler(self)

    def clean_date_peremption(self):
        date = self.cleaned_data.get("date_peremption")
        if date and not self.instance.pk and date < timezone.localdate():
            raise forms.ValidationError("La date de péremption est déjà dépassée.")
        return date


class MouvementForm(forms.Form):
    quantite = forms.IntegerField(label="Quantité", min_value=1)
    motif = forms.ChoiceField(label="Motif")
    numero_lot = forms.CharField(label="N° de lot", max_length=50, required=False)
    commentaire = forms.CharField(label="Commentaire", max_length=255, required=False)

    def __init__(self, *args, type_mouvement, **kwargs):
        super().__init__(*args, **kwargs)
        codes = MOTIFS_ENTREE if type_mouvement == MouvementStock.Type.ENTREE else MOTIFS_SORTIE
        labels = dict(MouvementStock.Motif.choices)
        # « Stock initial » est réservé à la création du produit
        self.fields["motif"].choices = [(c, labels[c]) for c in codes if c != "INITIAL"]
        if type_mouvement == MouvementStock.Type.SORTIE:
            del self.fields["numero_lot"]
        _styler(self)


class CategorieForm(forms.ModelForm):
    class Meta:
        model = Categorie
        fields = ["nom", "description"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _styler(self)
        self.fields["nom"].widget.attrs["placeholder"] = "Nom de la catégorie"
        self.fields["description"].widget.attrs["placeholder"] = "Description (facultatif)"
