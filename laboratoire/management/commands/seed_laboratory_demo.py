from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from decimal import Decimal

from accounts.models import AssociationMedecinPatient, User
from laboratoire.models import (
    AnalyseDemandee,
    CompteRendu,
    DemandeAnalyse,
    HistoriqueAction,
    Prelevement,
    Resultat,
    TypeAnalyse,
)
from laboratoire.services import changer_statut, creer_prelevements, synchroniser


class Command(BaseCommand):
    help = "Prépare trois demandes fictives pour tester le workflow du Laboratoire."

    @transaction.atomic
    def handle(self, *args, **options):
        call_command("seed_demo_data", stdout=self.stdout)
        try:
            doctor = User.objects.get(username="dr_moreau")
            patient = User.objects.get(username="patient_martin")
            laboratory = User.objects.get(username="labo_pasteur")
        except User.DoesNotExist as error:
            raise CommandError("Les comptes de démonstration n’ont pas pu être créés.") from error

        type_analyse = TypeAnalyse.objects.filter(actif=True).first()
        if type_analyse is None:
            raise CommandError(
                "Aucune analyse active dans le catalogue. Ajoutez une analyse avant de préparer la démo."
            )

        AssociationMedecinPatient.objects.get_or_create(
            medecin=doctor,
            patient=patient,
            defaults={
                "est_medecin_traitant": True,
                "notes": "Association de démonstration laboratoire.",
            },
        )

        self._supprimer_anciennes_donnees_demo()
        scenarios = (
            ("01", "À traiter", Prelevement.Statut.A_EFFECTUER),
            ("02", "Résultats à saisir", Prelevement.Statut.RECU),
            ("03", "Résultats publiés", Prelevement.Statut.TERMINE),
        )

        for numero, label, sample_status in scenarios:
            demande = DemandeAnalyse.objects.create(
                patient=patient,
                medecin=doctor,
                laboratoire=laboratory,
                priorite=DemandeAnalyse.Priorite.NORMALE,
                cree_par=doctor,
                commentaire=f"DEMO_LABO: {numero}/3 — {label}",
            )
            analyse = AnalyseDemandee.objects.create(
                demande=demande,
                type_analyse=type_analyse,
            )
            prelevement = creer_prelevements(demande, utilisateur=laboratory)[0]

            if sample_status in (Prelevement.Statut.RECU, Prelevement.Statut.TERMINE):
                changer_statut(
                    prelevement,
                    Prelevement.Statut.PRELEVE,
                    laboratory,
                )
                prelevement = changer_statut(
                    prelevement,
                    Prelevement.Statut.RECU,
                    laboratory,
                )

            if sample_status == Prelevement.Statut.TERMINE:
                Resultat.objects.create(
                    analyse_demandee=analyse,
                    prelevement=prelevement,
                    valeur=self._valeur_demo(type_analyse),
                    unite=type_analyse.unite,
                    saisi_par=laboratory,
                    valide_par=laboratory,
                    statut=Resultat.Statut.VALIDE,
                    date_validation=timezone.now(),
                )
                synchroniser(prelevement, utilisateur=laboratory)

            HistoriqueAction.objects.create(
                utilisateur=doctor,
                type_action="DEMANDE_LABO_DEMO_CREEE",
                objet_concerne="DemandeAnalyse",
                objet_id=demande.pk,
                details={"scenario": label, "donnees_fictives": True},
            )
            self.stdout.write(f"Demande #{demande.pk} : {label}.")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Trois scénarios de démonstration sont prêts."))
        self.stdout.write(
            "Comptes : dr_moreau / docteur123, labo_pasteur / labo123, "
            "patient_martin / patient123, admin / admin123"
        )

    @staticmethod
    def _valeur_demo(type_analyse):
        minimum = type_analyse.valeur_reference_min
        maximum = type_analyse.valeur_reference_max
        if minimum is not None and maximum is not None:
            return str((minimum + maximum) / Decimal("2"))
        if minimum is not None:
            return str(minimum)
        if maximum is not None:
            return str(maximum)
        return "1.0"

    def _supprimer_anciennes_donnees_demo(self):
        demande_ids = list(
            DemandeAnalyse.objects.filter(
                commentaire__startswith="DEMO_LABO:",
            ).values_list("pk", flat=True)
        )
        if not demande_ids:
            return

        Resultat.objects.filter(
            analyse_demandee__demande_id__in=demande_ids,
        ).delete()
        Prelevement.objects.filter(demande_id__in=demande_ids).delete()
        CompteRendu.objects.filter(demande_id__in=demande_ids).delete()
        DemandeAnalyse.objects.filter(pk__in=demande_ids).delete()
