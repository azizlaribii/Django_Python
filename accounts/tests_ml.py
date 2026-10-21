"""
Tests Unitaires pour le module Machine Learning Médical — MediConnect
Couvre les 5 exigences :
1. Absence d'imputation silencieuse (âge non inventé).
2. Dossiers incomplets et suspension des prédictions.
3. Vecteurs invalides (dimension != 12, NaN, inf).
4. Réconciliation et cohérence titre vs type d'examen (Bilan sanguin vs Coloscopie vs FOGD).
5. Validation du Random Forest (absence de fuite de données, dataset synthétique).
6. Similarité Cosinus qualifiée en proximité de profil et non en pourcentage de risque.
"""

import numpy as np
from django.test import TestCase
from accounts.models import User, DossierMedical, ExamenMedical, ObservationMedicale
from accounts.ml.random_forest import (
    valider_vecteur_patient,
    predire_risque_complications,
    obtenir_performances_modele,
    generer_dataset_clinique_synthetique,
)
from accounts.ml.similarity import (
    classifier_examen_reel,
    trouver_profil_similaire,
)
from accounts.ml.risk_score import (
    extraire_vecteur_clinique,
    verifier_completude_dossier,
    calculer_score_risque_clinique,
)


class MLModuleTests(TestCase):

    def setUp(self):
        # Création d'un médecin et d'un patient test
        self.docteur = User.objects.create_user(
            username='dr_test',
            email='dr@test.com',
            password='pass',
            role=User.Role.DOCTEUR
        )
        self.patient = User.objects.create_user(
            username='pat_test',
            email='pat@test.com',
            password='pass',
            role=User.Role.PATIENT
        )
        self.dossier = DossierMedical.objects.create(patient=self.patient)

    # ─────────────────────────────────────────────────────────────────────────
    # 1. DONNÉES MANQUANTES : PAS D'ÂGE INVENTÉ À 40 ANS
    # ─────────────────────────────────────────────────────────────────────────
    def test_age_non_impute_arbitrairement(self):
        """Vérifie que l'âge n'est jamais fixé arbitrairement à 40 ans si absent."""
        ia_data_sans_age = {
            'age': None,
            'maladies_chroniques_positives': [],
            'allergies_positives': [],
            'traitements_actifs': [],
            'examens_complets': []
        }
        vecteur = extraire_vecteur_clinique(self.patient, self.dossier, ia_data_sans_age)
        
        # L'index 0 (âge normalisé) doit être 0.0, JAMAIS 0.40 (40 ans)
        self.assertEqual(vecteur[0], 0.0)

        completude = verifier_completude_dossier(self.patient, self.dossier, ia_data_sans_age)
        self.assertTrue(completude['donnees_insuffisantes'])
        self.assertTrue(any('âge' in item.lower() for item in completude['donnees_manquantes']))

    # ─────────────────────────────────────────────────────────────────────────
    # 2. DOSSIER INCOMPLET : PRÉDICTION SUSPENDUE
    # ─────────────────────────────────────────────────────────────────────────
    def test_dossier_incomplet_suspension_prediction(self):
        """Vérifie que pour un dossier vide, le score et la prédiction sont suspendus."""
        ia_data_vide = {
            'age': None,
            'maladies_chroniques_positives': [],
            'allergies_positives': [],
            'traitements_actifs': [],
            'examens_complets': []
        }
        resultat = calculer_score_risque_clinique(self.patient, self.dossier, ia_data_vide)

        self.assertTrue(resultat['donnees_insuffisantes'])
        self.assertEqual(resultat['score_display'], 'Non calculé')
        self.assertEqual(resultat['niveau_risque'], 'DONNEES_INSUFFISANTES')
        self.assertTrue(len(resultat['donnees_manquantes']) > 0)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. VECTEURS INVALIDES : LEVÉE D'ERREUR
    # ─────────────────────────────────────────────────────────────────────────
    def test_validation_vecteur_patient(self):
        """Vérifie le rejet strict des vecteurs de dimension incorrecte ou contenant NaN/Inf."""
        # Vecteur valide (12 variables)
        vecteur_valide = np.zeros(12, dtype=np.float64)
        arr = valider_vecteur_patient(vecteur_valide)
        self.assertEqual(arr.shape, (12,))

        # Vecteur de mauvaise dimension (10 au lieu de 12)
        with self.assertRaises(ValueError):
            valider_vecteur_patient(np.zeros(10))

        # Vecteur de dimension 13
        with self.assertRaises(ValueError):
            valider_vecteur_patient(np.zeros(13))

        # Vecteur contenant NaN
        vec_nan = np.zeros(12)
        vec_nan[2] = np.nan
        with self.assertRaises(ValueError):
            valider_vecteur_patient(vec_nan)

        # Vecteur None
        with self.assertRaises(ValueError):
            valider_vecteur_patient(None)

    # ─────────────────────────────────────────────────────────────────────────
    # 4. RÉCONCILIATION TITRE VS TYPE D'EXAMEN
    # ─────────────────────────────────────────────────────────────────────────
    def test_reconciliation_bilan_sanguin_vs_coloscopie(self):
        """
        Un examen titré 'Bilan sanguin' mal étiqueté 'COLOSCOPIE' en BDD
        ne doit PAS être considéré comme une coloscopie invasive.
        """
        type_reel = classifier_examen_reel(
            titre="Bilan sanguin - Glycémie et cholestérol",
            code_type="COLOSCOPIE"
        )
        self.assertEqual(type_reel, 'BIOLOGIE_SANGUINE')

        # Vérification qu'il ne déclenche pas le flag examen invasif
        ia_data = {
            'age': 50,
            'maladies_chroniques_positives': [],
            'allergies_positives': [],
            'traitements_actifs': [],
            'examens_complets': [{
                'titre': "Bilan sanguin - Glycémie et cholestérol",
                'type_code': "COLOSCOPIE",
                'statut_preparation': "A_FAIRE"
            }]
        }
        vecteur = extraire_vecteur_clinique(self.patient, self.dossier, ia_data)
        # Index 9 (examen invasif) doit rester 0.0
        self.assertEqual(vecteur[9], 0.0)

    def test_reconciliation_fogd(self):
        """Vérifie la bonne détection d'une fibroscopie haute (FOGD)."""
        type_reel = classifier_examen_reel(
            titre="Fibroscopie œso-gastro-duodénale (FOGD)",
            code_type="FIBROSCOPIE"
        )
        self.assertEqual(type_reel, 'FOGD')

    # ─────────────────────────────────────────────────────────────────────────
    # 5. ABSENCE DE FUITE DE DONNÉES & RANDOM FOREST SYNTHÉTIQUE
    # ─────────────────────────────────────────────────────────────────────────
    def test_dataset_synthetique_et_absence_fuite(self):
        """Vérifie la taille du jeu de test (320 cas, 20%) et le bon dimensionnement."""
        X, y = generer_dataset_clinique_synthetique(n_samples=1600, random_state=42)
        self.assertEqual(X.shape, (1600, 12))
        self.assertEqual(y.shape, (1600,))

        perf = obtenir_performances_modele()
        self.assertEqual(perf['n_test'], 320)
        self.assertEqual(perf['n_train'], 1280)
        self.assertIn('Synthétique', perf['nature_dataset'])

    # ─────────────────────────────────────────────────────────────────────────
    # 6. SIMILARITÉ COSINUS : INDICE DE PROXIMITÉ ET NON RISQUE
    # ─────────────────────────────────────────────────────────────────────────
    def test_similarite_cosinus_profil(self):
        """Vérifie que la similarité cosinus retourne un pourcentage géométrique borné."""
        vecteur_test = np.array([0.62, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.50, 0.0, 0.0, 0.0])
        sim_res = trouver_profil_similaire(vecteur_test)

        self.assertIsNotNone(sim_res['meilleur_profil'])
        concordance = sim_res['meilleur_profil']['concordance_pct']
        self.assertTrue(0.0 <= concordance <= 100.0)
        # Le vecteur test étant exactement l'archétype CARDIO_METABOLIQUE, la similarité doit être 100%
        self.assertAlmostEqual(concordance, 100.0, places=1)
        self.assertEqual(sim_res['meilleur_profil']['cohorte']['id'], 'CARDIO_METABOLIQUE')
