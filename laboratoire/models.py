import uuid
from decimal import Decimal, InvalidOperation


from django.conf import settings

from django.core.exceptions import ValidationError

from django.core.validators import FileExtensionValidator, MinValueValidator

from django.db import models

from django.utils import timezone


def motifs_rejet_par_defaut():

    return [
        "Échantillon hémolysé",
        "Quantité insuffisante",
        "Mauvais tube",
        "Étiquette illisible",
        "Autre",
    ]


def generer_code_prelevement():
    return f"LAB-{uuid.uuid4().hex[:12].upper()}"


class TypeAnalyse(models.Model):

    class TypeEchantillon(models.TextChoices):
        SANG = "SANG", "Sang"
        URINE = "URINE", "Urine"
        AUTRE = "AUTRE", "Autre"

    code = models.CharField("Code", max_length=30, unique=True)

    nom = models.CharField("Nom", max_length=150)

    description = models.TextField("Description", blank=True)

    unite = models.CharField("Unité", max_length=30, blank=True)

    type_echantillon = models.CharField(
        "Type d’échantillon",
        max_length=10,
        choices=TypeEchantillon.choices,
        default=TypeEchantillon.SANG,
    )

    valeur_reference_min = models.DecimalField(

        "Valeur de référence minimale", max_digits=12, decimal_places=3,

        null=True, blank=True,

    )

    valeur_reference_max = models.DecimalField(

        "Valeur de référence maximale", max_digits=12, decimal_places=3,

        null=True, blank=True,

    )

    seuil_critique_bas = models.DecimalField(

        "Seuil critique bas", max_digits=12, decimal_places=3,

        null=True, blank=True,

    )

    seuil_critique_haut = models.DecimalField(

        "Seuil critique haut", max_digits=12, decimal_places=3,

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

        if (

            self.seuil_critique_bas is not None

            and self.seuil_critique_haut is not None

            and self.seuil_critique_bas > self.seuil_critique_haut

        ):

            raise ValidationError({

                "seuil_critique_haut": "Le seuil critique haut doit être supérieur au seuil critique bas."

            })


    def __str__(self):

        return f"{self.nom} ({self.code})"


class BilanPredefini(models.Model):

    nom = models.CharField("Nom du bilan", max_length=150, unique=True)

    description = models.TextField("Description", blank=True)

    analyses = models.ManyToManyField(

        TypeAnalyse, related_name="bilans", verbose_name="Analyses",

        blank=True,

    )

    actif = models.BooleanField("Actif", default=True)


    class Meta:

        ordering = ["nom"]

        verbose_name = "Bilan prédéfini"

        verbose_name_plural = "Bilans prédéfinis"


    def __str__(self):

        return self.nom


class ParametresLaboratoire(models.Model):

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    nom = models.CharField("Nom du laboratoire", max_length=150, blank=True)

    adresse = models.CharField("Adresse", max_length=255, blank=True)

    telephone = models.CharField("Téléphone", max_length=30, blank=True)

    logo = models.FileField(

        "Logo", upload_to="laboratoire/logos/", blank=True,

        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])],

    )

    entete_compte_rendu = models.TextField("En-tête du compte rendu PDF", blank=True)

    signature_compte_rendu = models.TextField("Signature du compte rendu PDF", blank=True)

    motifs_rejet = models.JSONField(

        "Motifs de rejet d’échantillon",

        default=motifs_rejet_par_defaut,

        blank=True,

    )

    delai_alerte_urgente_minutes = models.PositiveIntegerField(

        "Délai d’alerte pour une demande urgente (minutes)",

        default=60,

        validators=[MinValueValidator(1)],

    )


    class Meta:

        verbose_name = "Paramètres du laboratoire"

        verbose_name_plural = "Paramètres du laboratoire"


    def clean(self):

        super().clean()

        if not isinstance(self.motifs_rejet, list) or any(

            not isinstance(motif, str) or not motif.strip()

            for motif in self.motifs_rejet

        ):

            raise ValidationError({

                "motifs_rejet": "Saisissez une liste de motifs non vides."

            })


    @classmethod
    def get_solo(cls):
        """Retourne l'unique ligne de paramètres du laboratoire (pk=1)."""
        instance, _ = cls.objects.get_or_create(pk=1)
        return instance


    def __str__(self):

        return self.nom or "Paramètres du laboratoire"


