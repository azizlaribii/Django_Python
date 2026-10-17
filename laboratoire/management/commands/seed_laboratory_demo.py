from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import Group
from django.db import transaction

from accounts.models import AssociationMedecinPatient, User
from laboratoire.models import (
    AnalyseDemandee,
    DemandeAnalyse,
    HistoriqueAction,
    TypeAnalyse,
)


class Command(BaseCommand):
    help = "Prépare des comptes et des demandes de démonstration pour le module Laboratoire."

    @transaction.atomic
    def handle(self, *args, **options):
        call_command("seed_demo_data", stdout=self.stdout)
        try:
            doctor = User.objects.get(username="dr_moreau")
            patient = User.objects.get(username="patient_martin")
            laboratory = User.objects.get(username="labo_pasteur")
        except User.DoesNotExist as error:
            raise CommandError("Les comptes de démonstration n’ont pas pu être créés.") from error

        former_biologist = User.objects.filter(username="bio_pasteur").first()
        if former_biologist:
            for group_name in (
                "Équipe Laboratoire Pasteur",
                "Biologistes et responsables de validation",
            ):
                group = Group.objects.filter(name=group_name).first()
                if group:
                    group.user_set.remove(former_biologist)
            has_audit_history = (
                HistoriqueAction.objects.filter(utilisateur=former_biologist).exists()
                or former_biologist.resultats_saisis.exists()
                or former_biologist.resultats_valides.exists()
                or former_biologist.demandes_laboratoire.exists()
                or former_biologist.analyses_realisees.exists()
                or former_biologist.mouvements_stock.exists()
            )
            if has_audit_history:
                former_biologist.set_unusable_password()
                former_biologist.is_active = False
                former_biologist.save(update_fields=["password", "is_active"])
                self.stdout.write(self.style.WARNING(
                    "bio_pasteur a été désactivé pour préserver ses résultats et son historique."
                ))
            else:
                former_biologist.delete()
                self.stdout.write("Ancien compte bio_pasteur supprimé.")

        laboratory_team, _ = Group.objects.get_or_create(
            name="Équipe Laboratoire Pasteur",
        )
        laboratory_team.user_set.add(laboratory)
        self.stdout.write("Compte de démonstration du laboratoire : labo_pasteur.")

        AssociationMedecinPatient.objects.get_or_create(
            medecin=doctor,
            patient=patient,
            defaults={"est_medecin_traitant": True, "notes": "Association de démonstration laboratoire."},
        )

        analysis_types = [
            {
                "code": "DEMO-GLY",
                "nom": "Glycémie (démo)",
                "unite": "g/L",
                "valeur_reference_min": "0.700",
                "valeur_reference_max": "1.100",
            },
            {
                "code": "DEMO-NFS",
                "nom": "Hémogramme (démo)",
                "unite": "G/L",
                "valeur_reference_min": "4.000",
                "valeur_reference_max": "10.000",
            },
        ]
        types = []
        for fields in analysis_types:
            defaults = {key: value for key, value in fields.items() if key != "code"}
            item, _ = TypeAnalyse.objects.get_or_create(code=fields["code"], defaults=defaults)
            types.append(item)

        demande_ids = {}
        for code, label in (
            ("ANNULATION", "DEMO_LABO: à annuler par le médecin"),
            ("PARCOURS", "DEMO_LABO: parcours complet"),
        ):
            demande, _ = DemandeAnalyse.objects.get_or_create(
                medecin=doctor,
                patient=patient,
                commentaire=label,
                defaults={
                    "laboratoire": laboratory,
                    "priorite": DemandeAnalyse.Priorite.URGENTE if code == "PARCOURS"
                    else DemandeAnalyse.Priorite.NORMALE,
                    "cree_par": doctor,
                },
            )
            if demande.laboratoire_id != laboratory.pk:
                previous_laboratory_id = demande.laboratoire_id
                demande.laboratoire = laboratory
                demande.save(update_fields=["laboratoire"])
                HistoriqueAction.objects.create(
                    utilisateur=None,
                    type_action="DEMANDE_LABO_DEMO_REAFFECTEE",
                    objet_concerne="DemandeAnalyse",
                    objet_id=demande.pk,
                    details={
                        "ancien_laboratoire_id": previous_laboratory_id,
                        "laboratoire_id": laboratory.pk,
                    },
                )
            for item in types:
                AnalyseDemandee.objects.get_or_create(demande=demande, type_analyse=item)
            demande_ids[code] = demande.pk

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Données de démonstration du laboratoire prêtes."))
        self.stdout.write(
            "Comptes : dr_moreau / docteur123, labo_pasteur / labo123, "
            "patient_martin / patient123, admin / admin123"
        )
        self.stdout.write(f"Demande à annuler : #{demande_ids['ANNULATION']}")
        self.stdout.write(f"Demande du parcours complet : #{demande_ids['PARCOURS']}")
        self.stdout.write("Catalogue : DEMO-GLY et DEMO-NFS")
        self.stdout.write(
            "Aucune donnée médicale n’est supprimée; l’ancien compte biologiste est "
            "supprimé uniquement s’il n’a aucune trace liée, sinon il est désactivé."
        )
