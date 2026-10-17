from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from accounts.models import AssociationMedecinPatient

from .models import DemandeAnalyse, Prelevement, Resultat, TypeAnalyse

User = get_user_model()


class DemandeAnalyseForm(forms.ModelForm):
    analyses = forms.ModelMultipleChoiceField(
        label="Analyses demandées",
        queryset=TypeAnalyse.objects.filter(actif=True),
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = DemandeAnalyse
        fields = ["patient", "laboratoire", "priorite", "commentaire"]
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
        if self.instance.pk:
            self.fields["analyses"].queryset = TypeAnalyse.objects.filter(
                Q(actif=True) | Q(demandes__demande=self.instance),
            ).distinct()


class TypeAnalyseForm(forms.ModelForm):
    class Meta:
        model = TypeAnalyse
        fields = [
            "code", "nom", "description", "unite",
            "valeur_reference_min", "valeur_reference_max", "tarif", "actif",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


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
            "motif_rejet": forms.Textarea(attrs={"rows": 2}),
            "remarque": forms.Textarea(attrs={"rows": 2}),
        }


class ResultatForm(forms.ModelForm):
    class Meta:
        model = Resultat
        fields = ["valeur", "unite", "valeur_reference", "interpretation", "observation"]
        widgets = {"observation": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.statut == Resultat.Statut.VALIDE:
            self.fields["observation"].required = True
            self.fields["observation"].label = "Motif de correction (obligatoire)"
