from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from stock.models import Categorie, MouvementStock, Produit
from stock.services import enregistrer_mouvement


class Command(BaseCommand):
    help = "Crée des catégories et des produits de démonstration pour le module Stocks."

    def handle(self, *args, **options):
        today = timezone.localdate()
        user = get_user_model().objects.filter(is_superuser=True).first()
        cats = {n: Categorie.objects.get_or_create(nom=n)[0]
                for n in ["Consommables", "Médicaments", "Matériel d’injection", "Réactifs de laboratoire", "Hygiène & protection"]}

        # (nom, catégorie, unité, quantité, seuil, jours avant péremption ou None)
        demo = [
            ("Gants d’examen nitrile (M)", "Hygiène & protection", "BOITE", 40, 10, 400),
            ("Masques chirurgicaux", "Hygiène & protection", "BOITE", 6, 10, 200),
            ("Seringues 5 mL", "Matériel d’injection", "BOITE", 0, 8, 300),
            ("Tubes de prélèvement EDTA", "Réactifs de laboratoire", "PAQUET", 25, 10, 20),
            ("Compresses stériles 10x10", "Consommables", "PAQUET", 60, 15, 500),
            ("Sérum physiologique 500 mL", "Consommables", "FLACON", 12, 5, -10),
            ("Paracétamol 1 g", "Médicaments", "BOITE", 30, 10, None),
        ]
        crees = 0
        for nom, cat, unite, qte, seuil, jours in demo:
            if Produit.objects.filter(nom=nom).exists():
                continue
            vraie_date = (today + timedelta(days=jours)) if jours is not None else None
            # Création avec une date future : les entrées sont refusées sur un produit déjà périmé.
            p = Produit.objects.create(
                nom=nom, categorie=cats[cat], unite=unite, seuil_alerte=seuil,
                date_peremption=max(vraie_date, today + timedelta(days=1)) if vraie_date else None,
                fournisseur="MediSupply", emplacement="Réserve centrale",
            )
            if qte:
                enregistrer_mouvement(produit=p, type_mouvement=MouvementStock.Type.ENTREE, quantite=qte,
                                      motif=MouvementStock.Motif.INITIAL, utilisateur=user,
                                      commentaire="Données de démonstration")
            if vraie_date and vraie_date <= today:  # produit périmé : date appliquée après l'entrée de stock
                Produit.objects.filter(pk=p.pk).update(date_peremption=vraie_date)
            crees += 1
        self.stdout.write(self.style.SUCCESS(f"{crees} produit(s) de démonstration créé(s)."))