class DemandeAnalyse(models.Model):

    class Priorite(models.TextChoices):

        NORMALE = "NORMALE", "Normale"

        HAUTE = "HAUTE", "Haute"

        URGENTE = "URGENTE", "Urgente"


    class Statut(models.TextChoices):

        EN_ATTENTE = "EN_ATTENTE", "À faire"

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

    motif_annulation = models.TextField("Motif d’annulation", blank=True)

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

        if self.priorite == self.Priorite.URGENTE and not self.commentaire.strip():
            errors["commentaire"] = "Motif médical obligatoire pour une demande urgente."

        if self.statut == self.Statut.ANNULEE and not self.motif_annulation.strip():
            errors["motif_annulation"] = "Le motif est obligatoire pour annuler une demande."

        if errors:

            raise ValidationError(errors)


    def __str__(self):

        return f"Demande #{self.pk} — {self.patient}"

    def update_statut_from_analyses(self):
        if self.statut == self.Statut.ANNULEE:
            return False
        statuts = list(
            self.analyses.exclude(statut=AnalyseDemandee.Statut.ANNULEE)
            .values_list("statut", flat=True)
        )
        if not statuts:
            return False
        if all(status == AnalyseDemandee.Statut.TERMINEE for status in statuts):
            new_status = self.Statut.TERMINEE
        elif any(
            status in (AnalyseDemandee.Statut.EN_COURS, AnalyseDemandee.Statut.TERMINEE)
            for status in statuts
        ):
            new_status = self.Statut.EN_COURS
        else:
            new_status = self.Statut.EN_ATTENTE
        if self.statut == new_status:
            return False
        self.statut = new_status
        self.save(update_fields=["statut"])
        return True


class AnalyseDemandee(models.Model):

    class Statut(models.TextChoices):

        EN_ATTENTE = "EN_ATTENTE", "À faire"

        EN_COURS = "EN_COURS", "En cours"

        TERMINEE = "TERMINEE", "Terminée"

        ANNULEE = "ANNULEE", "Annulée"


    demande = models.ForeignKey(

        DemandeAnalyse, on_delete=models.CASCADE, related_name="analyses",

    )

    type_analyse = models.ForeignKey(

        TypeAnalyse, on_delete=models.PROTECT, related_name="demandes",

    )

    prelevement = models.ForeignKey(
        "Prelevement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analyses",
        verbose_name="Prélèvement",
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

    def update_statut_from_resultats(self):
        if self.statut == self.Statut.ANNULEE:
            return False
        if self.prelevement_id:
            new_status = {
                Prelevement.Statut.A_EFFECTUER: self.Statut.EN_ATTENTE,
                Prelevement.Statut.PRELEVE: self.Statut.EN_COURS,
                Prelevement.Statut.RECU: self.Statut.EN_COURS,
                Prelevement.Statut.TERMINE: self.Statut.TERMINEE,
                Prelevement.Statut.REJETE: self.Statut.EN_ATTENTE,
                Prelevement.Statut.ANNULE: self.Statut.ANNULEE,
            }[self.prelevement.statut]
        else:
            resultat = self.resultats.filter(statut=Resultat.Statut.VALIDE).exists()
            new_status = self.Statut.TERMINEE if resultat else self.Statut.EN_ATTENTE
        if self.statut == new_status:
            return False
        self.statut = new_status
        self.save(update_fields=["statut"])
        self.demande.update_statut_from_analyses()
        return True


class Prelevement(models.Model):

    class Type(models.TextChoices):

        SANG = "SANG", "Sang"

        URINE = "URINE", "Urine"

        AUTRE = "AUTRE", "Autre"


    class Statut(models.TextChoices):

        A_EFFECTUER = "A_EFFECTUER", "À faire"

        PRELEVE = "PRELEVE", "Prise de sang faite"

        RECU = "RECU", "Tube reçu"

        REJETE = "REJETE", "Refusé"

        ANNULE = "ANNULE", "Annulé"

        TERMINE = "TERMINE", "Terminé"


    demande = models.ForeignKey(

        DemandeAnalyse, on_delete=models.PROTECT, related_name="prelevements",

        verbose_name="Demande",

    )

    code_prelevement = models.CharField(
        "Code du prélèvement", max_length=40, unique=True,
        default=generer_code_prelevement,
    )

    type_prelevement = models.CharField("Type", max_length=10, choices=Type.choices)

    precision_type = models.CharField("Précision du type", max_length=120, blank=True)

    date_prelevement = models.DateTimeField("Date du prélèvement", null=True, blank=True)

    date_reception = models.DateTimeField("Date de réception", null=True, blank=True)

    date_creation = models.DateTimeField("Date de création", auto_now_add=True)

    preleve_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prelevements_effectues",
        verbose_name="Prélevé par",
    )

    recu_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prelevements_recus",
        verbose_name="Reçu par",
    )

    prelevement_precedent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reprises",
        verbose_name="Prélèvement précédent",
    )

    statut = models.CharField(

        "Statut", max_length=12, choices=Statut.choices, default=Statut.A_EFFECTUER,

    )

    motif_rejet = models.TextField("Motif du rejet", blank=True)

    remarque = models.TextField("Remarque", blank=True)


    class Meta:

        ordering = ["-date_creation"]

        verbose_name = "Prélèvement"

        verbose_name_plural = "Prélèvements"


    def clean(self):

        super().clean()

        errors = {}
        now = timezone.now()
        if self.statut == self.Statut.A_EFFECTUER and (
            self.date_prelevement or self.date_reception
        ):
            errors["statut"] = "Un prélèvement à faire ne peut pas avoir de date de prélèvement ou de réception."
        if self.date_prelevement and self.date_prelevement > now:
            errors["date_prelevement"] = "La date du prélèvement ne peut pas être dans le futur."
        if self.date_reception and self.date_reception > now:
            errors["date_reception"] = "La date de réception ne peut pas être dans le futur."
        if (
            self.date_prelevement and self.date_reception
            and self.date_reception < self.date_prelevement
        ):
            errors["date_reception"] = "La réception ne peut pas précéder le prélèvement."
        if self.statut == self.Statut.REJETE:
            motifs = ParametresLaboratoire.get_solo().motifs_rejet
            if not self.motif_rejet.strip():
                errors["motif_rejet"] = "Le motif est obligatoire pour refuser un prélèvement."
            elif self.motif_rejet not in motifs:
                errors["motif_rejet"] = "Choisissez un motif de refus proposé."
            elif self.motif_rejet == "Autre" and not self.remarque.strip():
                errors["remarque"] = "Ajoutez une précision lorsque le motif choisi est « Autre »."

        if self.demande_id and self.demande.statut == DemandeAnalyse.Statut.ANNULEE:

            errors["demande"] = "La demande associée est annulée."

        if errors:
            raise ValidationError(errors)


    def __str__(self):

        return f"{self.code_prelevement} — demande #{self.demande_id}"


