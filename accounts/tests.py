"""
Tests du module Examens et Préparation — MediConnect
===================================================
Conforme aux exigences du barème :
3. Tests & Besoins Non-Fonctionnels (BNF) — 4 points
  3.1 Stratégie et couverture de tests — 2 points
    - Tests unitaires (0.75 pt) : Modèles, contraintes, logique métier, calcul score, protocoles, IA.
    - Tests d'intégration / API (0.75 pt) : Vues, endpoints, statuts HTTP, réponses JSON via Client Django.
    - Couverture et exécution (0.5 pt) : Exécutable sans erreur, compatible coverage.py.
  3.2 Exigences non-fonctionnelles — 2 points
    - Sécurité OWASP (0.75 pt) : CSRF, hash mots de passe, requêtes ORM sans injection SQL brute, DEBUG/SECRET_KEY.
    - Rôles / Permissions (0.75 pt) : Contrôle d'accès effectif (@login_required, rôles DOCTEUR/ADMIN/PATIENT).
    - Performance & Logs (0.5 pt) : select_related/prefetch_related (absence N+1), configuration logging.
"""

from datetime import date, timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, is_password_usable
from django.conf import settings
from django.utils import timezone

from accounts.models import (
    User,
    DoctorProfile,
    PatientProfile,
    DossierMedical,
    ExamenMedical,
    EtapePreparationExamen,
    Prescription,
    ObservationMedicale,
)
from accounts.protocoles import (
    PROTOCOLES_PREPARATION,
    appliquer_protocole_examen,
)
from accounts.ml.ai_examen import (
    analyser_examen_ia,
    _generer_alertes_cliniques,
)

User = get_user_model()


