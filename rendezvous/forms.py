from datetime import datetime, time, timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Creneau, RendezVous

User = get_user_model()

JOURS = [(0, "Lun"), (1, "Mar"), (2, "Mer"), (3, "Jeu"), (4, "Ven"), (5, "Sam"), (6, "Dim")]
DUREES = [(15, "15 min"), (20, "20 min"), (30, "30 min"), (45, "45 min"), (60, "1 h")]


def _styler(form):
    for field in form.fields.values():
        w = field.widget
        if isinstance(w, forms.CheckboxSelectMultiple):
            continue
        if isinstance(w, forms.Select):
            w.attrs.setdefault("class", "form-select")
        else:
            w.attrs.setdefault("class", "form-input")


def medecins_qs():
    return User.objects.filter(role=User.Role.DOCTEUR, is_active=True).order_by("last_name", "first_name", "username")


def patients_qs():
    return User.objects.filter(role=User.Role.PATIENT, is_active=True).order_by("last_name", "first_name", "username")


class NomCompletChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.get_full_name() or obj.username


class MedecinChoiceField(NomCompletChoiceField):
    def label_from_instance(self, obj):
        nom = obj.get_full_name() or obj.username
        profil = getattr(obj, "doctor_profile", None)
        return f"Dr {nom} — {profil.specialite}" if profil else f"Dr {nom}"


class ReservationForm(forms.Form):
    patient = NomCompletChoiceField(queryset=patients_qs(), label="Patient")
    motif = forms.CharField(
        label="Motif de consultation", max_length=255,
        widget=forms.TextInput(attrs={"placeholder": "Ex. : contrôle annuel, douleurs abdominales…"}),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        if user.is_patient:
            del self.fields["patient"]
        else:
            self.fields["patient"].queryset = patients_qs()
        _styler(self)


class AnnulationForm(forms.Form):
    motif_annulation = forms.CharField(
        label="Motif d'annulation", max_length=255, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Facultatif"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _styler(self)


class DeplacementForm(forms.Form):
    creneau = forms.IntegerField(widget=forms.HiddenInput)
    motif = forms.CharField(label="Motif de consultation", max_length=255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _styler(self)


class ClotureForm(forms.Form):
    statut = forms.ChoiceField(
        label="Issue du rendez-vous",
        choices=[(RendezVous.Statut.TERMINE, "Honoré"), (RendezVous.Statut.ABSENT, "Patient absent")],
    )
    notes = forms.CharField(label="Notes", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _styler(self)


class CreneauForm(forms.Form):
    """Ajout (ou modification, avec `instance`) d'un créneau unique."""
    medecin = MedecinChoiceField(queryset=medecins_qs(), label="Médecin")
    date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    heure_debut = forms.TimeField(label="Début", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    heure_fin = forms.TimeField(label="Fin", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    note = forms.CharField(label="Note interne", max_length=255, required=False)

    def __init__(self, *args, user, instance=None, **kwargs):
        self.instance = instance
        if instance is not None:
            debut, fin = timezone.localtime(instance.debut), timezone.localtime(instance.fin)
            kwargs.setdefault("initial", {}).update({
                "date": debut.date(), "heure_debut": debut.time(), "heure_fin": fin.time(), "note": instance.note,
            })
        super().__init__(*args, **kwargs)
        self.user = user
        if user.is_doctor or instance is not None:  # le médecin d'un créneau existant ne change pas
            del self.fields["medecin"]
        else:
            self.fields["medecin"].queryset = medecins_qs()
        self.fields["date"].widget.attrs.setdefault("min", timezone.localdate().isoformat())
        _styler(self)

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        debut = timezone.make_aware(datetime.combine(data["date"], data["heure_debut"]))
        fin = timezone.make_aware(datetime.combine(data["date"], data["heure_fin"]))
        if fin <= debut:
            raise forms.ValidationError("L'heure de fin doit être après l'heure de début.")
        if self.instance is not None:  # la validation métier est faite par services.modifier_creneau
            self.debut, self.fin = debut, fin
            return data
        medecin = self.user if self.user.is_doctor else data["medecin"]
        if debut <= timezone.now():
            raise forms.ValidationError("Impossible de créer un créneau dans le passé.")
        creneau = Creneau(medecin=medecin, debut=debut, fin=fin, note=data.get("note", ""))
        creneau.full_clean()  # vérifie aussi le chevauchement avec les autres créneaux
        self.creneau = creneau
        return data


class GenerationCreneauxForm(forms.Form):
    """Génère un planning régulier sur une période."""
    medecin = MedecinChoiceField(queryset=medecins_qs(), label="Médecin")
    date_debut = forms.DateField(label="Du", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    date_fin = forms.DateField(label="Au", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    jours = forms.TypedMultipleChoiceField(
        label="Jours de consultation", choices=JOURS, coerce=int,
        widget=forms.CheckboxSelectMultiple, initial=[0, 1, 2, 3, 4],
    )
    heure_debut = forms.TimeField(label="Ouverture", initial=time(8, 30), widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    heure_fin = forms.TimeField(label="Fermeture", initial=time(17, 0), widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    duree_minutes = forms.TypedChoiceField(label="Durée d'une consultation", choices=DUREES, coerce=int, initial=30)
    pause_debut = forms.TimeField(label="Pause de", required=False, initial=time(12, 30), widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    pause_fin = forms.TimeField(label="à", required=False, initial=time(14, 0), widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        if user.is_doctor:
            del self.fields["medecin"]
        else:
            self.fields["medecin"].queryset = medecins_qs()
        aujourd_hui = timezone.localdate()
        self.fields["date_debut"].initial = aujourd_hui + timedelta(days=1)
        self.fields["date_fin"].initial = aujourd_hui + timedelta(days=14)
        _styler(self)

    def clean(self):
        data = super().clean()
        d1, d2 = data.get("date_debut"), data.get("date_fin")
        if d1 and d2:
            if d2 < d1:
                self.add_error("date_fin", "La date de fin précède la date de début.")
            elif (d2 - d1).days > 92:
                self.add_error("date_fin", "La période ne peut pas dépasser 3 mois.")
        h1, h2 = data.get("heure_debut"), data.get("heure_fin")
        if h1 and h2 and h2 <= h1:
            self.add_error("heure_fin", "L'heure de fermeture doit être après l'ouverture.")
        p1, p2 = data.get("pause_debut"), data.get("pause_fin")
        if bool(p1) != bool(p2):
            self.add_error("pause_fin", "Renseignez le début et la fin de la pause, ou aucun des deux.")
        elif p1 and p2 and p2 <= p1:
            self.add_error("pause_fin", "La fin de la pause doit être après son début.")
        return data
