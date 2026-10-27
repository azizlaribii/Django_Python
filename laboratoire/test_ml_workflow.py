from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .ml.predict import check_value
from .models import (
    AnalyseDemandee,
    DemandeAnalyse,
    Prelevement,
    Resultat,
    TypeAnalyse,
)
from .services import changer_statut, creer_prelevements


class AnomalyModelTests(TestCase):
    def test_normal_value_is_not_flagged(self):
        self.assertFalse(check_value("Hémoglobine", 14.2))

    def test_typographical_outlier_is_flagged(self):
        self.assertTrue(check_value("hemoglobine", 150))

    def test_unknown_analysis_is_not_flagged(self):
        self.assertFalse(check_value("analyse inconnue", 150))


class ResultPublicationMLTests(TestCase):
    def setUp(self):
        self.doctor = User.objects.create_user(
            username="ml-doctor",
            password="test-password",
            role=User.Role.DOCTEUR,
        )
        self.patient = User.objects.create_user(
            username="ml-patient",
            password="test-password",
            role=User.Role.PATIENT,
        )
        self.lab = User.objects.create_user(
            username="ml-laboratory",
            password="test-password",
            role=User.Role.LABORATOIRE,
        )
        self.analysis_type = TypeAnalyse.objects.create(
            code="HEMO-ML",
            nom="Hémoglobine",
            unite="g/dL",
            valeur_reference_min=Decimal("12.000"),
            valeur_reference_max=Decimal("16.000"),
        )
        self.demand = DemandeAnalyse.objects.create(
            patient=self.patient,
            medecin=self.doctor,
            laboratoire=self.lab,
            cree_par=self.doctor,
        )
        self.analysis = AnalyseDemandee.objects.create(
            demande=self.demand,
            type_analyse=self.analysis_type,
        )
        self.sample = creer_prelevements(self.demand, self.doctor)[0]
        changer_statut(self.sample, Prelevement.Statut.PRELEVE, self.lab)
        self.sample = changer_statut(
            self.sample,
            Prelevement.Statut.RECU,
            self.lab,
        )
        self.url = reverse(
            "laboratoire:prelevement_resultats",
            args=[self.sample.pk],
        )
        self.client.force_login(self.lab)

    def post_result(self, value, **extra):
        return self.client.post(self.url, {
            "action": "valider",
            f"valeur_{self.analysis.pk}": value,
            f"unite_{self.analysis.pk}": "g/dL",
            **extra,
        })

    @patch("laboratoire.views.check_value", return_value=False)
    def test_normal_result_publishes_without_confirmation(self, _check_value):
        response = self.post_result("14,2")

        self.assertEqual(response.status_code, 302)
        result = Resultat.objects.get(analyse_demandee=self.analysis)
        self.assertEqual(result.valeur, "14.2")
        self.assertEqual(result.statut, Resultat.Statut.VALIDE)

    def test_empty_value_is_rejected_before_publication(self):
        response = self.post_result("")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "obligatoire")
        self.assertFalse(Resultat.objects.exists())

    def test_non_positive_value_is_rejected(self):
        response = self.post_result("0")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "strictement supérieur à zéro")
        self.assertFalse(Resultat.objects.exists())

    @patch("laboratoire.views.check_value")
    def test_draft_is_saved_without_calling_the_anomaly_model(self, check):
        response = self.client.post(self.url, {
            "action": "brouillon",
            f"valeur_{self.analysis.pk}": "150",
            f"unite_{self.analysis.pk}": "g/dL",
        })

        self.assertEqual(response.status_code, 302)
        check.assert_not_called()
        result = Resultat.objects.get(analyse_demandee=self.analysis)
        self.assertEqual(result.statut, Resultat.Statut.EN_SAISIE)
        self.assertIsNone(result.date_validation)

    @patch("laboratoire.views.check_value", return_value=True)
    def test_confirmation_is_required_and_bound_to_the_submitted_value(
        self,
        _check_value,
    ):
        warning_response = self.post_result("150")

        self.assertEqual(warning_response.status_code, 200)
        self.assertContains(warning_response, "Valeur inhabituelle, vérifiez la saisie")
        self.assertContains(warning_response, "Corriger")
        self.assertContains(warning_response, "Confirmer quand même")
        self.assertFalse(Resultat.objects.exists())

        stale_confirmation = self.client.post(self.url, {
            "action": "valider",
            f"valeur_{self.analysis.pk}": "142",
            f"unite_{self.analysis.pk}": "g/dL",
            "confirmation_ia": warning_response.context["confirmation_token"],
        })
        self.assertEqual(stale_confirmation.status_code, 200)
        self.assertContains(stale_confirmation, "Valeur inhabituelle, vérifiez la saisie")
        self.assertFalse(Resultat.objects.exists())

        confirmed_response = self.client.post(self.url, {
            "action": "valider",
            f"valeur_{self.analysis.pk}": "150",
            f"unite_{self.analysis.pk}": "g/dL",
            "confirmation_ia": warning_response.context["confirmation_token"],
        })
        self.assertEqual(confirmed_response.status_code, 302)
        result = Resultat.objects.get(analyse_demandee=self.analysis)
        self.assertEqual(result.valeur, "150")
        self.assertEqual(result.statut, Resultat.Statut.VALIDE)
        self.assertEqual(result.valide_par, self.lab)

    def test_non_laboratory_user_cannot_publish(self):
        self.client.force_login(self.doctor)
        response = self.post_result("14.2")

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Resultat.objects.exists())