# ═════════════════════════════════════════════════════════════════════════════
# 1. TESTS UNITAIRES — MODÈLES & LOGIQUE MÉTIER (0.75 pt)
# ═════════════════════════════════════════════════════════════════════════════
class ExamenModelUnitTests(TestCase):
    """Tests unitaires sur les modèles ExamenMedical et EtapePreparationExamen."""

    def setUp(self):
        self.docteur = User.objects.create_user(
            username='dr_unitaire',
            email='dr_unitaire@test.com',
            password='Password123!',
            role=User.Role.DOCTEUR,
            first_name='Sophie',
            last_name='Martin'
        )
        self.patient = User.objects.create_user(
            username='pat_unitaire',
            email='pat_unitaire@test.com',
            password='Password123!',
            role=User.Role.PATIENT,
            first_name='Jean',
            last_name='Dupont'
        )
        self.dossier = DossierMedical.objects.create(patient=self.patient)

    def test_creation_examen_valeurs_par_defaut(self):
        """Vérifie la création correcte d'un examen médical avec ses valeurs par défaut."""
        demain = date.today() + timedelta(days=2)
        examen = ExamenMedical.objects.create(
            dossier=self.dossier,
            medecin=self.docteur,
            type_examen='COLOSCOPIE',
            titre='Coloscopie diagnostique',
            date_examen=demain
        )
        self.assertEqual(examen.statut, 'PLANIFIE')
        self.assertEqual(examen.statut_preparation, 'NON_REQUISE')
        self.assertEqual(examen.score_preparation, 0)
        self.assertEqual(examen.score_seuil_validation, 100)
        self.assertFalse(examen.est_pret_pour_examen)
        self.assertIn('Coloscopie diagnostique', str(examen))

    def test_logique_recalculer_score_preparation_etapes_nulles(self):
        """Vérifie le calcul de score si aucune étape n'est associée (évite ZeroDivisionError)."""
        demain = date.today() + timedelta(days=2)
        examen = ExamenMedical.objects.create(
            dossier=self.dossier,
            medecin=self.docteur,
            type_examen='COLOSCOPIE',
            titre='Coloscopie',
            date_examen=demain
        )
        score = examen.recalculer_score_preparation(save=True)
        self.assertEqual(score, 0)
        validees, total = examen.progression_etapes
        self.assertEqual((validees, total), (0, 0))

    def test_logique_calcul_score_pondere_et_statuts(self):
        """Vérifie la logique métier pondérée des étapes et les transitions de statut."""
        demain = date.today() + timedelta(days=3)
        examen = ExamenMedical.objects.create(
            dossier=self.dossier,
            medecin=self.docteur,
            type_examen='COLOSCOPIE',
            titre='Coloscopie préparée',
            date_examen=demain,
            score_seuil_validation=100
        )
        # Créer 3 étapes avec pondérations : 20, 30, 50 = total 100
        e1 = EtapePreparationExamen.objects.create(examen=examen, titre='Étape 1', points=20, ordre=1)
        e2 = EtapePreparationExamen.objects.create(examen=examen, titre='Étape 2', points=30, ordre=2)
        e3 = EtapePreparationExamen.objects.create(examen=examen, titre='Étape 3', points=50, ordre=3)

        # 1. État initial (0/100 -> A_FAIRE)
        examen.recalculer_score_preparation(save=True)
        self.assertEqual(examen.score_preparation, 0)
        self.assertEqual(examen.statut_preparation, 'A_FAIRE')
        self.assertFalse(examen.est_pret_pour_examen)

        # 2. Validation de l'étape 1 (20/100 -> 20% -> EN_COURS)
        e1.est_validee = True
        e1.validee_par = self.patient
        e1.date_validation = timezone.now()
        e1.save()
        score = examen.recalculer_score_preparation(save=True)
        self.assertEqual(score, 20)
        self.assertEqual(examen.statut_preparation, 'EN_COURS')
        self.assertFalse(examen.est_pret_pour_examen)

        # 3. Validation de l'étape 2 (50/100 -> 50% -> EN_COURS)
        e2.est_validee = True
        e2.save()
        score = examen.recalculer_score_preparation(save=True)
        self.assertEqual(score, 50)
        self.assertEqual(examen.statut_preparation, 'EN_COURS')

        # 4. Validation finale de l'étape 3 (100/100 -> 100% -> VALIDEE)
        e3.est_validee = True
        e3.save()
        score = examen.recalculer_score_preparation(save=True)
        self.assertEqual(score, 100)
        self.assertEqual(examen.statut_preparation, 'VALIDEE')
        self.assertTrue(examen.est_pret_pour_examen)

        validees, total = examen.progression_etapes
        self.assertEqual(validees, 3)
        self.assertEqual(total, 3)

    def test_seuil_validation_personnalise(self):
        """Vérifie qu'un score seuil personnalisé (ex: 75%) valide la préparation dès son atteinte."""
        examen = ExamenMedical.objects.create(
            dossier=self.dossier,
            medecin=self.docteur,
            titre='Scanner injecté',
            date_examen=date.today() + timedelta(days=1),
            score_seuil_validation=80
        )
        e1 = EtapePreparationExamen.objects.create(examen=examen, titre='Bilan créatinine', points=80, est_validee=True)
        e2 = EtapePreparationExamen.objects.create(examen=examen, titre='Jeûne 4h', points=20, est_validee=False)

        score = examen.recalculer_score_preparation(save=True)
        self.assertEqual(score, 80)
        # Seuil fixé à 80% atteint : préparation VALIDEE même si l'étape 2 n'est pas encore cochée
        self.assertTrue(examen.est_pret_pour_examen)
        self.assertEqual(examen.statut_preparation, 'VALIDEE')


