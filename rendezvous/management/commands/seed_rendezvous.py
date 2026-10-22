"""Données de démonstration : créneaux sur 2 semaines pour chaque médecin + quelques rendez-vous.

Usage : python manage.py seed_rendezvous
Relançable sans créer de doublons (les créneaux existants sont ignorés).
"""
import random
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from rendezvous import services
from rendezvous.models import Creneau, RendezVous
from rendezvous.services import RendezVousError

User = get_user_model()
MOTIFS = [
    "Consultation de contrôle", "Renouvellement d'ordonnance", "Douleurs abdominales",
    "Suivi tension artérielle", "Résultats d'analyses", "Fièvre persistante", "Bilan annuel",
]


class Command(BaseCommand):
    help = "Crée des créneaux et des rendez-vous de démonstration."

    def add_arguments(self, parser):
        parser.add_argument("--jours", type=int, default=14, help="Nombre de jours à couvrir (défaut 14).")
        parser.add_argument("--rdv", type=int, default=12, help="Nombre de rendez-vous à créer (défaut 12).")

    def handle(self, *args, **opts):
        medecins = list(User.objects.filter(role=User.Role.DOCTEUR, is_active=True))
        patients = list(User.objects.filter(role=User.Role.PATIENT, is_active=True))
        if not medecins:
            self.stdout.write(self.style.WARNING("Aucun médecin : créez d'abord des comptes docteurs."))
            return

        aujourd_hui = timezone.localdate()
        total = 0
        for m in medecins:
            crees, _ = services.generer_creneaux(
                medecin=m, date_debut=aujourd_hui, date_fin=aujourd_hui + timedelta(days=opts["jours"]),
                jours=[0, 1, 2, 3, 4], heure_debut=time(9, 0), heure_fin=time(17, 0), duree_minutes=30,
                pause_debut=time(12, 30), pause_fin=time(14, 0),
            )
            total += crees
        self.stdout.write(f"{total} créneau(x) créé(s) pour {len(medecins)} médecin(s).")

        if not patients:
            self.stdout.write(self.style.WARNING("Aucun patient : pas de rendez-vous créé."))
            return
        rng = random.Random(42)
        libres = list(Creneau.objects.disponibles().select_related("medecin"))
        rng.shuffle(libres)
        crees = 0
        for creneau in libres:
            if crees >= opts["rdv"]:
                break
            patient = rng.choice(patients)
            par = rng.choice([patient, creneau.medecin])
            try:
                services.reserver(creneau=creneau, patient=patient, motif=rng.choice(MOTIFS), par=par)
                crees += 1
            except RendezVousError:
                continue
        self.stdout.write(self.style.SUCCESS(
            f"{crees} rendez-vous créé(s). Total en base : {RendezVous.objects.count()}."
        ))
