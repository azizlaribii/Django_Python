from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from billing.models import Tarif, Facture, LigneFacture, Paiement


class Command(BaseCommand):
    help = "Crée des tarifs et des factures de démonstration"

    def handle(self, *args, **opts):
        User = get_user_model()
        for code, lib, cat, prix in [
            ('CONS', 'Consultation', 'CONSULTATION', '50.000'),
            ('ECG', 'Électrocardiogramme', 'EXAMEN', '80.000'),
            ('PRISE', 'Prise de sang', 'ANALYSE', '30.000'),
            ('ECHO', 'Échographie abdominale', 'EXAMEN', '90.000'),
            ('RADIO', 'Radiographie du thorax', 'EXAMEN', '60.000'),
            ('IRM', 'IRM cérébrale', 'EXAMEN', '250.000'),
        ]:
            Tarif.objects.get_or_create(code=code, defaults={
                'libelle': lib, 'categorie': cat, 'prix': Decimal(prix)})

        patient = User.objects.filter(role='PATIENT').first()
        medecin = User.objects.filter(role='DOCTEUR', is_verified=True).first()
        if not (patient and medecin):
            self.stderr.write("Il faut au moins un patient et un docteur certifié.")
            return

        f = Facture.objects.create(patient=patient, medecin=medecin, tva=Decimal('19'))
        for t in Tarif.objects.filter(code__in=['CONS', 'ECG']):
            LigneFacture.objects.create(facture=f, tarif=t, description=t.libelle,
                                        quantite=1, prix_unitaire=t.prix)
        Paiement.objects.create(facture=f, montant=Decimal('50.000'))
        self.stdout.write(self.style.SUCCESS(f"Facture {f.numero} créée."))