class Resultat(models.Model):

    class Statut(models.TextChoices):

        EN_SAISIE = "EN_SAISIE", "En saisie"
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

    version = models.PositiveIntegerField("Version", default=1)

    motif_correction = models.TextField("Motif de correction", blank=True)

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

        constraints = [

            models.UniqueConstraint(

                fields=["analyse_demandee"],

                name="unique_resultat_par_analyse",

            ),

        ]

        verbose_name = "Résultat"

        verbose_name_plural = "Résultats"


    @property
    def _valeur_decimal(self):
        try:
            return Decimal(self.valeur.strip().replace(",", "."))
        except (InvalidOperation, TypeError, ValueError, AttributeError):
            return None

    @property
    def potentiellement_anormal(self):

        """Repère une valeur numérique hors plage sans en déduire de diagnostic."""

        analyse = self.analyse_demandee.type_analyse

        numeric_value = self._valeur_decimal
        if numeric_value is None:
            return False
        return (

            (analyse.valeur_reference_min is not None and numeric_value < analyse.valeur_reference_min)

            or (analyse.valeur_reference_max is not None and numeric_value > analyse.valeur_reference_max)

        )


    @property

    def potentiellement_critique(self):

        analyse = self.analyse_demandee.type_analyse

        numeric_value = self._valeur_decimal
        if numeric_value is None:
            return False

        return (
            (analyse.seuil_critique_bas is not None and numeric_value <= analyse.seuil_critique_bas)
            or (analyse.seuil_critique_haut is not None and numeric_value >= analyse.seuil_critique_haut)
        )

    @property
    def interpretation_automatique(self):
        analyse = self.analyse_demandee.type_analyse
        numeric_value = self._valeur_decimal
        if numeric_value is None:
            return "À interpréter"
        if self.potentiellement_critique:
            return "Critique"
        if (
            analyse.valeur_reference_min is not None
            and numeric_value < analyse.valeur_reference_min
        ):
            return "Bas"
        if (
            analyse.valeur_reference_max is not None
            and numeric_value > analyse.valeur_reference_max
        ):
            return "Élevé"
        return "Normal"


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


class CompteRendu(models.Model):
    class Source(models.TextChoices):
        REGLES = "regles", "Résumé automatique (règles)"
        IA = "ia", "Généré par IA"

    class Statut(models.TextChoices):
        BROUILLON = "brouillon", "Brouillon"
        APPROUVE = "approuve", "Approuvé"

    demande = models.ForeignKey(
        DemandeAnalyse,
        on_delete=models.CASCADE,
        related_name="comptes_rendus",
        verbose_name="Demande d’analyses",
    )
    medecin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="comptes_rendus_laboratoire",
        verbose_name="Médecin prescripteur",
    )
    texte_genere = models.TextField("Texte généré")
    texte_final = models.TextField("Texte final", blank=True)
    note_medecin = models.TextField("Observations du médecin", blank=True)
    analyse_evolution_ia = models.TextField("Analyse IA de l’évolution", blank=True)
    modele_evolution_ia = models.CharField(
        "Modèle IA de l’évolution",
        max_length=100,
        blank=True,
    )
    generee_evolution_ia_le = models.DateTimeField(
        "Analyse IA générée le",
        null=True,
        blank=True,
    )
    source = models.CharField(
        "Source du résumé",
        max_length=10,
        choices=Source.choices,
        default=Source.REGLES,
    )
    statut = models.CharField(
        "Statut",
        max_length=12,
        choices=Statut.choices,
        default=Statut.BROUILLON,
    )
    cree_le = models.DateTimeField("Créé le", auto_now_add=True)
    approuve_le = models.DateTimeField("Approuvé le", null=True, blank=True)

    class Meta:
        ordering = ["-cree_le", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["demande"],
                name="unique_compte_rendu_par_demande",
            ),
        ]
        verbose_name = "Compte rendu descriptif"
        verbose_name_plural = "Comptes rendus descriptifs"

    def __str__(self):
        return f"Compte rendu de la demande #{self.demande_id}"