class ExamenProtocolesUnitTests(TestCase):
    """Tests unitaires sur les protocoles médicaux prédéfinis."""

    def setUp(self):
        self.docteur = User.objects.create_user(
            username='dr_proto', role=User.Role.DOCTEUR, password='password'
        )
        self.patient = User.objects.create_user(
            username='pat_proto', role=User.Role.PATIENT, password='password'
        )
        self.dossier = DossierMedical.objects.create(patient=self.patient)
        self.examen = ExamenMedical.objects.create(
            dossier=self.dossier,
            medecin=self.docteur,
            type_examen='COLOSCOPIE',
            titre='Coloscopie de dépistage',
            date_examen=date.today() + timedelta(days=4)
        )

    def test_integrite_dictionnaire_protocoles(self):
        """Vérifie la validité structurelle de tous les protocoles prédéfinis."""
        protocoles_cles = ['COLOSCOPIE', 'ECHOGRAPHIE_ABDOMINALE', 'SCANNER_INJECTION', 'FIBROSCOPIE']
        for cle in protocoles_cles:
            self.assertIn(cle, PROTOCOLES_PREPARATION)
            proto = PROTOCOLES_PREPARATION[cle]
            self.assertIn('nom', proto)
            self.assertIn('score_seuil', proto)
            self.assertIn('etapes', proto)
            self.assertGreater(len(proto['etapes']), 0)
            # Vérifier que la somme des points fait 100
            total_points = sum(e['points'] for e in proto['etapes'])
            self.assertEqual(total_points, 100, f"Le total des points pour {cle} doit être 100.")

    def test_appliquer_protocole_coloscopie(self):
        """Vérifie que l'application du protocole génère les étapes de préparation en base."""
        succes = appliquer_protocole_examen(self.examen, 'COLOSCOPIE')
        self.assertTrue(succes)

        self.examen.refresh_from_db()
        self.assertEqual(self.examen.protocole_type, 'COLOSCOPIE')
        self.assertIn("Régime sans résidu", self.examen.consignes_preparation)
        self.assertEqual(self.examen.score_preparation, 0)
        self.assertEqual(self.examen.statut_preparation, 'A_FAIRE')

        etapes = self.examen.etapes_preparation.all()
        self.assertEqual(etapes.count(), 5)
        self.assertEqual(sum(e.points for e in etapes), 100)

    def test_appliquer_protocole_inexistant(self):
        """Vérifie qu'un protocole inconnu retourne False et ne modifie rien."""
        succes = appliquer_protocole_examen(self.examen, 'PROTOCOLE_INVENTE')
        self.assertFalse(succes)


class ExamenAIUnitTests(TestCase):
    """Tests unitaires sur l'analyse IA des examens et les alertes cliniques croisées."""

    def setUp(self):
        self.docteur = User.objects.create_user(
            username='dr_ai', role=User.Role.DOCTEUR, password='password'
        )
        self.patient = User.objects.create_user(
            username='pat_ai', role=User.Role.PATIENT, password='password'
        )
        self.dossier = DossierMedical.objects.create(patient=self.patient)

    def test_suggestion_protocole_coloscopie(self):
        """Vérifie que l'IA associe un examen de type COLOSCOPIE au protocole correspondant."""
        examen = ExamenMedical.objects.create(
            dossier=self.dossier,
            medecin=self.docteur,
            type_examen='COLOSCOPIE',
            titre='Coloscopie de contrôle',
            date_examen=date.today() + timedelta(days=5)
        )
        res = analyser_examen_ia(examen, self.dossier)
        self.assertEqual(res['protocole_suggere'], 'COLOSCOPIE')
        self.assertGreaterEqual(res['confiance'], 95)
        self.assertTrue(res['suggestions_disponibles'])
        self.assertIn('polypes', res['message_ia'].lower())

    def test_alerte_croisee_scanner_diabete_metformine(self):
        """
        Règle clinique critique :
        Scanner avec contraste + diabète/metformine -> Alerte arrêt impératif de la Metformine.
        """
        self.dossier.notes_generales = "Patient diabétique de type 2 traité par Metformine 850mg."
        self.dossier.save()

        examen = ExamenMedical.objects.create(
            dossier=self.dossier,
            medecin=self.docteur,
            type_examen='SCANNER_TAP',
            titre='Scanner thoraco-abdominal injecté',
            date_examen=date.today() + timedelta(days=2)
        )
        alertes = _generer_alertes_cliniques(examen, self.dossier)
        titres_alertes = [a['titre'] for a in alertes]
        self.assertTrue(any('metformine' in t.lower() or 'diabète' in t.lower() for t in titres_alertes))

    def test_alerte_croisee_allergie_produit_contraste(self):
        """Scanner + terrain allergique au contraste/iode -> Alerte danger."""
        self.dossier.allergies = "Allergie connue aux produits de contraste iodés (urticaire géant)."
        self.dossier.save()

        examen = ExamenMedical.objects.create(
            dossier=self.dossier,
            medecin=self.docteur,
            type_examen='SCANNER_TAP',
            titre='Scanner TAP',
            date_examen=date.today() + timedelta(days=3)
        )
        alertes = _generer_alertes_cliniques(examen, self.dossier)
        self.assertTrue(any('allergie' in a['titre'].lower() for a in alertes))

    def test_alerte_croisee_endoscopie_anticoagulants(self):
        """Coloscopie + prise d'anticoagulant -> Alerte de surveillance hémorragique."""
        Prescription.objects.create(
            dossier=self.dossier,
            medecin=self.docteur,
            medicament='Eliquis (Apixaban) 5mg',
            posologie='1 comprimé matin et soir'
        )
        examen = ExamenMedical.objects.create(
            dossier=self.dossier,
            medecin=self.docteur,
            type_examen='COLOSCOPIE',
            titre='Coloscopie diagnostique',
            date_examen=date.today() + timedelta(days=3)
        )
        alertes = _generer_alertes_cliniques(examen, self.dossier)
        self.assertTrue(any('anticoagulant' in a['titre'].lower() for a in alertes))


