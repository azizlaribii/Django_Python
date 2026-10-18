from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from accounts.models import AssociationMedecinPatient

from .models import (
    BilanPredefini,
    DemandeAnalyse,
    ParametresLaboratoire,
    Prelevement,
    Resultat,
    TypeAnalyse,
    motifs_rejet_par_defaut,
)

User = get_user_model()


class DemandeAnalyseForm(forms.ModelForm):
    analyses = forms.ModelMultipleChoiceField(
        label="Analyses demandées",
        queryset=TypeAnalyse.objects.filter(actif=True),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    bilans = forms.ModelMultipleChoiceField(
        label="Bilans prédéfinis",
        queryset=BilanPredefini.objects.filter(actif=True),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = DemandeAnalyse
        fields = ["patient", "laboratoire", "priorite", "commentaire"]
        labels = {"commentaire": "Notes cliniques"}
        widgets = {"commentaire": forms.Textarea(attrs={"rows": 3})}

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
            if self.instance.pk:
                allowed_patients |= Q(pk=self.instance.patient_id)
            patients = patients.filter(allowed_patients)
        self.fields["patient"].queryset = patients
        self.fields["laboratoire"].queryset = User.objects.filter(
            role=User.Role.LABORATOIRE, is_active=True,
        )
        self.fields["laboratoire"].required = False
        self.fields["bilans"].queryset = BilanPredefini.objects.filter(actif=True)
        if self.instance.pk:
            self.fields["analyses"].queryset = TypeAnalyse.objects.filter(
                Q(actif=True) | Q(demandes__demande=self.instance),
            ).distinct()

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("analyses") and not cleaned_data.get("bilans"):
            self.add_error("analyses", "Choisissez au moins une analyse ou un bilan.")
        for bilan in cleaned_data.get("bilans", []):
            if not bilan.analyses.filter(actif=True).exists():
                self.add_error(
                    "bilans",
                    f"Le bilan « {bilan.nom} » ne contient aucune analyse active.",
                )
            elif bilan.analyses.filter(actif=False).exists():
                self.add_error(
                    "bilans",
                    f"Le bilan « {bilan.nom} » contient des analyses désactivées.",
                )
        return cleaned_data


class TypeAnalyseForm(forms.ModelForm):
    class Meta:
        model = TypeAnalyse
        fields = [
            "code", "nom", "description", "unite",
            "valeur_reference_min", "valeur_reference_max",
            "seuil_critique_bas", "seuil_critique_haut", "tarif", "actif",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class BilanPredefiniForm(forms.ModelForm):
    class Meta:
        model = BilanPredefini
        fields = ["nom", "description", "analyses", "actif"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "analyses": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["analyses"].required = True
        self.fields["analyses"].queryset = TypeAnalyse.objects.filter(actif=True)
        if self.instance.pk:
            self.fields["analyses"].queryset = TypeAnalyse.objects.filter(
                Q(actif=True) | Q(bilans=self.instance),
            ).distinct()


class ParametresLaboratoireForm(forms.ModelForm):
    motifs_rejet = forms.CharField(
        label="Motifs de rejet d’échantillon",
        required=False,
        help_text="Saisissez un motif par ligne.",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    class Meta:
        model = ParametresLaboratoire
        fields = [
            "nom", "adresse", "telephone", "logo",
            "entete_compte_rendu", "signature_compte_rendu",
            "motifs_rejet", "delai_alerte_urgente_minutes",
        ]
        widgets = {
            "entete_compte_rendu": forms.Textarea(attrs={"rows": 3}),
            "signature_compte_rendu": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["motifs_rejet"].initial = "\n".join(
            self.instance.motifs_rejet or []
        )

    def clean_motifs_rejet(self):
        motifs = self.cleaned_data["motifs_rejet"].splitlines()
        return list(dict.fromkeys(motif.strip() for motif in motifs if motif.strip()))


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
    patient = forms.CharField(required=False, label="Patient")
    medecin = forms.ModelChoiceField(
        required=False,
        queryset=User.objects.filter(role=User.Role.DOCTEUR).order_by(
            "last_name", "first_name", "username",
        ),
    )
    laboratoire = forms.ModelChoiceField(
        required=False,
        queryset=User.objects.filter(
            role=User.Role.LABORATOIRE, is_active=True,
        ).order_by("username"),
    )
    bloquees = forms.BooleanField(required=False, label="Demandes non attribuées")
    urgentes_en_retard = forms.BooleanField(required=False, label="Urgentes en retard")
    echantillons_rejetes = forms.BooleanField(required=False, label="Avec échantillon rejeté")
    resultats_a_valider = forms.BooleanField(required=False, label="Avec résultat à valider")

    def clean(self):
        cleaned_data = super().clean()
        date_debut = cleaned_data.get("date_debut")
        date_fin = cleaned_data.get("date_fin")
        if date_debut and date_fin and date_debut > date_fin:
            self.add_error("date_fin", "La date de fin doit suivre la date de début.")
        return cleaned_data


class RapportFilterForm(forms.Form):
    date_debut = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_fin = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        date_debut = cleaned_data.get("date_debut")
        date_fin = cleaned_data.get("date_fin")
        if date_debut and date_fin and date_debut > date_fin:
            self.add_error("date_fin", "La date de fin doit suivre la date de début.")
        return cleaned_data


class DemandeReaffectationForm(forms.Form):
    laboratoire = forms.ModelChoiceField(
        label="Réaffecter au laboratoire",
        queryset=User.objects.filter(
            role=User.Role.LABORATOIRE, is_active=True,
        ).order_by("username"),
    )


class DemandeAnnulationAdminForm(forms.Form):
    motif = forms.CharField(
        label="Motif obligatoire",
        widget=forms.Textarea(attrs={"rows": 2}),
    )


class RejetResultatForm(forms.Form):
    commentaire = forms.CharField(
        label="Commentaire obligatoire pour l’opérateur",
        min_length=3,
        widget=forms.Textarea(attrs={"rows": 2}),
    )


class PrelevementForm(forms.ModelForm):
    class Meta:
        model = Prelevement
        fields = [
            "code_prelevement", "type_prelevement", "date_prelevement",
            "date_reception", "statut", "motif_rejet", "remarque",
        ]
        widgets = {
            "date_prelevement": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"},
            ),
            "date_reception": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"},
            ),
            "remarque": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code_prelevement"].required = False
        self.fields["code_prelevement"].help_text = (
            "Laissez vide pour générer automatiquement le code-barres."
        )
        parametres = ParametresLaboratoire.objects.filter(pk=1).first()
        self.motifs_rejet = (
            parametres.motifs_rejet if parametres else motifs_rejet_par_defaut()
        )
        choices = [("", "Sélectionnez un motif de rejet")]
        choices.extend((motif, motif) for motif in self.motifs_rejet)
        if self.instance.motif_rejet and self.instance.motif_rejet not in self.motifs_rejet:
            choices.append((self.instance.motif_rejet, self.instance.motif_rejet))
        self.fields["motif_rejet"] = forms.ChoiceField(
            label="Motif du rejet",
            choices=choices,
            required=False,
        )


class ResultatForm(forms.ModelForm):
    class Meta:
        model = Resultat
        fields = ["valeur", "unite", "valeur_reference", "interpretation", "observation"]
        widgets = {"observation": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.statut in (
            Resultat.Statut.VALIDE,
            Resultat.Statut.CORRIGE,
        ):
            self.fields["observation"].required = True
            self.fields["observation"].label = "Motif de correction (obligatoire)"
