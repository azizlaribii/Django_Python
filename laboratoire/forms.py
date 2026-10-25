import re
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.html import format_html

from accounts.models import AssociationMedecinPatient

from .models import (
    AnalyseDemandee,
    BilanPredefini,
    DemandeAnalyse,
    ParametresLaboratoire,
    Prelevement,
    Resultat,
    TypeAnalyse,
    motifs_rejet_par_defaut,
)

User = get_user_model()

_VALEUR_NUMERIQUE = re.compile(
    r"^[<>≤≥]?\s*[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?$"
)


def _valeur_resultat_valide(value):
    if not any(character.isdigit() for character in value):
        return True
    if not _VALEUR_NUMERIQUE.fullmatch(value):
        return False
    numeric_text = value.lstrip("<>≤≥").strip().replace(",", ".")
    try:
        return Decimal(numeric_text).is_finite()
    except InvalidOperation:
        return False


class BilanPredefiniChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        analyses = ", ".join(
            analyse.nom for analyse in obj.analyses.all() if analyse.actif
        )
        if analyses:
            return format_html("{} <small>({})</small>", obj.nom, analyses)
        return obj.nom


class TypeAnalyseChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return format_html("{} <small>{}</small>", obj.nom, obj.code)


class BilanPredefiniCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.analysis_map = {}

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs,
        )
        option["attrs"]["data-analysis-ids"] = " ".join(
            str(pk) for pk in self.analysis_map.get(str(value), ())
        )
        return option


class DemandeAnalyseForm(forms.ModelForm):
    commentaire = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={
            "rows": 3,
            "maxlength": 2000,
            "placeholder": "Ex : suspicion d’infection, bilan de contrôle, diabète non équilibré...",
        }),
    )
    analyses = TypeAnalyseChoiceField(
        label="Analyses demandées",
        queryset=TypeAnalyse.objects.filter(actif=True),
        required=False,
        widget=forms.CheckboxSelectMultiple(
            attrs={"class": "lab-request-checkboxes"},
        ),
        help_text="",
    )
    bilans = BilanPredefiniChoiceField(
        label="Bilans prédéfinis",
        queryset=BilanPredefini.objects.filter(actif=True),
        required=False,
        widget=BilanPredefiniCheckboxSelectMultiple(
            attrs={"class": "lab-request-checkboxes"},
        ),
        help_text="Les analyses des bilans sélectionnés sont ajoutées automatiquement.",
    )

    class Meta:
        model = DemandeAnalyse
        fields = ["patient", "priorite", "commentaire"]
        labels = {
            "patient": "Patient concerné",
            "priorite": "Niveau de priorité",
            "commentaire": "Motif médical et informations cliniques",
        }
        help_texts = {
            "commentaire": "Obligatoire si la priorité est urgente.",
        }
    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        patients = User.objects.filter(role=User.Role.PATIENT, is_active=True)
        if user and user.is_doctor:
            allowed_patients = Q(
                pk__in=AssociationMedecinPatient.objects.filter(
                    medecin=user,
                ).values("patient_id")
            )
            patients = patients.filter(allowed_patients)
        if self.instance.pk:
            patients = patients.filter(pk=self.instance.patient_id)
        self.fields["patient"].queryset = patients
        self.fields["patient"].empty_label = "— Choisir un patient —"
        if self.instance.pk:
            self.fields["patient"].disabled = True
            self.fields["patient"].help_text = (
                "Patient actuel : "
                f"{self.instance.patient.get_full_name() or self.instance.patient.username}. "
                "Le patient ne peut pas être changé après la création de la demande."
            )
        bilans = BilanPredefini.objects.filter(
            actif=True,
        ).prefetch_related("analyses")
        self.fields["bilans"].queryset = bilans
        self.fields["bilans"].widget.analysis_map = {
            str(bilan.pk): list(
                bilan.analyses.filter(actif=True).values_list("pk", flat=True)
            )
            for bilan in bilans
        }
        if self.instance.pk:
            self.fields["analyses"].queryset = TypeAnalyse.objects.filter(
                Q(actif=True) | Q(demandes__demande=self.instance),
            ).distinct()
            if not self.is_bound:
                active_analysis_ids = set(
                    self.instance.analyses.exclude(
                        statut=AnalyseDemandee.Statut.ANNULEE,
                    ).values_list("type_analyse_id", flat=True)
                )
                inferred_bilans = []
                for bilan in bilans:
                    analysis_ids = set(
                        self.fields["bilans"].widget.analysis_map[str(bilan.pk)]
                    )
                    if analysis_ids and analysis_ids.issubset(active_analysis_ids):
                        inferred_bilans.append(bilan.pk)
                self.initial["bilans"] = inferred_bilans

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("analyses") and not cleaned_data.get("bilans"):
            raise forms.ValidationError(
                "Veuillez sélectionner au moins une analyse individuelle ou un bilan prédéfini.",
                code="required"
            )
        for bilan in cleaned_data.get("bilans", []):
            if not bilan.analyses.filter(actif=True).exists():
                raise forms.ValidationError(
                    f"Le bilan « {bilan.nom} » ne contient aucune analyse active. "
                    f"Veuillez en sélectionner un autre ou des analyses individuelles.",
                    code="bilan_inactif"
                )
            elif bilan.analyses.filter(actif=False).exists():
                self.add_warning = forms.ValidationError(
                    f"Attention : Le bilan « {bilan.nom} » contient des analyses désactivées qui seront ignorées.",
                    code="warning"
                )
        return cleaned_data


