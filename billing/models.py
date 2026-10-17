from django.db import models


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