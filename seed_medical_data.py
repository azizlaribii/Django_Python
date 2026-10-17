"""
Script de création de données de démonstration médicales.
Usage: python manage.py shell < seed_medical_data.py
ou: python manage.py runscript seed_medical_data
"""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.utils import timezone
from datetime import date, timedelta
from accounts.models import (
    User, DoctorProfile, PatientProfile, LaboratoryProfile,
    AssociationMedecinPatient, DossierMedical,
    ExamenMedical, ResultatLaboratoire, Prescription, ObservationMedicale
)

def seed():
    print("🌱 Seed des données médicales de démonstration...")

    # Récupérer les comptes existants
    try:
        docteur = User.objects.get(username='dr_moreau')
        labo = User.objects.get(username='labo_pasteur')
        patient = User.objects.get(username='patient_martin')
    except User.DoesNotExist as e:
        print(f"❌ Compte introuvable : {e}")
        print("Assurez-vous d'avoir lancé manage.py pour créer les comptes de démo.")
        return

    # Profil patient
    pp, _ = PatientProfile.objects.get_or_create(user=patient)
    pp.date_naissance = date(1985, 3, 22)
    pp.groupe_sanguin = 'O+'
    pp.numero_securite_sociale = '1 85 03 75 123 456 78'
    pp.antecedents = 'Hypertension artérielle traitée depuis 2019. Allergie pénicilline.'
    pp.personne_contact = 'Marie Martin (épouse) — 06 12 34 56 78'
    pp.save()
    print(f"  ✓ Profil patient mis à jour : {patient.get_full_name()}")

    # Dossier médical
    dossier, _ = DossierMedical.objects.get_or_create(patient=patient)
    dossier.allergies = 'Pénicilline (réaction anaphylactique), Aspirine (intolérance digestive)'
    dossier.antecedents_familiaux = 'Père : diabète type 2. Mère : hypertension artérielle.'
    dossier.notes_generales = 'Patient coopératif. Suivi régulier recommandé tous les 3 mois.'
    dossier.save()
    print(f"  ✓ Dossier médical #{ dossier.numero_dossier }")

    # Association médecin-patient
    assoc, created = AssociationMedecinPatient.objects.get_or_create(
        medecin=docteur,
        patient=patient,
        defaults={
            'est_medecin_traitant': True,
            'notes': 'Suivi hypertension et contrôle lipidique annuel.',
            'date_association': date(2023, 1, 15)
        }
    )
    if created:
        print(f"  ✓ Association Dr. {docteur.get_full_name()} ↔ {patient.get_full_name()}")

    # Examens médicaux
    # Examens médicaux
    examens_data = [
        {
            'titre': 'Consultation cardiologie',
            'type_examen': 'CONSULTATION',
            'description': 'Contrôle tension artérielle et évaluation risque cardiovasculaire',
            'date_examen': date.today() - timedelta(days=30),
            'lieu_examen': 'Cabinet Dr. Moreau — Salle 1',
            'consignes_preparation': 'Apporter le carnet de relevés tensionnels des 7 derniers jours et les ordonnances actuelles.',
            'statut_preparation': 'VALIDEE',
            'statut': 'TERMINE',
            'resultat': 'TA 138/88 mmHg. ECG normal. Poursuite traitement actuel recommandée.'
        },
        {
            'titre': 'Radiographie thoracique',
            'type_examen': 'RADIOLOGIE',
            'description': 'Contrôle pulmonaire annuel',
            'date_examen': date.today() - timedelta(days=60),
            'lieu_examen': 'Service Radiologie — Salle RX 2',
            'consignes_preparation': 'Retirer tout objet métallique (chaînette, piercing) avant l\'entrée en salle.',
            'statut_preparation': 'NON_REQUISE',
            'statut': 'TERMINE',
            'resultat': 'Poumons clairs. Pas d\'anomalie détectée.'
        },
        {
            'titre': 'Échographie cardiaque (Echocardiographie)',
            'type_examen': 'ECHOGRAPHIE',
            'description': 'Évaluation fonction cardiaque et cinétique ventriculaire',
            'date_examen': date.today() + timedelta(days=14),
            'lieu_examen': 'Service d\'Imagerie Cardiovasculaire — Hôpital Saint-Luc',
            'consignes_preparation': '• Tenue confortable en deux pièces.\n• Ne pas appliquer de crème ou huile corporelle sur le thorax le jour de l\'examen.\n• Apporter les résultats de la dernière prise de sang et le précédent électrocardiogramme.',
            'statut_preparation': 'A_FAIRE',
            'statut': 'PLANIFIE',
            'resultat': ''
        },
        {
            'titre': 'Échographie abdomino-pelvienne',
            'type_examen': 'ECHOGRAPHIE',
            'description': 'Exploration foie, vésicule et reins',
            'date_examen': date.today() + timedelta(days=5),
            'lieu_examen': 'Centre d\'Échographie Pasteur — Salle 3',
            'consignes_preparation': '• Être à jeun strict au moins 6 heures avant l\'examen (pas d\'aliments solides ni liquides sucrés ou café).\n• Boire 1 litre d\'eau plate 1 heure avant l\'examen et ne pas uriner (nécessité d\'une vessie pleine).',
            'statut_preparation': 'A_FAIRE',
            'statut': 'PLANIFIE',
            'resultat': ''
        },
        {
            'titre': 'Bilan biologique complet pré-anesthésie',
            'type_examen': 'BIOLOGIE',
            'description': 'NFS + bilan lipidique + glycémie à jeun + hémostase',
            'date_examen': date.today(),
            'lieu_examen': 'Laboratoire d\'Analyses Pasteur',
            'consignes_preparation': '• Être à jeun strict depuis la veille à minuit (12 heures de jeûne).\n• Eau plate autorisée en petite quantité.',
            'statut_preparation': 'VALIDEE',
            'statut': 'EN_COURS',
            'resultat': ''
        },
    ]

    for e_data in examens_data:
        ex, created = ExamenMedical.objects.get_or_create(
            dossier=dossier,
            titre=e_data['titre'],
            defaults={**e_data, 'medecin': docteur}
        )
        if not created:
            for k, v in e_data.items():
                setattr(ex, k, v)
            ex.save()
    print(f"  ✓ {len(examens_data)} examens créés/mis à jour avec préparation")

    # Résultats laboratoire
    resultats_data = [
        {
            'type_analyse': 'NFS — Numération Formule Sanguine',
            'priorite': 'NORMALE',
            'statut': 'DISPONIBLE',
            'date_prescription': date.today() - timedelta(days=15),
            'date_realisation': date.today() - timedelta(days=12),
            'valeurs': 'Hémoglobine: 14.2 g/dL (N), Leucocytes: 7200/mm³ (N), Plaquettes: 245000/mm³ (N)',
            'interpretation': 'NFS dans les limites de la normale. Pas d\'anémie ni syndrome inflammatoire.'
        },
        {
            'type_analyse': 'Bilan Lipidique — Cholestérol total + LDL + HDL + Triglycérides',
            'priorite': 'HAUTE',
            'statut': 'TRANSMIS',
            'date_prescription': date.today() - timedelta(days=15),
            'date_realisation': date.today() - timedelta(days=12),
            'valeurs': 'Cholestérol total: 2.18 g/L (élevé), LDL: 1.45 g/L (élevé), HDL: 0.52 g/L (N), TG: 1.78 g/L (élevé)',
            'interpretation': 'Dyslipidémie confirmée. Adaptation thérapeutique recommandée.'
        },
        {
            'type_analyse': 'Glycémie à jeun + HbA1c',
            'priorite': 'NORMALE',
            'statut': 'EN_ATTENTE',
            'date_prescription': date.today(),
            'valeurs': '',
            'interpretation': ''
        },
    ]

    for r_data in resultats_data:
        r, created = ResultatLaboratoire.objects.get_or_create(
            dossier=dossier,
            type_analyse=r_data['type_analyse'],
            defaults={**r_data, 'medecin_prescripteur': docteur, 'laboratoire': labo}
        )
    print(f"  ✓ {len(resultats_data)} résultats laboratoire créés")

    # Prescriptions
    prescriptions_data = [
        {
            'medicament': 'Amlodipine 5mg (Amlor)',
            'posologie': '1 comprimé par jour, le matin',
            'instructions': 'Ne pas interrompre sans avis médical. Surveiller la tension.',
            'date_prescription': date.today() - timedelta(days=30),
            'date_fin': date.today() + timedelta(days=60),
            'statut': 'ACTIVE'
        },
        {
            'medicament': 'Atorvastatine 20mg',
            'posologie': '1 comprimé le soir au coucher',
            'instructions': 'Contrôle bilan hépatique dans 3 mois. Signaler toute douleur musculaire.',
            'date_prescription': date.today() - timedelta(days=5),
            'date_fin': None,
            'statut': 'ACTIVE'
        },
        {
            'medicament': 'Paracétamol 1g',
            'posologie': '1 à 3 comprimés par jour, max 4g/24h',
            'instructions': 'En cas de douleurs ou fièvre uniquement.',
            'date_prescription': date.today() - timedelta(days=60),
            'date_fin': date.today() - timedelta(days=30),
            'statut': 'TERMINEE'
        },
    ]

    for p_data in prescriptions_data:
        Prescription.objects.get_or_create(
            dossier=dossier,
            medicament=p_data['medicament'],
            defaults={**p_data, 'medecin': docteur}
        )
    print(f"  ✓ {len(prescriptions_data)} prescriptions créées")

    # Observations médicales
    observations_data = [
        {
            'titre': 'Consultation initiale — Suivi HTA',
            'contenu': 'Patient hypertendu sous traitement depuis 4 ans. TA stable à 138/88 mmHg. Pas de symptômes d\'HTA sévère. Observance médicamenteuse satisfaisante. Poids : 82 kg, IMC : 26.4.',
            'date_observation': date.today() - timedelta(days=30),
            'confidentiel': False
        },
        {
            'titre': 'Résultats bilan lipidique — Action requise',
            'contenu': 'Dyslipidémie confirmée. Introduction statine (Atorvastatine 20mg) justifiée. Régime hypolipémiant conseillé. Contrôle à 3 mois avec bilan hépatique.',
            'date_observation': date.today() - timedelta(days=5),
            'confidentiel': False
        },
        {
            'titre': 'Note confidentielle — Évaluation psychologique',
            'contenu': 'Patient présente un stress professionnel élevé. Conseillé suivi psychologique et activité physique régulière.',
            'date_observation': date.today() - timedelta(days=10),
            'confidentiel': True
        },
    ]

    for o_data in observations_data:
        ObservationMedicale.objects.get_or_create(
            dossier=dossier,
            titre=o_data['titre'],
            defaults={**o_data, 'medecin': docteur}
        )
    print(f"  ✓ {len(observations_data)} observations créées")

    print("\n✅ Données de démonstration créées avec succès !")
    print(f"   → Connectez-vous avec : patient_martin / patient123")
    print(f"   → Ou avec : dr_moreau / docteur123")

if __name__ == '__main__':
    seed()
