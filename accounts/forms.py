from django import forms
from django.contrib.auth import authenticate
from .models import (
    User, DoctorProfile, LaboratoryProfile, PatientProfile,
    ExamenMedical, ResultatLaboratoire, Prescription, ObservationMedicale,
    AssociationMedecinPatient, DossierMedical,
)


class LoginForm(forms.Form):
    username = forms.CharField(
        label="Nom d'utilisateur",
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': "Entrez votre nom d'utilisateur",
            'autocomplete': 'username',
            'id': 'login-username'
        })
    )
    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': '••••••••',
            'autocomplete': 'current-password',
            'id': 'login-password'
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')

        if username and password:
            user = authenticate(username=username, password=password)
            if not user:
                raise forms.ValidationError("Nom d'utilisateur ou mot de passe incorrect.")
            if not user.is_active:
                raise forms.ValidationError("Ce compte a été désactivé par l'administrateur.")
            self.user_cache = user
        return cleaned_data

    def get_user(self):
        return getattr(self, 'user_cache', None)


class RegisterForm(forms.ModelForm):
    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'Minimum 6 caractères'}),
        min_length=4
    )
    password_confirm = forms.CharField(
        label="Confirmer le mot de passe",
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'Retapez votre mot de passe'})
    )

    # Doctor specific extra fields
    specialite = forms.CharField(
        required=False,
        label="Spécialité médicale",
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: Cardiologie, Pédiatrie...'})
    )
    numero_ordre = forms.CharField(
        required=False,
        label="N° d'Ordre / Licence",
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: ORD-78291'})
    )
    cabinet_name = forms.CharField(
        required=False,
        label="Nom du Cabinet / Clinique",
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: Cabinet Médical Saint-Luc'})
    )

    # Laboratory specific extra fields
    nom_laboratoire = forms.CharField(
        required=False,
        label="Nom du Laboratoire",
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: BioSanté Analyses'})
    )
    numero_agrement = forms.CharField(
        required=False,
        label="N° Agrément officiel",
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: AGR-2024-998'})
    )
    responsable = forms.CharField(
        required=False,
        label="Responsable du laboratoire",
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Nom du responsable'})
    )

    # Patient specific extra fields
    date_naissance = forms.DateField(
        required=False,
        label="Date de naissance",
        widget=forms.DateInput(attrs={'class': 'form-input', 'type': 'date'})
    )
    groupe_sanguin = forms.ChoiceField(
        choices=PatientProfile.BLOOD_GROUPS,
        required=False,
        label="Groupe Sanguin",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    numero_securite_sociale = forms.CharField(
        required=False,
        label="N° Sécurité Sociale / CIN",
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: 1 85 02 75 123 456'})
    )

    class Meta:
        model = User
        fields = [
            'username', 'first_name', 'last_name', 'email',
            'phone', 'city', 'address', 'role'
        ]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Identifiant unique'}),
            'first_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Prénom'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Nom'}),
            'email': forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'contact@exemple.com'}),
            'phone': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '+33 6 12 34 56 78'}),
            'city': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: Paris'}),
            'address': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Adresse complète'}),
            'role': forms.Select(attrs={'class': 'form-select', 'id': 'role-selector'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get('password')
        p2 = cleaned_data.get('password_confirm')
        if p1 and p2 and p1 != p2:
            self.add_error('password_confirm', "Les deux mots de passe ne correspondent pas.")
        return cleaned_data

    def save_profile(self, user):
        if user.role == User.Role.DOCTEUR:
            profile, _ = DoctorProfile.objects.get_or_create(user=user)
            if self.cleaned_data.get('specialite'):
                profile.specialite = self.cleaned_data['specialite']
            if self.cleaned_data.get('numero_ordre'):
                profile.numero_ordre = self.cleaned_data['numero_ordre']
            if self.cleaned_data.get('cabinet_name'):
                profile.cabinet_name = self.cleaned_data['cabinet_name']
            profile.save()
        elif user.role == User.Role.LABORATOIRE:
            profile, _ = LaboratoryProfile.objects.get_or_create(user=user)
            if self.cleaned_data.get('nom_laboratoire'):
                profile.nom_laboratoire = self.cleaned_data['nom_laboratoire']
            if self.cleaned_data.get('numero_agrement'):
                profile.numero_agrement = self.cleaned_data['numero_agrement']
            if self.cleaned_data.get('responsable'):
                profile.responsable = self.cleaned_data['responsable']
            profile.save()
        elif user.role == User.Role.PATIENT:
            profile, _ = PatientProfile.objects.get_or_create(user=user)
            if self.cleaned_data.get('date_naissance'):
                profile.date_naissance = self.cleaned_data['date_naissance']
            if self.cleaned_data.get('groupe_sanguin'):
                profile.groupe_sanguin = self.cleaned_data['groupe_sanguin']
            if self.cleaned_data.get('numero_securite_sociale'):
                profile.numero_securite_sociale = self.cleaned_data['numero_securite_sociale']
            profile.save()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            self.save_profile(user)
        return user


class AdminCreateUserForm(RegisterForm):
    is_verified = forms.BooleanField(
        required=False,
        initial=True,
        label="Compte certifié / validé par l'Administration",
        widget=forms.CheckboxInput(attrs={'class': 'form-checkbox', 'style': 'width: 20px; height: 20px; cursor: pointer;'})
    )
    is_active = forms.BooleanField(
        required=False,
        initial=True,
        label="Compte actif (accès autorisé)",
        widget=forms.CheckboxInput(attrs={'class': 'form-checkbox', 'style': 'width: 20px; height: 20px; cursor: pointer;'})
    )

    class Meta(RegisterForm.Meta):
        fields = [
            'username', 'first_name', 'last_name', 'email',
            'phone', 'city', 'address', 'role'
        ]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_verified = self.cleaned_data.get('is_verified', True)
        user.is_active = self.cleaned_data.get('is_active', True)
        if user.role == User.Role.ADMIN:
            user.is_staff = True
        if commit:
            user.save()
            self.save_profile(user)
        return user


class UserProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'city', 'address']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'phone': forms.TextInput(attrs={'class': 'form-input'}),
            'city': forms.TextInput(attrs={'class': 'form-input'}),
            'address': forms.TextInput(attrs={'class': 'form-input'}),
        }


