from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from decimal import Decimal, InvalidOperation


class TypeAnalyse(models.Model):
    code = models.CharField("Code", max_length=30, unique=True)
    nom = models.CharField("Nom", max_length=150)
    description = models.TextField("Description", blank=True)
    unite = models.CharField("Unité", max_length=30, blank=True)
    valeur_reference_min = models.DecimalField(
        "Valeur de référence minimale", max_digits=12, decimal_places=3,
        null=True, blank=True,
    )
    valeur_reference_max = models.DecimalField(
        "Valeur de référence maximale", max_digits=12, decimal_places=3,
        null=True, blank=True,
    )
    tarif = models.DecimalField(
        "Tarif", max_digits=9, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
    )
    actif = models.BooleanField("Actif", default=True)

    class Meta:
        ordering = ["nom"]
        verbose_name = "Type d’analyse"
        verbose_name_plural = "Types d’analyses"

    def clean(self):
        super().clean()
        if (
            self.valeur_reference_min is not None
            and self.valeur_reference_max is not None
            and self.valeur_reference_min > self.valeur_reference_max
        ):
            raise ValidationError({
                "valeur_reference_max": "La valeur maximale doit être supérieure à la valeur minimale."
            })

    def __str__(self):
        return f"{self.nom} ({self.code})"


class DemandeAnalyse(models.Model):
    class Priorite(models.TextChoices):
        NORMALE = "NORMALE", "Normale"
        HAUTE = "HAUTE", "Haute"
        URGENTE = "URGENTE", "Urgente"

    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        EN_COURS = "EN_COURS", "En cours"
        TERMINEE = "TERMINEE", "Terminée"
        ANNULEE = "ANNULEE", "Annulée"

    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="demandes_analyses", limit_choices_to={"role": "PATIENT"},
        verbose_name="Patient",
    )
    medecin = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="demandes_prescrites", limit_choices_to={"role": "DOCTEUR"},
        verbose_name="Médecin prescripteur",
    )
    laboratoire = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="demandes_laboratoire", limit_choices_to={"role": "LABORATOIRE"},
        verbose_name="Laboratoire destinataire",
    )
    date_demande = models.DateTimeField("Date de prescription", default=timezone.now)
    priorite = models.CharField(
        "Priorité", max_length=10, choices=Priorite.choices, default=Priorite.NORMALE,
    )
    statut = models.CharField(
        "Statut", max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE,
    )
    commentaire = models.TextField("Commentaire", blank=True)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="demandes_analyses_creees", verbose_name="Créée par",
    )

    class Meta:
        ordering = ["-date_demande", "-pk"]
        verbose_name = "Demande d’analyse"
        verbose_name_plural = "Demandes d’analyses"

    def clean(self):
        super().clean()
        errors = {}
        if self.patient_id and self.patient.role != "PATIENT":
            errors["patient"] = "Le compte sélectionné n’est pas un patient."
        if self.medecin_id and self.medecin.role != "DOCTEUR":
            errors["medecin"] = "Le prescripteur doit être un médecin."
        if self.laboratoire_id and self.laboratoire.role != "LABORATOIRE":
            errors["laboratoire"] = "Le destinataire doit être un compte laboratoire."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Demande #{self.pk} — {self.patient}"


class AnalyseDemandee(models.Model):
    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        EN_COURS = "EN_COURS", "En cours"
        TERMINEE = "TERMINEE", "Terminée"
        ANNULEE = "ANNULEE", "Annulée"

    demande = models.ForeignKey(
        DemandeAnalyse, on_delete=models.CASCADE, related_name="analyses",
    )
    type_analyse = models.ForeignKey(
        TypeAnalyse, on_delete=models.PROTECT, related_name="demandes",
    )
    statut = models.CharField(
        "Statut", max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE,
    )

    class Meta:
        ordering = ["type_analyse__nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["demande", "type_analyse"], name="unique_type_analyse_par_demande",
            ),
        ]
        verbose_name = "Analyse demandée"
        verbose_name_plural = "Analyses demandées"

    def __str__(self):
        return f"{self.type_analyse} — demande #{self.demande_id}"


