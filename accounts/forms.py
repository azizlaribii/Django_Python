from django import forms
from django.contrib.auth import authenticate
from .models import User, DoctorProfile, LaboratoryProfile, PatientProfile


class LoginForm(forms.Form):
    username = forms.CharField(
        label="Nom d'utilisateur",
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Entrez votre nom d’utilisateur',
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
        label="Nom du Biologiste responsable",
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'ex: Dr. Martin Dupont'})
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