class DoctorProfileForm(forms.ModelForm):
    class Meta:
        model = DoctorProfile
        fields = ['specialite', 'numero_ordre', 'cabinet_name', 'horaires', 'biographie']
        widgets = {
            'specialite': forms.TextInput(attrs={'class': 'form-input'}),
            'numero_ordre': forms.TextInput(attrs={'class': 'form-input'}),
            'cabinet_name': forms.TextInput(attrs={'class': 'form-input'}),
            'horaires': forms.TextInput(attrs={'class': 'form-input'}),
            'biographie': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
        }


class LaboratoryProfileForm(forms.ModelForm):
    class Meta:
        model = LaboratoryProfile
        fields = ['nom_laboratoire', 'numero_agrement', 'responsable', 'services_offerts']
        widgets = {
            'nom_laboratoire': forms.TextInput(attrs={'class': 'form-input'}),
            'numero_agrement': forms.TextInput(attrs={'class': 'form-input'}),
            'responsable': forms.TextInput(attrs={'class': 'form-input'}),
            'services_offerts': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
        }


class PatientProfileForm(forms.ModelForm):
    class Meta:
        model = PatientProfile
        fields = ['date_naissance', 'groupe_sanguin', 'numero_securite_sociale', 'antecedents', 'personne_contact']
        widgets = {
            'date_naissance': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'groupe_sanguin': forms.Select(attrs={'class': 'form-select'}),
            'numero_securite_sociale': forms.TextInput(attrs={'class': 'form-input'}),
            'antecedents': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'personne_contact': forms.TextInput(attrs={'class': 'form-input'}),
        }


