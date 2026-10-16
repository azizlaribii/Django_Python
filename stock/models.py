from datetime import timedelta

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


def seuil_peremption_jours():
    """Nombre de jours avant la péremption à partir duquel un produit est signalé.

    Modifiable globalement dans settings.py : STOCK_ALERTE_PEREMPTION_JOURS = 30
    """
    return getattr(settings, "STOCK_ALERTE_PEREMPTION_JOURS", 30)


class Categorie(models.Model):
    nom = models.CharField("Nom", max_length=100, unique=True)
    description = models.CharField("Description", max_length=255, blank=True)

    class Meta:
        verbose_name = "Catégorie"
        verbose_name_plural = "Catégories"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class ProduitQuerySet(models.QuerySet):
    def actifs(self):
        return self.filter(actif=True)

    def en_rupture(self):
        return self.filter(quantite=0)

    def stock_faible(self):
        return self.filter(quantite__gt=0, quantite__lte=F("seuil_alerte"))

    def expires(self):
        return self.filter(date_peremption__lt=timezone.localdate())

    def bientot_perimes(self):
        aujourdhui = timezone.localdate()
        limite = aujourdhui + timedelta(days=seuil_peremption_jours())
        return self.filter(date_peremption__gte=aujourdhui, date_peremption__lte=limite)

    def normaux(self):
        limite = timezone.localdate() + timedelta(days=seuil_peremption_jours())
        return self.filter(quantite__gt=F("seuil_alerte")).filter(
            Q(date_peremption__isnull=True) | Q(date_peremption__gt=limite)
        )


class Produit(models.Model):
    class Unite(models.TextChoices):
        UNITE = "UNITE", "Unité"
        BOITE = "BOITE", "Boîte"
        PAQUET = "PAQUET", "Paquet"
        FLACON = "FLACON", "Flacon"
        SACHET = "SACHET", "Sachet"
        KIT = "KIT", "Kit"
        LITRE = "LITRE", "Litre"

    nom = models.CharField("Nom du produit", max_length=150)
    reference = models.CharField(
        "Référence", max_length=50, unique=True, null=True, blank=True,
        help_text="Laissez vide pour générer automatiquement (PRD-00001...).",
    )
    categorie = models.ForeignKey(
        Categorie, verbose_name="Catégorie", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="produits",
    )
    unite = models.CharField("Unité", max_length=10, choices=Unite.choices, default=Unite.UNITE)
    fournisseur = models.CharField("Fournisseur", max_length=150, blank=True)
    emplacement = models.CharField(
        "Emplacement de stockage", max_length=100, blank=True,
        help_text="Ex. : Armoire B, étagère 2.",
    )
    prix_unitaire = models.DecimalField(
        "Prix unitaire (€)", max_digits=8, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
    )
    quantite = models.PositiveIntegerField("Quantité en stock", default=0, editable=False)
    seuil_alerte = models.PositiveIntegerField(
        "Seuil d’alerte", default=10,
        help_text="Une alerte est affichée lorsque la quantité est inférieure ou égale à ce seuil.",
    )
    date_peremption = models.DateField(
        "Date de péremption", null=True, blank=True,
        help_text="Laissez vide pour un produit sans date de péremption.",
    )
    description = models.TextField("Description", blank=True)
    actif = models.BooleanField("Actif", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProduitQuerySet.as_manager()

    class Meta:
        verbose_name = "Produit médical"
        verbose_name_plural = "Produits médicaux"
        ordering = ["nom"]

    def __str__(self):
        return f"{self.nom} ({self.reference})" if self.reference else self.nom

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.reference:
            self.reference = f"PRD-{self.pk:05d}"
            super().save(update_fields=["reference"])

    # --- État du stock -------------------------------------------------
    @property
    def jours_avant_peremption(self):
        if not self.date_peremption:
            return None
        return (self.date_peremption - timezone.localdate()).days

    @property
    def est_expire(self):
        jours = self.jours_avant_peremption
        return jours is not None and jours < 0

    @property
    def bientot_perime(self):
        jours = self.jours_avant_peremption
        return jours is not None and 0 <= jours <= seuil_peremption_jours()

    @property
    def en_rupture(self):
        return self.quantite == 0

    @property
    def stock_faible(self):
        return 0 < self.quantite <= self.seuil_alerte

    @property
    def valeur_stock(self):
        if self.prix_unitaire is None:
            return None
        return self.prix_unitaire * self.quantite

    @property
    def statuts(self):
        """Liste de (code, libellé, classe CSS) : un produit peut cumuler plusieurs états."""
        res = []
        jours = self.jours_avant_peremption
        if self.est_expire:
            res.append(("expire", "Périmé", "danger"))
        elif self.bientot_perime:
            texte = "Expire aujourd’hui" if jours == 0 else f"Expire dans {jours} j"
            res.append(("bientot", texte, "pending"))
        if self.en_rupture:
            res.append(("rupture", "Rupture", "danger"))
        elif self.stock_faible:
            res.append(("faible", "Stock faible", "pending"))
        if not res:
            res.append(("normal", "Disponible", "verified"))
        return res


MOTIFS_ENTREE = ("INITIAL", "ACHAT", "RETOUR", "AJUSTEMENT_PLUS")
MOTIFS_SORTIE = ("UTILISATION", "PEREMPTION", "PERTE", "AJUSTEMENT_MOINS")


class MouvementStock(models.Model):
    class Type(models.TextChoices):
        ENTREE = "ENTREE", "Entrée"
        SORTIE = "SORTIE", "Sortie"

    class Motif(models.TextChoices):
        INITIAL = "INITIAL", "Stock initial"
        ACHAT = "ACHAT", "Réception / achat"
        RETOUR = "RETOUR", "Retour en stock"
        AJUSTEMENT_PLUS = "AJUSTEMENT_PLUS", "Ajustement d’inventaire (+)"
        UTILISATION = "UTILISATION", "Utilisation / consommation"
        PEREMPTION = "PEREMPTION", "Mise au rebut (péremption)"
        PERTE = "PERTE", "Casse / perte"
        AJUSTEMENT_MOINS = "AJUSTEMENT_MOINS", "Ajustement d’inventaire (−)"

    produit = models.ForeignKey(Produit, on_delete=models.PROTECT, related_name="mouvements")
    type = models.CharField("Type", max_length=10, choices=Type.choices)
    motif = models.CharField("Motif", max_length=20, choices=Motif.choices)
    quantite = models.PositiveIntegerField("Quantité", validators=[MinValueValidator(1)])
    stock_apres = models.PositiveIntegerField("Stock après mouvement")
    numero_lot = models.CharField("N° de lot", max_length=50, blank=True)
    commentaire = models.CharField("Commentaire", max_length=255, blank=True)
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="mouvements_stock", verbose_name="Effectué par",
    )
    date = models.DateTimeField("Date", auto_now_add=True)

    class Meta:
        verbose_name = "Mouvement de stock"
        verbose_name_plural = "Mouvements de stock"
        ordering = ["-date", "-id"]

    @property
    def auteur(self):
        u = self.utilisateur
        return (u.get_full_name() or u.username) if u else "—"

    def __str__(self):
        signe = "+" if self.type == self.Type.ENTREE else "−"
        return f"{self.produit.nom} {signe}{self.quantite}"