class Prelevement(models.Model):
    class Type(models.TextChoices):
        SANG = "SANG", "Sang"
        URINE = "URINE", "Urine"
        AUTRE = "AUTRE", "Autre"

    class Statut(models.TextChoices):
        A_EFFECTUER = "A_EFFECTUER", "À effectuer"
        PRELEVE = "PRELEVE", "Prélevé"
        RECU = "RECU", "Reçu au laboratoire"
        REJETE = "REJETE", "Rejeté"
        ANNULE = "ANNULE", "Annulé"

    demande = models.ForeignKey(
        DemandeAnalyse, on_delete=models.PROTECT, related_name="prelevements",
        verbose_name="Demande",
    )
    code_prelevement = models.CharField("Code du prélèvement", max_length=40, unique=True)
    type_prelevement = models.CharField("Type", max_length=10, choices=Type.choices)
    date_prelevement = models.DateTimeField("Date du prélèvement", null=True, blank=True)
    date_reception = models.DateTimeField("Date de réception", null=True, blank=True)
    statut = models.CharField(
        "Statut", max_length=12, choices=Statut.choices, default=Statut.A_EFFECTUER,
    )
    motif_rejet = models.TextField("Motif du rejet", blank=True)
    remarque = models.TextField("Remarque", blank=True)

    class Meta:
        ordering = ["-date_prelevement", "-pk"]
        verbose_name = "Prélèvement"
        verbose_name_plural = "Prélèvements"

    def clean(self):
        super().clean()
        if self.statut == self.Statut.REJETE and not self.motif_rejet.strip():
            raise ValidationError({"motif_rejet": "Le motif est obligatoire pour rejeter un prélèvement."})
        if self.demande_id and self.demande.statut == DemandeAnalyse.Statut.ANNULEE:
            raise ValidationError({"demande": "La demande associée est annulée."})

    def __str__(self):
        return f"{self.code_prelevement} — demande #{self.demande_id}"


class Resultat(models.Model):
    class Statut(models.TextChoices):
        EN_SAISIE = "EN_SAISIE", "En saisie"
        EN_ATTENTE_VALIDATION = "EN_ATTENTE_VALIDATION", "En attente de validation"
        CORRIGE = "CORRIGE", "Correction à valider"
        VALIDE = "VALIDE", "Validé"

    analyse_demandee = models.ForeignKey(
        AnalyseDemandee, on_delete=models.PROTECT, related_name="resultats",
        verbose_name="Analyse demandée",
    )
    prelevement = models.ForeignKey(
        Prelevement, on_delete=models.PROTECT, null=True, blank=True,
        related_name="resultats", verbose_name="Prélèvement",
    )
    valeur = models.CharField("Valeur", max_length=255)
    unite = models.CharField("Unité", max_length=30, blank=True)
    valeur_reference = models.CharField("Valeurs de référence", max_length=120, blank=True)
    interpretation = models.CharField("Interprétation", max_length=120, blank=True)
    observation = models.TextField("Observation", blank=True)
    statut = models.CharField(
        "Statut", max_length=24, choices=Statut.choices, default=Statut.EN_SAISIE,
    )
    saisi_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="resultats_saisis", verbose_name="Saisi par",
    )
    valide_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="resultats_valides", verbose_name="Validé par",
    )
    date_saisie = models.DateTimeField("Date de saisie", auto_now_add=True)
    date_modification = models.DateTimeField("Dernière modification", auto_now=True)
    date_validation = models.DateTimeField("Date de validation", null=True, blank=True)

    class Meta:
        ordering = ["-date_saisie"]
        permissions = [
            ("valider_resultat", "Peut valider les résultats d’analyses"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["analyse_demandee", "prelevement"],
                name="unique_resultat_analyse_prelevement",
            ),
        ]
        verbose_name = "Résultat"
        verbose_name_plural = "Résultats"

    @property
    def potentiellement_anormal(self):
        """Repère une valeur numérique hors plage sans en déduire de diagnostic."""
        analyse = self.analyse_demandee.type_analyse
        try:
            numeric_value = Decimal(self.valeur.strip().replace(",", "."))
        except (InvalidOperation, TypeError, ValueError):
            return False
        if numeric_value is None:
            return False
        return (
            (analyse.valeur_reference_min is not None and numeric_value < analyse.valeur_reference_min)
            or (analyse.valeur_reference_max is not None and numeric_value > analyse.valeur_reference_max)
        )

    def __str__(self):
        return f"{self.analyse_demandee.type_analyse.nom} — {self.valeur}"


class HistoriqueAction(models.Model):
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="actions_laboratoire", verbose_name="Utilisateur",
    )
    type_action = models.CharField("Action", max_length=40)
    objet_concerne = models.CharField("Objet concerné", max_length=80)
    objet_id = models.PositiveBigIntegerField("Identifiant de l’objet", null=True, blank=True)
    date_action = models.DateTimeField("Date de l’action", auto_now_add=True)
    details = models.JSONField("Détails", default=dict, blank=True)

    class Meta:
        ordering = ["-date_action", "-pk"]
        verbose_name = "Action de laboratoire"
        verbose_name_plural = "Historique des actions"

    def __str__(self):
        return f"{self.type_action} — {self.objet_concerne} #{self.objet_id or '—'}"