class AdminUserEditForm(forms.ModelForm):
    new_password = forms.CharField(
        label="Nouveau mot de passe (laisser vide pour ne pas modifier)",
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'Nouveau mot de passe (optionnel)'})
    )

    class Meta:
        model = User
        fields = [
            'username', 'first_name', 'last_name', 'email',
            'phone', 'city', 'address', 'role', 'is_verified', 'is_active'
        ]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-input'}),
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'phone': forms.TextInput(attrs={'class': 'form-input'}),
            'city': forms.TextInput(attrs={'class': 'form-input'}),
            'address': forms.TextInput(attrs={'class': 'form-input'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'is_verified': forms.CheckboxInput(attrs={'class': 'form-checkbox', 'style': 'width: 20px; height: 20px; cursor: pointer;'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox', 'style': 'width: 20px; height: 20px; cursor: pointer;'}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        new_pwd = self.cleaned_data.get('new_password')
        if new_pwd:
            user.set_password(new_pwd)
        if commit:
            user.save()
        return user


# ─────────────────────────────────────────────────────────────
# FORMULAIRES MÉDICAUX
# ─────────────────────────────────────────────────────────────
class ExamenMedicalForm(forms.ModelForm):
    heure_examen = forms.TimeField(
        required=False,
        input_formats=['%H:%M', '%H:%M:%S', '%Hh%M', '%Hh%M:%S', '%H:%M %p'],
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'HH:MM (ex: 14:30)'})
    )

    class Meta:
        model = ExamenMedical
        fields = [
            'titre', 'type_examen', 'description', 'date_examen', 'heure_examen',
            'lieu_examen', 'consignes_preparation', 'statut_preparation', 'statut', 'resultat'
        ]
        widgets = {
            'titre': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: Échographie abdominale / Radiographie'}),
            'type_examen': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Motif ou description'}),
            'date_examen': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'lieu_examen': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: Salle d\'imagerie 2 / Service Radiologie'}),
            'consignes_preparation': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 3,
                'placeholder': 'ex: À jeun strict depuis 6h. Boire 1L d\'eau 1h avant sans uriner. Apporter anciens clichés.'
            }),
            'statut_preparation': forms.Select(attrs={'class': 'form-select'}),
            'statut': forms.Select(attrs={'class': 'form-select'}),
            'resultat': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'Compte-rendu du résultat'}),
        }


