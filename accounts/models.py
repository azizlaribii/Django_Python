from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db.models.signals import post_save
from django.dispatch import receiver


class CustomUserManager(BaseUserManager):
    def create_user(self, username, email=None, password=None, **extra_fields):
        if not username:
            raise ValueError("Le nom d'utilisateur est obligatoire")
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', User.Role.ADMIN)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Le superutilisateur doit avoir is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Le superutilisateur doit avoir is_superuser=True.')

        return self.create_user(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrateur'
        DOCTEUR = 'DOCTEUR', 'Docteur'
        LABORATOIRE = 'LABORATOIRE', 'Laboratoire'
        PATIENT = 'PATIENT', 'Patient'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.PATIENT,
        verbose_name="Rôle utilisateur"
    )
    phone = models.CharField(max_length=25, blank=True, null=True, verbose_name="Téléphone")
    address = models.CharField(max_length=255, blank=True, null=True, verbose_name="Adresse")
    city = models.CharField(max_length=100, blank=True, null=True, verbose_name="Ville")
    is_verified = models.BooleanField(
        default=False,
        verbose_name="Compte certifié / validé",
        help_text="Coché par l'administrateur pour valider l'activité d'un docteur ou laboratoire."
    )

    objects = CustomUserManager()

    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Tous les Utilisateurs"

    @property
    def is_doctor(self):
        return self.role == self.Role.DOCTEUR

    @property
    def is_laboratory(self):
        return self.role == self.Role.LABORATOIRE

    @property
    def is_patient(self):
        return self.role == self.Role.PATIENT

    @property
    def is_admin_user(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    def __str__(self):
        full = self.get_full_name()
        display = full if full else self.username
        return f"{display} ({self.get_role_display()})"


class DoctorProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='doctor_profile',
        verbose_name="Compte utilisateur"
    )
    specialite = models.CharField(
        max_length=120,
        default="Médecine Générale",
        verbose_name="Spécialité médicale"
    )
    numero_ordre = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Numéro d'Ordre / Licence"
    )
    cabinet_name = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name="Nom du cabinet ou clinique"
    )
    horaires = models.CharField(
        max_length=150,
        blank=True,
        default="08h30 - 17h00 (Lun-Ven)",
        verbose_name="Horaires de consultation"
    )
    biographie = models.TextField(
        blank=True,
        verbose_name="Présentation / Biographie"
    )

    class Meta:
        verbose_name = "Profil Docteur"
        verbose_name_plural = "Profils Docteurs"

    def __str__(self):
        return f"Dr. {self.user.get_full_name() or self.user.username} - {self.specialite}"


class LaboratoryProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='lab_profile',
        verbose_name="Compte utilisateur"
    )
    nom_laboratoire = models.CharField(
        max_length=150,
        default="Laboratoire d'Analyses Médicales",
        verbose_name="Nom du laboratoire"
    )
    numero_agrement = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="N° d'agrément officiel"
    )
    responsable = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Biologiste / Responsable"
    )
    services_offerts = models.TextField(
        blank=True,
        default="Analyses biochimiques, Hématologie, Sérologie, Microbiologie, Tests PCR",
        verbose_name="Analyses & Examens proposés"
    )

    class Meta:
        verbose_name = "Profil Laboratoire"
        verbose_name_plural = "Profils Laboratoires"

    def __str__(self):
        return f"{self.nom_laboratoire} ({self.user.username})"


class PatientProfile(models.Model):
    BLOOD_GROUPS = [
        ('A+', 'A+'), ('A-', 'A-'),
        ('B+', 'B+'), ('B-', 'B-'),
        ('AB+', 'AB+'), ('AB-', 'AB-'),
        ('O+', 'O+'), ('O-', 'O-'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='patient_profile',
        verbose_name="Compte utilisateur"
    )
    date_naissance = models.DateField(
        null=True,
        blank=True,
        verbose_name="Date de naissance"
    )
    groupe_sanguin = models.CharField(
        max_length=5,
        choices=BLOOD_GROUPS,
        blank=True,
        default='O+',
        verbose_name="Groupe sanguin"
    )
    numero_securite_sociale = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        verbose_name="N° Sécurité Sociale / Identifiant Patient"
    )
    antecedents = models.TextField(
        blank=True,
        verbose_name="Antécédents médicaux & allergies"
    )
    personne_contact = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Contact en cas d'urgence (Nom & Tél)"
    )

    class Meta:
        verbose_name = "Profil Patient"
        verbose_name_plural = "Profils Patients"

    def __str__(self):
        return f"Patient: {self.user.get_full_name() or self.user.username} ({self.groupe_sanguin})"


# Signals to auto-create matching profiles
@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if instance.role == User.Role.DOCTEUR:
        DoctorProfile.objects.get_or_create(user=instance)
    elif instance.role == User.Role.LABORATOIRE:
        LaboratoryProfile.objects.get_or_create(user=instance)
    elif instance.role == User.Role.PATIENT:
        PatientProfile.objects.get_or_create(user=instance)


# Proxy Models for dedicated Django Admin sections
class DoctorManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(role=User.Role.DOCTEUR)


class Docteur(User):
    objects = DoctorManager()

    class Meta:
        proxy = True
        verbose_name = "🩺 Docteur"
        verbose_name_plural = "🩺 Docteurs"


class LaboratoryManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(role=User.Role.LABORATOIRE)


class Laboratoire(User):
    objects = LaboratoryManager()

    class Meta:
        proxy = True
        verbose_name = "🔬 Laboratoire"
        verbose_name_plural = "🔬 Laboratoires"


class PatientManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(role=User.Role.PATIENT)


class Patient(User):
    objects = PatientManager()

    class Meta:
        proxy = True
        verbose_name = "👤 Patient"
        verbose_name_plural = "👤 Patients"
