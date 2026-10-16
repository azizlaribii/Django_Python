from django.core.management.base import BaseCommand
from accounts.models import User, DoctorProfile, LaboratoryProfile, PatientProfile


class Command(BaseCommand):
    help = "Initialise la base de données avec des comptes de démonstration pour Admin, Docteurs, Laboratoires et Patients."

    def handle(self, *args, **options):
        self.stdout.write("Création des comptes de test...")

        # 1. Administrateur
        admin_user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@santeconnect.fr',
                'first_name': 'Admin',
                'last_name': 'Système',
                'role': User.Role.ADMIN,
                'is_staff': True,
                'is_superuser': True,
                'is_verified': True,
                'city': 'Paris',
                'phone': '+33 1 00 00 00 00',
            }
        )
        admin_user.set_password('admin123')
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.role = User.Role.ADMIN
        admin_user.save()
        self.stdout.write(self.style.SUCCESS("[OK] Compte Administrateur configure : admin / admin123"))

        # 2. Docteurs
        doc1, _ = User.objects.get_or_create(
            username='dr_moreau',
            defaults={
                'email': 'moreau@medecine.fr',
                'first_name': 'Alexandre',
                'last_name': 'Moreau',
                'role': User.Role.DOCTEUR,
                'is_verified': True,
                'city': 'Paris',
                'phone': '+33 1 42 68 00 11',
                'address': '14 Avenue de la République',
            }
        )
        doc1.set_password('docteur123')
        doc1.save()
        p1, _ = DoctorProfile.objects.get_or_create(user=doc1)
        p1.specialite = "Cardiologie & Médecine Générale"
        p1.numero_ordre = "ORD-75-9921"
        p1.cabinet_name = "Centre Médical Saint-Honoré"
        p1.horaires = "08h30 - 18h30 (Lun-Ven)"
        p1.save()

        doc2, _ = User.objects.get_or_create(
            username='dr_belkacem',
            defaults={
                'email': 'belkacem@hopital-lyon.fr',
                'first_name': 'Nadia',
                'last_name': 'Belkacem',
                'role': User.Role.DOCTEUR,
                'is_verified': False,  # En attente de certification par l'Admin !
                'city': 'Lyon',
                'phone': '+33 4 78 90 12 34',
                'address': '22 Boulevard des Belges',
            }
        )
        doc2.set_password('docteur123')
        doc2.save()
        p2, _ = DoctorProfile.objects.get_or_create(user=doc2)
        p2.specialite = "Pédiatrie & Néonatalogie"
        p2.numero_ordre = "ORD-69-4458"
        p2.cabinet_name = "Pôle Santé Enfance Lyon"
        p2.save()

        self.stdout.write(self.style.SUCCESS("[OK] Comptes Docteurs crees : dr_moreau, dr_belkacem / docteur123"))

        # 3. Laboratoires
        lab1, _ = User.objects.get_or_create(
            username='labo_pasteur',
            defaults={
                'email': 'contact@labo-pasteur.fr',
                'first_name': 'Laboratoire',
                'last_name': 'Pasteur',
                'role': User.Role.LABORATOIRE,
                'is_verified': True,
                'city': 'Paris',
                'phone': '+33 1 45 67 89 00',
                'address': '8 Rue du Docteur Roux',
            }
        )
        lab1.set_password('labo123')
        lab1.save()
        plab1, _ = LaboratoryProfile.objects.get_or_create(user=lab1)
        plab1.nom_laboratoire = "Laboratoire d'Analyses Biologiques Pasteur"
        plab1.numero_agrement = "AGR-LAB-2024-88"
        plab1.responsable = "Dr. Philippe Laurent (Biologiste)"
        plab1.services_offerts = "Hématologie, Biochimie, Immunologie, Microbiologie, Tests PCR"
        plab1.save()

        lab2, _ = User.objects.get_or_create(
            username='labo_biocentre',
            defaults={
                'email': 'secretariat@biocentre-marseille.fr',
                'first_name': 'BioCentre',
                'last_name': 'Méditerranée',
                'role': User.Role.LABORATOIRE,
                'is_verified': False,  # En attente d'agrément par l'Admin !
                'city': 'Marseille',
                'phone': '+33 4 91 22 33 44',
                'address': '45 Avenue du Prado',
            }
        )
        lab2.set_password('labo123')
        lab2.save()
        plab2, _ = LaboratoryProfile.objects.get_or_create(user=lab2)
        plab2.nom_laboratoire = "BioCentre Analyses Méditerranée"
        plab2.numero_agrement = "AGR-13-8874-B"
        plab2.responsable = "Dr. Claire Valette"
        plab2.save()

        self.stdout.write(self.style.SUCCESS("[OK] Comptes Laboratoires crees : labo_pasteur, labo_biocentre / labo123"))

        # 4. Patients
        pat1, _ = User.objects.get_or_create(
            username='patient_martin',
            defaults={
                'email': 'sophie.martin@email.fr',
                'first_name': 'Sophie',
                'last_name': 'Martin',
                'role': User.Role.PATIENT,
                'city': 'Paris',
                'phone': '+33 6 12 34 56 78',
                'address': '18 Rue de la Paix',
            }
        )
        pat1.set_password('patient123')
        pat1.save()
        ppat1, _ = PatientProfile.objects.get_or_create(user=pat1)
        ppat1.groupe_sanguin = "O+"
        ppat1.numero_securite_sociale = "2 92 05 75 142 890"
        ppat1.antecedents = "Allergie à la pénicilline. Asthme léger."
        ppat1.personne_contact = "Marc Martin (Conjoint) : +33 6 98 76 54 32"
        ppat1.save()

        pat2, _ = User.objects.get_or_create(
            username='patient_bernard',
            defaults={
                'email': 'thomas.bernard@email.fr',
                'first_name': 'Thomas',
                'last_name': 'Bernard',
                'role': User.Role.PATIENT,
                'city': 'Bordeaux',
                'phone': '+33 6 45 89 12 30',
                'address': '5 Place de la Bourse',
            }
        )
        pat2.set_password('patient123')
        pat2.save()
        ppat2, _ = PatientProfile.objects.get_or_create(user=pat2)
        ppat2.groupe_sanguin = "A-"
        ppat2.numero_securite_sociale = "1 88 11 33 245 118"
        ppat2.save()

        self.stdout.write(self.style.SUCCESS("[OK] Comptes Patients crees : patient_martin, patient_bernard / patient123"))
        self.stdout.write(self.style.SUCCESS("[OK] Base de donnees initialisee avec succes !"))