class ExamenMedicalFullForm(ExamenMedicalForm):
    patient = forms.ModelChoiceField(
        queryset=User.objects.filter(role=User.Role.PATIENT, is_active=True),
        label="Patient",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    medecin = forms.ModelChoiceField(
        queryset=User.objects.filter(role=User.Role.DOCTEUR, is_active=True),
        required=False,
        label="Médecin prescripteur / réalisateur",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta(ExamenMedicalForm.Meta):
        fields = [
            'patient', 'medecin', 'titre', 'type_examen', 'description',
            'date_examen', 'heure_examen', 'lieu_examen', 'consignes_preparation',
            'statut_preparation', 'statut', 'resultat'
        ]


class ResultatLaboratoireForm(forms.ModelForm):
    class Meta:
        model = ResultatLaboratoire
        fields = ['type_analyse', 'priorite', 'statut', 'date_prescription', 'date_realisation', 'laboratoire', 'valeurs', 'interpretation']
        widgets = {
            'type_analyse': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: NFS, Glycémie, Bilan hépatique...'}),
            'priorite': forms.Select(attrs={'class': 'form-select'}),
            'statut': forms.Select(attrs={'class': 'form-select'}),
            'date_prescription': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'date_realisation': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'laboratoire': forms.Select(attrs={'class': 'form-select'}),
            'valeurs': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'Valeurs mesurées'}),
            'interpretation': forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Interprétation des résultats'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['laboratoire'].queryset = User.objects.filter(role=User.Role.LABORATOIRE, is_active=True)
        self.fields['laboratoire'].empty_label = "— Sélectionner un laboratoire —"
        self.fields['laboratoire'].required = False
        self.fields['date_realisation'].required = False


class PrescriptionForm(forms.ModelForm):
    class Meta:
        model = Prescription
        fields = ['medicament', 'posologie', 'instructions', 'date_prescription', 'date_fin', 'statut']
        widgets = {
            'medicament': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: Amoxicilline 500mg'}),
            'posologie': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: 3 fois/jour pendant 7 jours'}),
            'instructions': forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Instructions particulières'}),
            'date_prescription': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'date_fin': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'statut': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date_fin'].required = False


class ObservationMedicaleForm(forms.ModelForm):
    class Meta:
        model = ObservationMedicale
        fields = ['titre', 'contenu', 'date_observation', 'confidentiel']
        widgets = {
            'titre': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: Contrôle tension artérielle'}),
            'contenu': forms.Textarea(attrs={'class': 'form-input', 'rows': 4, 'placeholder': 'Détails de l\'observation...'}),
            'date_observation': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'confidentiel': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }


class AssociationForm(forms.ModelForm):
    class Meta:
        model = AssociationMedecinPatient
        fields = ['patient', 'est_medecin_traitant', 'notes']
        widgets = {
            'patient': forms.Select(attrs={'class': 'form-select'}),
            'est_medecin_traitant': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'notes': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
        }


class DossierMedicalForm(forms.ModelForm):
    class Meta:
        model = DossierMedical
        fields = ['notes_generales', 'allergies', 'antecedents_familiaux']
        widgets = {
            'notes_generales': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'allergies': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
            'antecedents_familiaux': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
        }


class NouveauPatientDossierForm(forms.Form):
    username = forms.CharField(label="Nom d'utilisateur / Identifiant", widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: jean_dupont'}))
    first_name = forms.CharField(label="Prénom", widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: Jean'}))
    last_name = forms.CharField(label="Nom", widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: Dupont'}))
    email = forms.EmailField(label="Email", required=False, widget=forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'jean.dupont@email.com'}))
    phone = forms.CharField(label="Téléphone", required=False, widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': '06 12 34 56 78'}))
    city = forms.CharField(label="Ville", required=False, widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Paris'}))
    address = forms.CharField(label="Adresse", required=False, widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': '12 rue de la Paix'}))

    date_naissance = forms.DateField(label="Date de naissance", required=False, widget=forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}))
    groupe_sanguin = forms.ChoiceField(choices=PatientProfile.BLOOD_GROUPS, required=False, label="Groupe sanguin", widget=forms.Select(attrs={'class': 'form-select'}))
    numero_securite_sociale = forms.CharField(label="N° Sécurité Sociale", required=False, widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': '1 85 03 75 123 456 78'}))
    personne_contact = forms.CharField(label="Contact d'urgence", required=False, widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Nom et Téléphone du contact'}))
    antecedents = forms.CharField(label="Antécédents médicaux personnels", required=False, widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Antécédents du patient...'}))

    allergies = forms.CharField(label="Allergies connues", required=False, widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'ex: Pénicilline, arachides, aspirine...'}))
    antecedents_familiaux = forms.CharField(label="Antécédents familiaux", required=False, widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'ex: Diabète type 2, HTA, cardiopathie...'}))
    notes_generales = forms.CharField(label="Notes générales du dossier", required=False, widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Notes de suivi initiales...'}))

    medecin_traitant = forms.ModelChoiceField(
        queryset=User.objects.filter(role=User.Role.DOCTEUR, is_active=True),
        required=False,
        label="Médecin traitant assigné",
        widget=forms.Select(attrs={'class': 'form-select'})
    )


class PatientDossierEditForm(forms.Form):
    first_name = forms.CharField(label="Prénom", widget=forms.TextInput(attrs={'class': 'form-input'}))
    last_name = forms.CharField(label="Nom", widget=forms.TextInput(attrs={'class': 'form-input'}))
    email = forms.EmailField(label="Email", required=False, widget=forms.EmailInput(attrs={'class': 'form-input'}))
    phone = forms.CharField(label="Téléphone", required=False, widget=forms.TextInput(attrs={'class': 'form-input'}))
    city = forms.CharField(label="Ville", required=False, widget=forms.TextInput(attrs={'class': 'form-input'}))
    address = forms.CharField(label="Adresse", required=False, widget=forms.TextInput(attrs={'class': 'form-input'}))

    date_naissance = forms.DateField(label="Date de naissance", required=False, widget=forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}))
    groupe_sanguin = forms.ChoiceField(choices=PatientProfile.BLOOD_GROUPS, required=False, label="Groupe sanguin", widget=forms.Select(attrs={'class': 'form-select'}))
    numero_securite_sociale = forms.CharField(label="N° Sécurité Sociale", required=False, widget=forms.TextInput(attrs={'class': 'form-input'}))
    personne_contact = forms.CharField(label="Contact d'urgence", required=False, widget=forms.TextInput(attrs={'class': 'form-input'}))
    antecedents = forms.CharField(label="Antécédents personnels", required=False, widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 2}))

    allergies = forms.CharField(label="Allergies connues", required=False, widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 2}))
    antecedents_familiaux = forms.CharField(label="Antécédents familiaux", required=False, widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 2}))
    notes_generales = forms.CharField(label="Notes générales", required=False, widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 2}))

    medecin_traitant = forms.ModelChoiceField(
        queryset=User.objects.filter(role=User.Role.DOCTEUR, is_active=True),
        required=False,
        label="Médecin traitant",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
