from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand

from laboratoire.models import Resultat


class Command(BaseCommand):
    help = "Signale les résultats numériques nuls ou négatifs sans modifier ni supprimer de données."

    def handle(self, *args, **options):
        flagged = []
        results = Resultat.objects.select_related(
            "analyse_demandee__type_analyse",
        ).order_by("pk")
        for result in results.iterator():
            numeric_text = result.valeur.strip().lstrip("<>≤≥").strip().replace(",", ".")
            try:
                numeric_value = Decimal(numeric_text)
            except (InvalidOperation, ValueError):
                continue
            if numeric_value.is_finite() and numeric_value <= 0:
                flagged.append(result)

        if not flagged:
            self.stdout.write(self.style.SUCCESS(
                "Aucun résultat numérique nul ou négatif."
            ))
            return

        self.stdout.write(
            f"Résultats à vérifier : {len(flagged)} "
            "(aucune donnée modifiée ou supprimée)"
        )
        for result in flagged:
            self.stdout.write(
                f"#{result.pk} | demande #{result.analyse_demandee.demande_id} | "
                f"{result.analyse_demandee.type_analyse.nom} | {result.valeur}"
            )
