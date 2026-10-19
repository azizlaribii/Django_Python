"""Module Rendez-vous : créneaux de consultation des médecins et réservations des patients."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

STATUTS_ACTIFS = ("EN_ATTENTE", "CONFIRME")


class CreneauQuerySet(models.QuerySet):
    def a_venir(self):
        return self.filter(debut__gt=timezone.now())

    def du_medecin(self, medecin):
        return self.filter(medecin=medecin)

    def chevauchant(self, debut, fin):
        """Créneaux dont l'intervalle [debut, fin[ recoupe celui donné."""
        return self.filter(debut__lt=fin, fin__gt=debut)

    def avec_rdv_actif(self):
        return self.filter(rendez_vous__statut__in=STATUTS_ACTIFS).distinct()

    def disponibles(self):
        """Créneaux futurs, non bloqués et sans rendez-vous en cours."""
        return (
            self.a_venir()
            .filter(est_bloque=False)
            .exclude(rendez_vous__statut__in=STATUTS_ACTIFS)
        )


class Creneau(models.Model):
    medecin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="creneaux",
        limit_choices_to={"role": "DOCTEUR"},
        verbose_name="Médecin",
    )
    debut = models.DateTimeField(verbose_name="Début")
    fin = models.DateTimeField(verbose_name="Fin")
    est_bloque = models.BooleanField(
        default=False,
        verbose_name="Bloqué",
        help_text="Un créneau bloqué n'est plus proposé à la réservation (absence, congé…).",
    )
    note = models.CharField(max_length=255, blank=True, verbose_name="Note interne")
    date_creation = models.DateTimeField(auto_now_add=True)

    objects = CreneauQuerySet.as_manager()

    class Meta:
        verbose_name = "Créneau"
        verbose_name_plural = "Créneaux"
        ordering = ["debut"]
        constraints = [
            models.CheckConstraint(condition=Q(fin__gt=F("debut")), name="creneau_fin_apres_debut"),
            models.UniqueConstraint(fields=["medecin", "debut"], name="creneau_unique_medecin_debut"),
        ]
        indexes = [models.Index(fields=["medecin", "debut"])]

    def __str__(self):
        debut = timezone.localtime(self.debut)
        fin = timezone.localtime(self.fin)
        return f"{debut:%d/%m/%Y %H:%M}–{fin:%H:%M} · Dr {self.medecin.get_full_name() or self.medecin.username}"

    def clean(self):
        if self.debut and self.fin:
            if self.fin <= self.debut:
                raise ValidationError({"fin": "L'heure de fin doit être après l'heure de début."})
            if self.medecin_id:
                conflits = Creneau.objects.du_medecin(self.medecin_id).chevauchant(self.debut, self.fin)
                if self.pk:
                    conflits = conflits.exclude(pk=self.pk)
                if conflits.exists():
                    raise ValidationError("Ce créneau chevauche un autre créneau du même médecin.")

    @property
    def duree_minutes(self):
        return int((self.fin - self.debut).total_seconds() // 60)

    @property
    def est_passe(self):
        return self.debut <= timezone.now()

    @property
    def rdv_actif(self):
        """Le rendez-vous en attente ou confirmé occupant ce créneau (ou None)."""
        cache = getattr(self, "_prefetched_objects_cache", {}).get("rendez_vous")
        if cache is not None:
            return next((r for r in cache if r.statut in STATUTS_ACTIFS), None)
        return self.rendez_vous.filter(statut__in=STATUTS_ACTIFS).first()

    @property
    def est_disponible(self):
        return not self.est_bloque and not self.est_passe and self.rdv_actif is None

    @property
    def etat(self):
        """Code d'état utilisé par les templates : libre / reserve / bloque / passe."""
        if self.rdv_actif is not None:
            return "reserve"
        if self.est_bloque:
            return "bloque"
        if self.est_passe:
            return "passe"
        return "libre"


class RendezVousQuerySet(models.QuerySet):
    def actifs(self):
        return self.filter(statut__in=STATUTS_ACTIFS)

    def a_venir(self):
        return self.filter(creneau__debut__gt=timezone.now())

    def visibles_par(self, user):
        """Restreint la liste selon le rôle de l'utilisateur connecté."""
        if not user.is_authenticated:
            return self.none()
        if user.is_admin_user:
            return self
        if user.is_doctor:
            return self.filter(medecin=user)
        if user.is_patient:
            return self.filter(patient=user)
        return self.none()


class RendezVous(models.Model):
    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente de confirmation"
        CONFIRME = "CONFIRME", "Confirmé"
        ANNULE = "ANNULE", "Annulé"
        TERMINE = "TERMINE", "Honoré"
        ABSENT = "ABSENT", "Patient absent"

    creneau = models.ForeignKey(
        Creneau, on_delete=models.PROTECT, related_name="rendez_vous", verbose_name="Créneau"
    )
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rendez_vous_patient",
        limit_choices_to={"role": "PATIENT"},
        verbose_name="Patient",
    )
    medecin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rendez_vous_medecin",
        limit_choices_to={"role": "DOCTEUR"},
        verbose_name="Médecin",
    )
    motif = models.CharField(max_length=255, verbose_name="Motif de consultation")
    statut = models.CharField(
        max_length=20, choices=Statut.choices, default=Statut.EN_ATTENTE, verbose_name="Statut"
    )
    notes_medecin = models.TextField(blank=True, verbose_name="Notes du médecin")

    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rendez_vous_crees", verbose_name="Réservé par",
    )
    date_creation = models.DateTimeField(auto_now_add=True, verbose_name="Réservé le")
    date_modification = models.DateTimeField(auto_now=True)
    date_confirmation = models.DateTimeField(null=True, blank=True, verbose_name="Confirmé le")
    annule_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rendez_vous_annules", verbose_name="Annulé par",
    )
    date_annulation = models.DateTimeField(null=True, blank=True, verbose_name="Annulé le")
    motif_annulation = models.CharField(max_length=255, blank=True, verbose_name="Motif d'annulation")

    objects = RendezVousQuerySet.as_manager()

    class Meta:
        verbose_name = "Rendez-vous"
        verbose_name_plural = "Rendez-vous"
        ordering = ["creneau__debut"]
        constraints = [
            # Garde-fou en base : un créneau ne peut porter qu'un seul rendez-vous actif.
            models.UniqueConstraint(
                fields=["creneau"],
                condition=Q(statut__in=STATUTS_ACTIFS),
                name="rdv_un_seul_actif_par_creneau",
            ),
        ]
        indexes = [
            models.Index(fields=["medecin", "statut"]),
            models.Index(fields=["patient", "statut"]),
        ]

    def __str__(self):
        return f"RDV #{self.pk} · {self.patient.get_full_name() or self.patient.username} · {self.creneau}"

    @property
    def debut(self):
        return self.creneau.debut

    @property
    def fin(self):
        return self.creneau.fin

    @property
    def est_actif(self):
        return self.statut in STATUTS_ACTIFS

    @property
    def est_passe(self):
        return self.creneau.debut <= timezone.now()

    @property
    def classe_statut(self):
        return {
            "EN_ATTENTE": "pending",
            "CONFIRME": "verified",
            "ANNULE": "danger",
            "TERMINE": "info",
            "ABSENT": "inactive",
        }[self.statut]
