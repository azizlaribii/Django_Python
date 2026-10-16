from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


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


# ─────────────────────────────────────────────────────────────
# ASSOCIATION MÉDECIN ↔ PATIENT
# ─────────────────────────────────────────────────────────────
class AssociationMedecinPatient(models.Model):
    medecin = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='patients_associes',
        limit_choices_to={'role': User.Role.DOCTEUR},
        verbose_name="Médecin traitant"
    )
    patient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='medecins_associes',
        limit_choices_to={'role': User.Role.PATIENT},
        verbose_name="Patient"
    )
    date_association = models.DateField(default=timezone.now, verbose_name="Date d'association")
    est_medecin_traitant = models.BooleanField(default=True, verbose_name="Médecin traitant principal")
    notes = models.TextField(blank=True, verbose_name="Notes de suivi")

    class Meta:
        unique_together = ('medecin', 'patient')
        verbose_name = "Association Médecin-Patient"
        verbose_name_plural = "Associations Médecin-Patient"

    def __str__(self):
        return f"Dr. {self.medecin.get_full_name()} → {self.patient.get_full_name()}"


# ─────────────────────────────────────────────────────────────
# DOSSIER MÉDICAL (racine du dossier patient)
# ─────────────────────────────────────────────────────────────
class DossierMedical(models.Model):
    patient = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='dossier_medical',
        limit_choices_to={'role': User.Role.PATIENT},
        verbose_name="Patient"
    )
    numero_dossier = models.CharField(max_length=20, unique=True, verbose_name="N° Dossier")
    date_creation = models.DateField(auto_now_add=True, verbose_name="Date de création")
    date_mise_a_jour = models.DateTimeField(auto_now=True, verbose_name="Dernière mise à jour")
    notes_generales = models.TextField(blank=True, verbose_name="Notes générales")
    allergies = models.TextField(blank=True, verbose_name="Allergies connues")
    antecedents_familiaux = models.TextField(blank=True, verbose_name="Antécédents familiaux")

    class Meta:
        verbose_name = "Dossier Médical"
        verbose_name_plural = "Dossiers Médicaux"

    def __str__(self):
        return f"Dossier #{self.numero_dossier} — {self.patient.get_full_name()}"

    def save(self, *args, **kwargs):
        if not self.numero_dossier:
            import random, string
            self.numero_dossier = 'DM-' + ''.join(random.choices(string.digits, k=6))
        super().save(*args, **kwargs)


# ─────────────────────────────────────────────────────────────
# EXAMEN MÉDICAL
# ─────────────────────────────────────────────────────────────
class ExamenMedical(models.Model):
    STATUT_CHOICES = [
        ('PLANIFIE', 'Planifié'),
        ('EN_COURS', 'En cours'),
        ('TERMINE', 'Terminé'),
        ('ANNULE', 'Annulé'),
    ]
    TYPE_CHOICES = [
        ('CONSULTATION', 'Consultation'),
        ('RADIOLOGIE', 'Radiologie'),
        ('BIOLOGIE', 'Biologie'),
        ('ECHOGRAPHIE', 'Échographie'),
        ('AUTRE', 'Autre'),
    ]

    dossier = models.ForeignKey(
        DossierMedical,
        on_delete=models.CASCADE,
        related_name='examens',
        verbose_name="Dossier médical"
    )
    medecin = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='examens_prescrits',
        limit_choices_to={'role': User.Role.DOCTEUR},
        verbose_name="Médecin prescripteur"
    )
    type_examen = models.CharField(max_length=20, choices=TYPE_CHOICES, default='CONSULTATION', verbose_name="Type")
    titre = models.CharField(max_length=200, verbose_name="Intitulé de l'examen")
    description = models.TextField(blank=True, verbose_name="Description / Motif")
    date_examen = models.DateField(verbose_name="Date de l'examen")
    heure_examen = models.TimeField(null=True, blank=True, verbose_name="Heure")
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='PLANIFIE', verbose_name="Statut")
    resultat = models.TextField(blank=True, verbose_name="Résultat / Compte-rendu")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Examen Médical"
        verbose_name_plural = "Examens Médicaux"
        ordering = ['-date_examen']

    def __str__(self):
        return f"{self.titre} — {self.dossier.patient.get_full_name()} ({self.date_examen})"