class TypeAnalyseForm(forms.ModelForm):
    description = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": 2000}),
    )

    class Meta:
        model = TypeAnalyse
        fields = [
            "code", "nom", "description", "unite",
            "type_echantillon",
            "valeur_reference_min", "valeur_reference_max",
            "seuil_critique_bas", "seuil_critique_haut", "tarif", "actif",
        ]
        labels = {
            "code": "Code de l’analyse",
            "nom": "Nom de l’analyse",
            "description": "Description",
            "unite": "Unité de mesure",
            "type_echantillon": "Catégorie d’échantillon",
            "valeur_reference_min": "Référence minimale",
            "valeur_reference_max": "Référence maximale",
            "seuil_critique_bas": "Seuil critique bas",
            "seuil_critique_haut": "Seuil critique haut",
            "tarif": "Tarif (€)",
            "actif": "Analyse active et disponible à la prescription",
        }
        help_texts = {
            "code": "Code unique utilisé pour identifier cette analyse.",
            "unite": "Exemple : g/L, mmol/L ou U/L.",
            "valeur_reference_min": "Laissez vide si aucune limite minimale n’est définie.",
            "valeur_reference_max": "Laissez vide si aucune limite maximale n’est définie.",
            "seuil_critique_bas": "Laissez vide si aucun seuil critique bas n’est défini.",
            "seuil_critique_haut": "Laissez vide si aucun seuil critique haut n’est défini.",
            "actif": "Désactivez pour archiver sans supprimer les historiques associés.",
        }
        widgets = {
            "code": forms.TextInput(attrs={"autocomplete": "off"}),
            "nom": forms.TextInput(attrs={"autocomplete": "off"}),
            "unite": forms.TextInput(attrs={"placeholder": "Ex. g/L"}),
            "valeur_reference_min": forms.NumberInput(attrs={
                "step": "any",
                "inputmode": "decimal",
            }),
            "valeur_reference_max": forms.NumberInput(attrs={
                "step": "any",
                "inputmode": "decimal",
            }),
            "seuil_critique_bas": forms.NumberInput(attrs={
                "step": "any",
                "inputmode": "decimal",
            }),
            "seuil_critique_haut": forms.NumberInput(attrs={
                "step": "any",
                "inputmode": "decimal",
            }),
            "tarif": forms.NumberInput(attrs={
                "step": "0.01",
                "min": "0",
                "inputmode": "decimal",
            }),
        }


