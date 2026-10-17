from django.core.management.base import BaseCommand

from stock.services import get_alertes


class Command(BaseCommand):
    help = "Affiche les alertes de stock (rupture, stock faible, péremption). " \
           "À planifier (cron) ou à relier au module Notifications."

    def handle(self, *args, **options):
        libelles = {
            "rupture": "En rupture", "faible": "Stock faible",
            "expire": "Périmés (encore en stock)", "bientot": "Péremption proche",
        }
        total = 0
        for cle, qs in get_alertes().items():
            produits = list(qs)
            total += len(produits)
            self.stdout.write(self.style.WARNING(f"\n{libelles[cle]} : {len(produits)}"))
            for p in produits:
                date = p.date_peremption.strftime("%d/%m/%Y") if p.date_peremption else "-"
                self.stdout.write(f"  - {p.nom} [{p.reference}] qté={p.quantite} (seuil {p.seuil_alerte}) péremption={date}")
        if total == 0:
            self.stdout.write(self.style.SUCCESS("Aucune alerte de stock."))
        # TODO (Notifications) : créer une notification interne / SMS pour chaque produit ici.