# ─────────────────────────────────────────────────────────────
# RÉSULTAT LABORATOIRE
# ─────────────────────────────────────────────────────────────
class ResultatLaboratoire(models.Model):
    PRIORITE_CHOICES = [
        ('NORMALE', 'Normale'),
        ('HAUTE', 'Haute'),
        ('URGENTE', 'Urgente'),
    ]
    STATUT_CHOICES = [
        ('EN_ATTENTE', 'En attente'),
        ('EN_COURS', 'En cours d\'analyse'),
        ('DISPONIBLE', 'Résultats disponibles'),
        ('TRANSMIS', 'Transmis au médecin'),
    ]

    dossier = models.ForeignKey(
        DossierMedical,
        on_delete=models.CASCADE,
        related_name='resultats_labo',
        verbose_name="Dossier médical"
    )
    medecin_prescripteur = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='analyses_prescrites',
        limit_choices_to={'role': User.Role.DOCTEUR},
        verbose_name="Médecin prescripteur"
    )
    laboratoire = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='analyses_realisees',
        limit_choices_to={'role': User.Role.LABORATOIRE},
        verbose_name="Laboratoire"
    )
    type_analyse = models.CharField(max_length=200, verbose_name="Type d'analyse")
    reference = models.CharField(max_length=20, unique=True, verbose_name="Référence analyse")
    priorite = models.CharField(max_length=10, choices=PRIORITE_CHOICES, default='NORMALE', verbose_name="Priorité")
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='EN_ATTENTE', verbose_name="Statut")
    date_prescription = models.DateField(default=timezone.now, verbose_name="Date de prescription")
    date_realisation = models.DateField(null=True, blank=True, verbose_name="Date de réalisation")
    valeurs = models.TextField(blank=True, verbose_name="Valeurs & Résultats")
    interpretation = models.TextField(blank=True, verbose_name="Interprétation")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Résultat de Laboratoire"
        verbose_name_plural = "Résultats de Laboratoire"
        ordering = ['-date_prescription']

    def __str__(self):
        return f"[{self.reference}] {self.type_analyse} — {self.dossier.patient.get_full_name()}"

    def save(self, *args, **kwargs):
        if not self.reference:
            import random, string
            self.reference = 'AN-' + ''.join(random.choices(string.digits, k=4))
        super().save(*args, **kwargs)


# ─────────────────────────────────────────────────────────────
# PRESCRIPTION / ORDONNANCE
# ─────────────────────────────────────────────────────────────
class Prescription(models.Model):
    STATUT_CHOICES = [
        ('ACTIVE', 'Active'),
        ('TERMINEE', 'Terminée'),
        ('ANNULEE', 'Annulée'),
    ]

    dossier = models.ForeignKey(
        DossierMedical,
        on_delete=models.CASCADE,
        related_name='prescriptions',
        verbose_name="Dossier médical"
    )
    medecin = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='prescriptions_ecrites',
        limit_choices_to={'role': User.Role.DOCTEUR},
        verbose_name="Médecin prescripteur"
    )
    medicament = models.CharField(max_length=200, verbose_name="Médicament / Traitement")
    posologie = models.CharField(max_length=300, verbose_name="Posologie & Durée")
    instructions = models.TextField(blank=True, verbose_name="Instructions particulières")
    date_prescription = models.DateField(default=timezone.now, verbose_name="Date de prescription")
    date_fin = models.DateField(null=True, blank=True, verbose_name="Date de fin du traitement")
    statut = models.CharField(max_length=10, choices=STATUT_CHOICES, default='ACTIVE', verbose_name="Statut")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Prescription / Ordonnance"
        verbose_name_plural = "Prescriptions / Ordonnances"
        ordering = ['-date_prescription']

    def __str__(self):
        return f"{self.medicament} — {self.dossier.patient.get_full_name()} ({self.date_prescription})"


# ─────────────────────────────────────────────────────────────
# OBSERVATION MÉDICALE
# ─────────────────────────────────────────────────────────────
class ObservationMedicale(models.Model):
    dossier = models.ForeignKey(
        DossierMedical,
        on_delete=models.CASCADE,
        related_name='observations',
        verbose_name="Dossier médical"
    )
    medecin = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='observations_ecrites',
        limit_choices_to={'role': User.Role.DOCTEUR},
        verbose_name="Médecin"
    )
    titre = models.CharField(max_length=200, verbose_name="Titre de l'observation")
    contenu = models.TextField(verbose_name="Observation médicale")
    date_observation = models.DateField(default=timezone.now, verbose_name="Date")
    confidentiel = models.BooleanField(default=False, verbose_name="Confidentiel (médecin uniquement)")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Observation Médicale"
        verbose_name_plural = "Observations Médicales"
        ordering = ['-date_observation']

    def __str__(self):
        return f"{self.titre} — {self.dossier.patient.get_full_name()} ({self.date_observation})"