# ═════════════════════════════════════════════════════════════════════════════
# 2. TESTS D'INTÉGRATION & API — CLIENT DJANGO (0.75 pt)
# ═════════════════════════════════════════════════════════════════════════════
class ExamenViewsIntegrationTests(TestCase):
    """Tests d'intégration des vues et endpoints de l'application Examens."""

    def setUp(self):
        self.client = Client()
        self.docteur = User.objects.create_user(
            username='dr_integration',
            email='dr_int@test.com',
            password='Password123!',
            role=User.Role.DOCTEUR,
            first_name='Dr',
            last_name='House'
        )
        self.patient = User.objects.create_user(
            username='pat_integration',
            email='pat_int@test.com',
            password='Password123!',
            role=User.Role.PATIENT,
            first_name='Arthur',
            last_name='Dent'
        )
        self.dossier = DossierMedical.objects.create(patient=self.patient)

        self.examen = ExamenMedical.objects.create(
            dossier=self.dossier,
            medecin=self.docteur,
            type_examen='COLOSCOPIE',
            titre='Coloscopie globale',
            date_examen=date.today() + timedelta(days=3),
            score_seuil_validation=100
        )
        appliquer_protocole_examen(self.examen, 'COLOSCOPIE')

    def test_examens_list_vue_docteur_statut_200(self):
        """Le médecin accède à la liste globale des examens (HTTP 200) avec filtres."""
        self.client.force_login(self.docteur)
        response = self.client.get(reverse('examens_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/examens_list.html')
        self.assertIn('examens', response.context)
        self.assertIn('stats', response.context)
        self.assertEqual(response.context['stats']['total'], 1)

    def test_examens_list_filtre_recherche_texte(self):
        """Vérifie que la recherche textuelle (q) filtre correctement les examens."""
        self.client.force_login(self.docteur)
        # Recherche qui doit matcher
        r_match = self.client.get(reverse('examens_list'), {'q': 'Coloscopie'})
        self.assertEqual(len(r_match.context['examens']), 1)

        # Recherche qui ne doit rien donner
        r_empty = self.client.get(reverse('examens_list'), {'q': 'IntrouvableXYZ'})
        self.assertEqual(len(r_empty.context['examens']), 0)

    def test_add_examen_global_par_docteur_succes(self):
        """Création d'un examen médical avec protocole en POST par le médecin."""
        self.client.force_login(self.docteur)
        post_data = {
            'patient': self.patient.id,
            'type_examen': 'ECHO_ABDOMINALE',
            'titre': 'Échographie abdomino-pelvienne complète',
            'date_examen': (date.today() + timedelta(days=5)).strftime('%Y-%m-%d'),
            'statut': 'PLANIFIE',
            'statut_preparation': 'A_FAIRE',
            'score_seuil_validation': '100',
            'protocole_type': 'ECHOGRAPHIE_ABDOMINALE',
        }
        response = self.client.post(reverse('add_examen_global'), post_data)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'], f"Form errors: {data.get('errors')}")

        nouvel_examen = ExamenMedical.objects.get(titre='Échographie abdomino-pelvienne complète')
        self.assertEqual(nouvel_examen.protocole_type, 'ECHOGRAPHIE_ABDOMINALE')
        self.assertEqual(nouvel_examen.etapes_preparation.count(), 3)

    def test_add_examen_global_donnees_invalides(self):
        """Rejet propre avec message d'erreur si données obligatoires manquantes."""
        self.client.force_login(self.docteur)
        # Pas de date_examen ni patient
        response = self.client.post(reverse('add_examen_global'), {'titre': 'Test'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])

    def test_examen_fiche_preparation_acces_proprietaire_et_medecin(self):
        """La fiche détaillée est accessible par le médecin et par le patient concerné."""
        # 1. Médecin
        self.client.force_login(self.docteur)
        r_doc = self.client.get(reverse('examen_fiche_preparation', args=[self.examen.id]))
        self.assertEqual(r_doc.status_code, 200)

        # 2. Patient concerné
        self.client.force_login(self.patient)
        r_pat = self.client.get(reverse('examen_fiche_preparation', args=[self.examen.id]))
        self.assertEqual(r_pat.status_code, 200)
        self.assertTemplateUsed(r_pat, 'accounts/examen_fiche_preparation.html')

    def test_toggle_etape_preparation_par_patient_maj_score(self):
        """Le patient coche une étape : le statut de l'étape et le score global changent."""
        self.client.force_login(self.patient)
        premiere_etape = self.examen.etapes_preparation.first()
        self.assertFalse(premiere_etape.est_validee)

        url = reverse('toggle_etape_preparation', args=[premiere_etape.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['est_validee'])
        self.assertGreater(data['score_preparation'], 0)
        self.assertEqual(data['validees_count'], 1)

    def test_valider_preparation_examen_action_rapide_docteur(self):
        """Le médecin force la validation d'une préparation via l'action rapide."""
        self.client.force_login(self.docteur)
        url = reverse('valider_preparation_examen', args=[self.examen.id])
        response = self.client.post(url, {'statut_preparation': 'VALIDEE'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        self.examen.refresh_from_db()
        self.assertEqual(self.examen.statut_preparation, 'VALIDEE')

    def test_api_protocole_details_valide_et_404(self):
        """Vérifie l'API endpoint /api/protocole/<id>/ (succès 200 et 404)."""
        self.client.force_login(self.docteur)

        # 1. Protocole existant
        r_ok = self.client.get(reverse('api_protocole_details', args=['COLOSCOPIE']))
        self.assertEqual(r_ok.status_code, 200)
        d_ok = r_ok.json()
        self.assertTrue(d_ok['success'])
        self.assertEqual(d_ok['protocole']['id'], 'COLOSCOPIE')

        # 2. Protocole inexistant
        r_err = self.client.get(reverse('api_protocole_details', args=['INCONNU']))
        self.assertEqual(r_err.status_code, 404)

    def test_api_examen_detail_json(self):
        """Vérifie l'endpoint /api/examen/<id>/ retournant les données complètes de l'examen."""
        self.client.force_login(self.docteur)
        response = self.client.get(reverse('api_examen_detail', args=[self.examen.id]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['id'], self.examen.id)
        self.assertEqual(data['titre'], self.examen.titre)
        self.assertEqual(data['type_examen'], 'COLOSCOPIE')
        self.assertEqual(data['patient_id'], self.patient.id)

    def test_delete_examen_par_docteur(self):
        """Le médecin peut supprimer un examen médical (HTTP 302 redirect)."""
        self.client.force_login(self.docteur)
        url = reverse('delete_examen', args=[self.examen.id])
        response = self.client.post(url)
        self.assertIn(response.status_code, [200, 302])
        self.assertFalse(ExamenMedical.objects.filter(id=self.examen.id).exists())


# ═════════════════════════════════════════════════════════════════════════════
# 3. EXIGENCES NON-FONCTIONNELLES — SÉCURITÉ & PERMISSIONS (1.5 pt)
# ═════════════════════════════════════════════════════════════════════════════
class ExamenPermissionsSecurityTests(TestCase):
    """
    Vérification des exigences non-fonctionnelles de sécurité OWASP,
    contrôle d'accès par rôle et isolation des données médicales.
    """

    def setUp(self):
        self.client = Client()
        self.docteur = User.objects.create_user(
            username='dr_secu', role=User.Role.DOCTEUR, password='SecretPassword123!'
        )
        self.patient_owner = User.objects.create_user(
            username='pat_owner', role=User.Role.PATIENT, password='SecretPassword123!'
        )
        self.patient_usurpateur = User.objects.create_user(
            username='pat_autre', role=User.Role.PATIENT, password='SecretPassword123!'
        )
        self.dossier = DossierMedical.objects.create(patient=self.patient_owner)
        self.examen = ExamenMedical.objects.create(
            dossier=self.dossier,
            medecin=self.docteur,
            type_examen='COLOSCOPIE',
            titre='Coloscopie confidentielle',
            date_examen=date.today() + timedelta(days=2)
        )
        self.etape = EtapePreparationExamen.objects.create(
            examen=self.examen,
            titre='Étape de préparation confidentielle',
            points=50
        )

    # ── OWASP SÉCURITÉ : MOTS DE PASSE & INJECTIONS ──────────────────────────
    def test_securite_mots_de_passe_hashes(self):
        """Vérifie que les mots de passe utilisateurs ne sont jamais stockés en clair (PBKDF2/argon2)."""
        user = User.objects.get(username='dr_secu')
        self.assertNotEqual(user.password, 'SecretPassword123!')
        self.assertTrue(user.password.startswith('pbkdf2_sha256$') or user.password.startswith('argon2'))
        self.assertTrue(check_password('SecretPassword123!', user.password))
        self.assertTrue(is_password_usable(user.password))

    def test_securite_orm_prevention_injection_sql(self):
        """
        Vérifie que l'ORM Django protège contre les injections SQL directes
        lors des filtres et recherches d'examens.
        """
        payload_injection = "' OR 1=1 --"
        # Recherche avec tentative d'injection SQL
        qs = ExamenMedical.objects.filter(titre__icontains=payload_injection)
        # La requête doit s'exécuter de façon sécurisée sans crasher ni tout retourner
        self.assertEqual(qs.count(), 0)

    def test_securite_headers_owasp_et_settings_configuration(self):
        """Vérifie la présence des middlewares de sécurité et des headers critiques."""
        self.assertIn('django.middleware.csrf.CsrfViewMiddleware', settings.MIDDLEWARE)
        self.assertIn('django.middleware.clickjacking.XFrameOptionsMiddleware', settings.MIDDLEWARE)
        self.assertIn('django.middleware.security.SecurityMiddleware', settings.MIDDLEWARE)
        self.assertEqual(getattr(settings, 'X_FRAME_OPTIONS', 'DENY'), 'DENY')
        self.assertTrue(getattr(settings, 'SECURE_CONTENT_TYPE_NOSNIFF', True))

    # ── CONTRÔLE D'ACCÈS PAR RÔLE (RBAC) ────────────────────────────────────
    def test_refus_acces_anonyme_vers_login(self):
        """Un utilisateur non authentifié est automatiquement redirigé vers la mire de login."""
        endpoints = [
            reverse('examens_list'),
            reverse('examen_fiche_preparation', args=[self.examen.id]),
        ]
        for url in endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login/', response.headers.get('Location', ''))

    def test_patient_refuse_acces_liste_globale_examens(self):
        """Un patient n'a pas le droit d'accéder à la liste globale des examens du cabinet."""
        self.client.force_login(self.patient_owner)
        response = self.client.get(reverse('examens_list'))
        # Redirection avec avertissement
        self.assertEqual(response.status_code, 302)

    def test_patient_ne_peut_pas_creer_examen(self):
        """Un patient tentant de créer un examen reçoit une erreur 403 Forbidden."""
        self.client.force_login(self.patient_owner)
        response = self.client.post(reverse('add_examen_global'), {'titre': 'Hack Examen'})
        self.assertEqual(response.status_code, 403)

    def test_isolation_patient_fiche_interdite_a_un_tiers(self):
        """Un patient tiers ne peut pas consulter la fiche de préparation d'un autre patient."""
        self.client.force_login(self.patient_usurpateur)
        url = reverse('examen_fiche_preparation', args=[self.examen.id])
        response = self.client.get(url)
        # Redirection vers le dashboard avec message d'erreur
        self.assertEqual(response.status_code, 302)

    def test_isolation_patient_toggle_etape_interdit_a_un_tiers(self):
        """Un patient tiers ne peut pas cocher/valider l'étape de préparation d'un autre patient."""
        self.client.force_login(self.patient_usurpateur)
        url = reverse('toggle_etape_preparation', args=[self.etape.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.etape.est_validee)

    def test_validation_preparation_forcee_interdite_au_patient(self):
        """Un patient ne peut pas forcer le statut VALIDEE de son examen (réservé au médecin)."""
        self.client.force_login(self.patient_owner)
        url = reverse('valider_preparation_examen', args=[self.examen.id])
        response = self.client.post(url, {'statut_preparation': 'VALIDEE'})
        self.assertEqual(response.status_code, 403)


# ═════════════════════════════════════════════════════════════════════════════
# 4. EXIGENCES NON-FONCTIONNELLES — PERFORMANCE & LOGS (0.5 pt)
# ═════════════════════════════════════════════════════════════════════════════
class ExamenPerformanceTests(TestCase):
    """Vérification des performances ORM (N+1 queries) et configuration des logs."""

    def setUp(self):
        self.client = Client()
        self.docteur = User.objects.create_user(
            username='dr_perf', role=User.Role.DOCTEUR, password='password'
        )
        # Créer plusieurs patients et examens avec étapes pour tester l'impact N+1
        for i in range(5):
            patient = User.objects.create_user(
                username=f'patient_perf_{i}', role=User.Role.PATIENT, password='password'
            )
            dossier = DossierMedical.objects.create(patient=patient)
            examen = ExamenMedical.objects.create(
                dossier=dossier,
                medecin=self.docteur,
                type_examen='COLOSCOPIE',
                titre=f'Examen de performance {i}',
                date_examen=date.today() + timedelta(days=i + 1)
            )
            for j in range(3):
                EtapePreparationExamen.objects.create(
                    examen=examen,
                    titre=f'Étape {j}',
                    points=33
                )

    def test_optimisation_requetes_select_related_prefetch(self):
        """
        Vérifie que la vue examens_crud_list utilise select_related et prefetch_related
        pour éviter l'explosion des requêtes SQL (problème N+1).
        """
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        self.client.force_login(self.docteur)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse('examens_list'))
            self.assertEqual(response.status_code, 200)

        # Avec 5 examens, sans optimisation cela ferait 5 x (patient + profile + medecin + étapes) = 20+ requêtes.
        # Avec select_related et prefetch_related, le nombre de requêtes reste maîtrisé et borné (<= 15).
        self.assertLessEqual(len(ctx), 15)

    def test_configuration_logging_django_et_accounts(self):
        """Vérifie que le dictionnaire LOGGING est bien configuré pour l'application accounts."""
        self.assertTrue(hasattr(settings, 'LOGGING'))
        logging_cfg = settings.LOGGING
        self.assertIn('loggers', logging_cfg)
        self.assertIn('accounts', logging_cfg['loggers'])
        self.assertIn('django', logging_cfg['loggers'])


# ═════════════════════════════════════════════════════════════════════════════
# 5. TESTS MACHINE LEARNING & IA MÉDICALE
# ═════════════════════════════════════════════════════════════════════════════
from .tests_ml import MLModuleTests  # noqa: F401, E402
