from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone

class Tarif(models.Model):
    class Categorie(models.TextChoices):
        CONSULTATION = 'CONSULTATION', 'Consultation'
        EXAMEN = 'EXAMEN', 'Examen'
        ANALYSE = 'ANALYSE', 'Analyse de laboratoire'
        AUTRE = 'AUTRE', 'Autre'

    code = models.CharField("Code", max_length=30, unique=True)
    libelle = models.CharField("Libellé", max_length=150)
    categorie = models.CharField("Catégorie", max_length=20,
                                 choices=Categorie.choices, default=Categorie.CONSULTATION)
    prix = models.DecimalField("Prix", max_digits=12, decimal_places=3)
    actif = models.BooleanField("Actif", default=True)

    class Meta:
        ordering = ['categorie', 'libelle']

    def __str__(self):
        return f"{self.libelle} ({self.prix})"


class Facture(models.Model):
    class Statut(models.TextChoices):
        EN_ATTENTE = 'EN_ATTENTE', 'En attente'
        PARTIELLE = 'PARTIELLE', 'Partiellement payée'
        PAYEE = 'PAYEE', 'Payée'
        ANNULEE = 'ANNULEE', 'Annulée'

    numero = models.CharField("Numéro", max_length=20, unique=True, blank=True)
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                related_name='factures_patient',
                                limit_choices_to={'role': 'PATIENT'})
    medecin = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                related_name='factures_medecin', null=True, blank=True,
                                limit_choices_to={'role': 'DOCTEUR'})
    date_emission = models.DateField("Date d'émission", auto_now_add=True)
    statut = models.CharField("Statut", max_length=20,
                              choices=Statut.choices, default=Statut.EN_ATTENTE)
    remise = models.DecimalField("Remise", max_digits=12, decimal_places=3, default=0)
    tva = models.DecimalField("TVA (%)", max_digits=5, decimal_places=2, default=0)

    class Meta:
        ordering = ['-date_emission', '-id']

    @property
    def sous_total(self):
        return sum((l.total for l in self.lignes.all()), Decimal('0'))

    @property
    def total_ht(self):
        return max(self.sous_total - self.remise, Decimal('0'))

    @property
    def montant_tva(self):
        return (self.total_ht * self.tva / Decimal('100')).quantize(Decimal('0.001'))

    @property
    def total_ttc(self):
        return self.total_ht + self.montant_tva

        def save(self, *args, **kwargs):
        if not self.numero:
            prefixe = f"FAC-{timezone.now().year}-"
            derniere = (Facture.objects
                        .filter(numero__startswith=prefixe)
                        .order_by('-numero')
                        .first())
            suite = int(derniere.numero.split('-')[-1]) + 1 if derniere else 1
            self.numero = f"{prefixe}{suite:05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.numero or f"Facture #{self.pk}"
        
    def __str__(self):
        return self.numero or f"Facture #{self.pk}"
        


class LigneFacture(models.Model):
    facture = models.ForeignKey(Facture, on_delete=models.CASCADE, related_name='lignes')
    tarif = models.ForeignKey(Tarif, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.CharField("Description", max_length=200)
    reference = models.CharField("Référence", max_length=50, blank=True)
    quantite = models.PositiveIntegerField("Quantité", default=1)
    prix_unitaire = models.DecimalField("Prix unitaire", max_digits=12, decimal_places=3)

    @property
    def total(self):
        return self.quantite * self.prix_unitaire

    def __str__(self):
        return f"{self.description} x{self.quantite}"