class BilanPredefiniForm(forms.ModelForm):
    description = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": 2000}),
    )

    class Meta:
        model = BilanPredefini
        fields = ["nom", "description", "analyses", "actif"]
        widgets = {
            "analyses": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["analyses"].required = True
        self.fields["nom"].help_text = "Le nom du bilan doit être unique."
        self.fields["description"].help_text = (
            "Décrivez brièvement l’objectif ou le contenu du bilan."
        )
        self.fields["actif"].label = "Bilan actif et disponible à la prescription"
        self.fields["actif"].help_text = (
            "Désactivez pour archiver sans supprimer les prescriptions historiques."
        )
        self.fields["analyses"].queryset = TypeAnalyse.objects.filter(actif=True)
        if self.instance.pk:
            self.fields["analyses"].queryset = TypeAnalyse.objects.filter(
                Q(actif=True) | Q(bilans=self.instance),
            ).distinct()

    def clean(self):
        cleaned_data = super().clean()
        analyses = cleaned_data.get("analyses")
        if (
            cleaned_data.get("actif")
            and analyses is not None
            and not analyses.filter(actif=True).exists()
        ):
            self.add_error(
                "analyses",
                "Un bilan actif doit contenir au moins une analyse active.",
            )
        return cleaned_data


class ParametresLaboratoireForm(forms.ModelForm):
    entete_compte_rendu = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": 2000}),
    )
    signature_compte_rendu = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": 2000}),
    )
    motifs_rejet = forms.CharField(
        label="Motifs de rejet d’échantillon",
        required=False,
        help_text="Saisissez un motif par ligne.",
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 4, "maxlength": 4000}),
    )

    class Meta:
        model = ParametresLaboratoire
        fields = [
            "nom", "adresse", "telephone", "logo",
            "entete_compte_rendu", "signature_compte_rendu",
            "motifs_rejet", "delai_alerte_urgente_minutes",
        ]
        widgets = {
            "telephone": forms.TextInput(attrs={
                "type": "tel",
                "maxlength": 30,
                "autocomplete": "tel",
            }),
            "logo": forms.FileInput(attrs={
                "accept": ".png,.jpg,.jpeg,.webp",
            }),
            "delai_alerte_urgente_minutes": forms.NumberInput(attrs={
                "min": 1,
                "step": 1,
                "inputmode": "numeric",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["motifs_rejet"].initial = "\n".join(
            self.instance.motifs_rejet or []
        )

    def clean_motifs_rejet(self):
        motifs = self.cleaned_data["motifs_rejet"].splitlines()
        motifs = list(dict.fromkeys(motif.strip() for motif in motifs if motif.strip()))
        if len(motifs) > 30:
            raise forms.ValidationError("Saisissez 30 motifs de rejet au maximum.")
        if any(len(motif) > 120 for motif in motifs):
            raise forms.ValidationError(
                "Chaque motif de rejet doit contenir 120 caractères au maximum."
            )
        return motifs


class SupervisionFilterForm(forms.Form):
    date_debut = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_fin = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    statut = forms.ChoiceField(
        required=False,
        choices=[("", "Tous les statuts"), *DemandeAnalyse.Statut.choices],
    )
    priorite = forms.ChoiceField(
        required=False,
        choices=[("", "Toutes les priorités"), *DemandeAnalyse.Priorite.choices],
    )
    patient = forms.CharField(
        required=False,
        label="Patient",
        max_length=100,
        widget=forms.TextInput(attrs={"maxlength": 100, "autocomplete": "off"}),
    )
    medecin = forms.ModelChoiceField(
        required=False,
        queryset=User.objects.filter(role=User.Role.DOCTEUR).order_by(
            "last_name", "first_name", "username",
        ),
    )
    def clean(self):
        cleaned_data = super().clean()
        date_debut = cleaned_data.get("date_debut")
        date_fin = cleaned_data.get("date_fin")
        if date_debut and date_fin and date_debut > date_fin:
            self.add_error("date_fin", "La date de fin doit suivre la date de début.")
        return cleaned_data


class RapportFilterForm(forms.Form):
    date_debut = forms.DateField(
        required=False,
        label="Depuis le",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_fin = forms.DateField(
        required=False,
        label="Jusqu’au",
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        date_debut = cleaned_data.get("date_debut")
        date_fin = cleaned_data.get("date_fin")
        if date_debut and date_fin and date_debut > date_fin:
            self.add_error("date_fin", "La date de fin doit suivre la date de début.")
        return cleaned_data


class DemandeListFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        max_length=120,
        label="Patient ou commentaire",
        widget=forms.SearchInput(attrs={"maxlength": 120}),
    )
    date_debut = forms.DateField(
        required=False,
        label="Créé à partir du",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_fin = forms.DateField(
        required=False,
        label="Créé jusqu’au",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    statut = forms.ChoiceField(
        required=False,
        choices=[("", "Tous les statuts"), *DemandeAnalyse.Statut.choices],
    )
    priorite = forms.ChoiceField(
        required=False,
        choices=[("", "Toutes les priorités"), *DemandeAnalyse.Priorite.choices],
    )

    def clean(self):
        cleaned_data = super().clean()
        date_debut = cleaned_data.get("date_debut")
        date_fin = cleaned_data.get("date_fin")
        if date_debut and date_fin and date_debut > date_fin:
            self.add_error("date_fin", "La date de fin doit suivre la date de début.")
        return cleaned_data


class PrelevementListFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        max_length=120,
        label="Code ou patient",
        widget=forms.SearchInput(attrs={"maxlength": 120}),
    )
    onglet = forms.ChoiceField(
        required=False,
        choices=[
            ("a_traiter", "À traiter"),
            ("resultats", "Résultats à saisir"),
            ("clotures", "Clôturés"),
        ],
        initial="a_traiter",
    )
    statut = forms.ChoiceField(required=False)
    date_debut = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_fin = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        onglet = self.data.get("onglet", self.initial.get("onglet", "a_traiter"))
        statuts_par_onglet = {
            "a_traiter": [
                Prelevement.Statut.A_EFFECTUER,
                Prelevement.Statut.PRELEVE,
            ],
            "resultats": [Prelevement.Statut.RECU],
            "clotures": [
                Prelevement.Statut.TERMINE,
                Prelevement.Statut.REJETE,
                Prelevement.Statut.ANNULE,
            ],
        }
        if onglet not in statuts_par_onglet:
            onglet = "a_traiter"
        self.fields["statut"].choices = [
            ("", "Tous les statuts de l’onglet"),
            *[
                (status, label)
                for status, label in Prelevement.Statut.choices
                if status in statuts_par_onglet[onglet]
            ],
        ]

    def clean(self):
        cleaned_data = super().clean()
        date_debut = cleaned_data.get("date_debut")
        date_fin = cleaned_data.get("date_fin")
        if date_debut and date_fin and date_debut > date_fin:
            self.add_error("date_fin", "La date de fin doit suivre la date de début.")
        return cleaned_data


class ResultatsPatientFilterForm(forms.Form):
    analyse = forms.ChoiceField(
        required=False,
        label="Type d’analyse à comparer",
    )
    date_debut = forms.DateField(
        required=False,
        label="Du",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_fin = forms.DateField(
        required=False,
        label="Au",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    type_legacy = forms.CharField(
        required=False,
        max_length=100,
        label="Autre type d’analyse",
        widget=forms.SearchInput(attrs={"maxlength": 100}),
    )

    def __init__(self, *args, types_analyse, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["analyse"].choices = [
            ("", "Choisir une analyse"),
            *((str(item.pk), item.nom) for item in types_analyse),
        ]

    def clean(self):
        cleaned_data = super().clean()
        date_debut = cleaned_data.get("date_debut")
        date_fin = cleaned_data.get("date_fin")
        if date_debut and date_fin and date_debut > date_fin:
            self.add_error("date_fin", "La date de fin doit suivre la date de début.")
        return cleaned_data


class DoctorHistoryFilterForm(forms.Form):
    analyse = forms.ChoiceField(required=False, label="Analyse")

    def __init__(self, *args, types_analyse, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["analyse"].choices = [
            ("", "Toutes les analyses"),
            *((str(item.pk), item.nom) for item in types_analyse),
        ]


class HistoriqueFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        max_length=120,
        label="Recherche dans le journal",
        widget=forms.SearchInput(attrs={"maxlength": 120}),
    )


class DemandeAnnulationForm(forms.Form):
    motif = forms.CharField(
        label="Motif d’annulation",
        min_length=3,
        max_length=1000,
        widget=forms.Textarea(attrs={
            "rows": 3,
            "minlength": 3,
            "maxlength": 1000,
            "required": True,
        }),
    )

    def clean_motif(self):
        motif = self.cleaned_data["motif"].strip()
        if len(motif) < 3:
            raise forms.ValidationError("Le motif doit contenir au moins 3 caractères.")
        return motif


class RejetResultatForm(forms.Form):
    commentaire = forms.CharField(
        label="Commentaire obligatoire pour l’opérateur",
        min_length=3,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2, "minlength": 3, "maxlength": 1000}),
    )


class PrelevementForm(forms.ModelForm):
    precision_type = forms.CharField(
        required=False,
        max_length=120,
        widget=forms.TextInput(attrs={"maxlength": 120}),
    )
    remarque = forms.CharField(
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2, "maxlength": 1000}),
    )

    class Meta:
        model = Prelevement
        fields = [
            "type_prelevement", "precision_type", "remarque",
        ]
        widgets = {
            "remarque": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["precision_type"].help_text = (
            "Précisez le type d’échantillon lorsque « Autre » est sélectionné."
        )
        if self.instance.statut == Prelevement.Statut.REJETE:
            parametres = ParametresLaboratoire.objects.filter(pk=1).first()
            motifs = parametres.motifs_rejet if parametres else motifs_rejet_par_defaut()
            self.fields["motif_rejet"] = forms.ChoiceField(
                label="Motif du refus",
                choices=[(motif, motif) for motif in motifs],
                initial=self.instance.motif_rejet,
            )
            self.fields["remarque"].required = self.instance.motif_rejet == "Autre"

    def clean(self):
        cleaned_data = super().clean()
        sample_type = cleaned_data.get("type_prelevement")
        if (
            sample_type == Prelevement.Type.AUTRE
            and not cleaned_data.get("precision_type", "").strip()
        ):
            self.add_error(
                "precision_type",
                "Précisez le type d’échantillon lorsque « Autre » est sélectionné.",
            )
        if sample_type and self.instance.pk:
            incompatible_analysis = self.instance.analyses.exclude(
                statut=AnalyseDemandee.Statut.ANNULEE,
            ).exclude(type_analyse__type_echantillon=sample_type).exists()
            if incompatible_analysis:
                self.add_error(
                    "type_prelevement",
                    "Le type d’échantillon ne correspond pas aux analyses associées.",
                )
        return cleaned_data


class RejetPrelevementForm(forms.Form):
    motif = forms.ChoiceField(label="Motif du refus")
    remarque = forms.CharField(
        label="Précision",
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2, "maxlength": 1000}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        settings = ParametresLaboratoire.objects.filter(pk=1).first()
        motifs = settings.motifs_rejet if settings else motifs_rejet_par_defaut()
        self.fields["motif"].choices = [("", "— Choisir un motif —")] + [
            (motif, motif) for motif in motifs
        ]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("motif") == "Autre" and not cleaned.get("remarque", "").strip():
            self.add_error("remarque", "Précisez le motif choisi « Autre ».")
        return cleaned


class PrelevementResultatsForm(forms.Form):
    def __init__(self, *args, analyses, publier=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.analyses = list(analyses)
        self.publier = publier
        for analyse in self.analyses:
            resultat = analyse.resultats.filter(
                statut=Resultat.Statut.EN_SAISIE,
            ).first()
            self.fields[f"valeur_{analyse.pk}"] = forms.CharField(
                label=f"{analyse.type_analyse.nom} ({analyse.type_analyse.code})",
                max_length=255,
                required=publier,
                initial=resultat.valeur if resultat else "",
            )
            self.fields[f"unite_{analyse.pk}"] = forms.CharField(
                label="Unité",
                required=False,
                max_length=30,
                widget=forms.TextInput(attrs={"maxlength": 30}),
                initial=(
                    resultat.unite if resultat and resultat.unite
                    else analyse.type_analyse.unite
                ),
            )
            reference = ""
            if analyse.type_analyse.valeur_reference_min is not None or analyse.type_analyse.valeur_reference_max is not None:
                reference = (
                    f"{analyse.type_analyse.valeur_reference_min if analyse.type_analyse.valeur_reference_min is not None else '—'}"
                    f" – {analyse.type_analyse.valeur_reference_max if analyse.type_analyse.valeur_reference_max is not None else '—'}"
                )
                if analyse.type_analyse.unite:
                    reference += f" {analyse.type_analyse.unite}"
            self.fields[f"valeur_reference_{analyse.pk}"] = forms.CharField(
                label="Valeurs de référence",
                required=False,
                max_length=120,
                widget=forms.TextInput(attrs={"maxlength": 120}),
                initial=(
                    resultat.valeur_reference if resultat and resultat.valeur_reference
                    else reference
                ),
            )
            self.fields[f"observation_{analyse.pk}"] = forms.CharField(
                label="Commentaire / observation",
                required=False,
                max_length=2000,
                widget=forms.Textarea(attrs={"rows": 2}),
                initial=resultat.observation if resultat else "",
            )
            self.fields[f"valeur_{analyse.pk}"].widget.attrs.update({
                "inputmode": "decimal",
                "maxlength": 255,
                "autocomplete": "off",
            })
            if publier:
                self.fields[f"valeur_{analyse.pk}"].required = True
                if analyse.type_analyse.unite:
                    self.fields[f"unite_{analyse.pk}"].required = True

    def clean(self):
        cleaned_data = super().clean()
        if not self.publier and not any(
            cleaned_data.get(f"valeur_{analyse.pk}", "").strip()
            for analyse in self.analyses
        ):
            raise forms.ValidationError(
                "Saisissez au moins une valeur avant d’enregistrer le brouillon."
            )
        for analyse in self.analyses:
            value = cleaned_data.get(f"valeur_{analyse.pk}", "").strip()
            unit = cleaned_data.get(f"unite_{analyse.pk}", "").strip()
            configured_unit = analyse.type_analyse.unite.strip()
            if value and not _valeur_resultat_valide(value):
                self.add_error(
                    f"valeur_{analyse.pk}",
                    "Saisissez un nombre valide (ex. 1,25 ou <0,1) ou un résultat qualitatif sans chiffres.",
                )
            if (
                self.publier
                and configured_unit
                and unit
                and unit.casefold() != configured_unit.casefold()
            ):
                self.add_error(
                    f"unite_{analyse.pk}",
                    f"L’unité doit correspondre au catalogue : {configured_unit}.",
                )
        return cleaned_data


class ResultatForm(forms.ModelForm):
    motif_correction = forms.CharField(
        label="Motif de correction",
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2, "maxlength": 1000}),
    )
    observation = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": 2000}),
    )

    class Meta:
        model = Resultat
        fields = ["valeur", "unite", "valeur_reference", "interpretation", "observation"]
        labels = {
            "valeur": "Valeur mesurée",
            "unite": "Unité de mesure",
            "valeur_reference": "Valeurs de référence",
            "interpretation": "Interprétation (optionnel)",
            "observation": "Observations et commentaires",
        }
        help_texts = {
            "valeur": "Saisissez le résultat numérique ou qualitatif (ex: 15.5 ou Positif)",
            "interpretation": "L'interprétation automatique sera calculée selon les seuils",
            "observation": "Commentaires libres sur ce résultat",
        }
        widgets = {
            "observation": forms.Textarea(attrs={
                "rows": 3,
                "maxlength": 2000,
                "placeholder": "Observations techniques, conditions particulières...",
            }),
            "interpretation": forms.TextInput(attrs={"placeholder": "Optionnel"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Pré-remplir l'unité et les valeurs de référence pour les nouveaux résultats
        if not self.instance.pk and hasattr(self.instance, 'analyse_demandee'):
            type_analyse = self.instance.analyse_demandee.type_analyse

            # Pré-remplir l'unité
            if type_analyse.unite:
                self.initial["unite"] = type_analyse.unite
                self.fields["unite"].help_text = f"Unité du catalogue : {type_analyse.unite}"

            # Pré-remplir les valeurs de référence
            if (
                type_analyse.valeur_reference_min is not None
                and type_analyse.valeur_reference_max is not None
            ):
                self.initial["valeur_reference"] = (
                    f"{type_analyse.valeur_reference_min} - {type_analyse.valeur_reference_max} {type_analyse.unite or ''}".strip()
                )
            elif type_analyse.valeur_reference_min is not None:
                self.initial["valeur_reference"] = f"> {type_analyse.valeur_reference_min} {type_analyse.unite or ''}".strip()
            elif type_analyse.valeur_reference_max is not None:
                self.initial["valeur_reference"] = f"< {type_analyse.valeur_reference_max} {type_analyse.unite or ''}".strip()

        if (
            self.instance.pk
            and self.instance.statut == Resultat.Statut.VALIDE
        ):
            self.fields["motif_correction"].required = True

    def clean_valeur(self):
        """Validation de la valeur avec détection des seuils critiques"""
        valeur = self.cleaned_data.get("valeur", "").strip()
        if not valeur:
            raise forms.ValidationError("La valeur du résultat est obligatoire.")
        if not _valeur_resultat_valide(valeur):
            raise forms.ValidationError(
                "Saisissez un nombre valide (ex. 1,25 ou <0,1) ou un résultat qualitatif sans chiffres."
            )
        return valeur

    def clean_unite(self):
        unite = self.cleaned_data.get("unite", "").strip()
        analyse = getattr(self.instance, "analyse_demandee", None)
        if analyse and analyse.type_analyse.unite:
            expected = analyse.type_analyse.unite.strip()
            if unite.casefold() != expected.casefold():
                raise forms.ValidationError(
                    f"L’unité doit correspondre au catalogue : {expected}."
                )
        return unite
