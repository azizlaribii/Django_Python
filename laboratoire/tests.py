import re
import json
import socket
from io import BytesIO
from importlib import import_module
from types import SimpleNamespace
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from django.apps import apps
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.utils.functional import SimpleLazyObject
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AssociationMedecinPatient, User

from .forms import (
    DemandeAnalyseForm,
    DemandeAnnulationForm,
    DemandeListFilterForm,
    ParametresLaboratoireForm,
    PrelevementForm,
)
from .models import (
    AnalyseDemandee,
    BilanPredefini,
    DemandeAnalyse,
    CompteRendu,
    HistoriqueAction,
    Prelevement,
    Resultat,
    TypeAnalyse,
)
from .permissions import demandes_visibles, resultats_visibles
from .services import (
    annuler_demande,
    changer_statut,
    corriger_resultat,
    creer_prelevements,
    envoyer_resultats,
    refaire_prelevement,
)
from .services_resume import (
    ResumeAPIError,
    generer_resume,
    preparer_donnees,
    statut_valeur,
)
from .reporting import get_report_data


@override_settings(GOOGLE_API_KEY="", GEMINI_API_KEY="")
class LaboratoireWorkflowTests(TestCase):
    def setUp(self):
        self.doctor = User.objects.create_user(
            username="doctor-workflow",
            password="test-password",
            role=User.Role.DOCTEUR,
        )
        self.patient = User.objects.create_user(
            username="patient-workflow",
            password="test-password",
            role=User.Role.PATIENT,
        )
        self.lab = User.objects.create_user(
            username="lab-workflow",
            password="test-password",
            role=User.Role.LABORATOIRE,
        )
        self.admin = User.objects.create_user(
            username="admin-workflow",
            password="test-password",
            role=User.Role.ADMIN,
        )
        AssociationMedecinPatient.objects.create(
            medecin=self.doctor,
            patient=self.patient,
        )
        self.analyse_sang = TypeAnalyse.objects.create(
            code="GLY-WF",
            nom="Glycémie",
            unite="g/L",
            valeur_reference_min=Decimal("0.700"),
            valeur_reference_max=Decimal("1.100"),
        )
        self.demande = self.creer_demande([self.analyse_sang])

    def test_demo_command_resets_only_demo_requests_and_creates_workflow_scenarios(self):
        call_command("seed_laboratory_demo", verbosity=0)
        call_command("seed_laboratory_demo", verbosity=0)

        demos = list(
            DemandeAnalyse.objects.filter(commentaire__startswith="DEMO_LABO:")
            .prefetch_related("prelevements", "analyses__resultats")
            .order_by("commentaire")
        )
        self.assertEqual(len(demos), 3)
        self.assertTrue(DemandeAnalyse.objects.filter(pk=self.demande.pk).exists())
        self.assertEqual(
            {demande.prelevements.get().statut for demande in demos},
            {
                Prelevement.Statut.A_EFFECTUER,
                Prelevement.Statut.RECU,
                Prelevement.Statut.TERMINE,
            },
        )
        self.assertEqual(
            {demande.statut for demande in demos},
            {
                DemandeAnalyse.Statut.EN_ATTENTE,
                DemandeAnalyse.Statut.EN_COURS,
                DemandeAnalyse.Statut.TERMINEE,
            },
        )
        published_demo = next(
            demande for demande in demos if "03/3" in demande.commentaire
        )
        result = published_demo.analyses.get().resultats.get()
        self.assertEqual(result.statut, Resultat.Statut.VALIDE)
        self.assertTrue(result.valeur)
        self.assertEqual(result.unite, published_demo.analyses.get().type_analyse.unite)
        self.assertEqual(
            HistoriqueAction.objects.filter(
                type_action="DEMANDE_LABO_DEMO_CREEE",
            ).count(),
            6,
        )

    @override_settings(
        ANTHROPIC_API_KEY="test-api-key",
        IA_MODELE="test-model",
    )
    @patch("laboratoire.services_resume.urlopen")
    def test_anthropic_receives_only_pseudonymized_result_fields(self, mock_urlopen):
        mock_urlopen.return_value = BytesIO(json.dumps({
            "content": [{"type": "text", "text": "Glycémie : 1,18 g/L (élevé)."}],
        }).encode("utf-8"))
        lignes = [{
            "analyse": "Glycémie",
            "valeur": "1.18",
            "unite": "g/L",
            "reference": "0.7 à 1.1 g/L",
            "statut": "élevé",
            "valeur_precedente": "1.05",
            "unite_precedente": "g/L",
            "evolution": "Écart : +0.13 g/L",
            "patient_id": 123,
            "patient": "Identité à ne pas transmettre",
        }]

        result = generer_resume(lignes)

        self.assertEqual(result.source, CompteRendu.Source.IA)
        self.assertEqual(result.texte, "Glycémie : 1,18 g/L (élevé).")
        self.assertEqual(result.avertissement, "")
        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        sent_rows = json.loads(payload["messages"][0]["content"])
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(len(sent_rows), 1)
        self.assertNotIn("patient_id", sent_rows[0])
        self.assertNotIn("patient", sent_rows[0])
        self.assertEqual(sent_rows[0]["evolution"], "Écart : +0.13 g/L")
        self.assertIn("aucun diagnostic", payload["system"].lower())
        self.assertIn("comparaison avec l’historique", payload["system"].lower())
        self.assertIn("recommandation", payload["system"].lower())

    def test_ai_summary_marks_incoherent_rows_as_not_comparable(self):
        from laboratoire.services_resume import _donnees_pseudonymisees

        rows = _donnees_pseudonymisees([{
            "analyse": "Analyse",
            "valeur": "1.0",
            "unite": "g/L",
            "reference": "0.7 à 1.1 g/L",
            "statut": "normal",
            "valeur_precedente": "0.9",
            "unite_precedente": "g/L",
            "evolution": "stable",
            "donnee_coherente": False,
        }])

        self.assertEqual(rows[0]["statut"], "non déterminé")
        self.assertEqual(rows[0]["reference"], "Non comparable : données à vérifier")
        self.assertEqual(rows[0]["valeur_precedente"], "")
        self.assertEqual(rows[0]["unite_precedente"], "")
        self.assertEqual(
            rows[0]["evolution"],
            "Comparaison non calculée : données à vérifier",
        )

    @override_settings(
        GOOGLE_API_KEY="test-google-api-key",
        GEMINI_MODEL="gemini-test",
        ANTHROPIC_API_KEY="",
    )
    @patch("laboratoire.services_resume.urlopen")
    def test_gemini_uses_google_header_and_only_pseudonymized_result_fields(
        self,
        mock_urlopen,
    ):
        mock_urlopen.return_value = BytesIO(json.dumps({
            "status": "completed",
            "steps": [{
                "type": "model_output",
                "content": [{
                    "type": "text",
                    "text": "Glycémie : 1,18 g/L.",
                }],
            }],
        }).encode("utf-8"))

        with self.assertLogs("laboratoire.services_resume", level="INFO") as captured:
            result = generer_resume([{
                "analyse": "Glycémie",
                "valeur": "1.18",
                "unite": "g/L",
                "patient_id": 321,
            }])

        self.assertEqual(result.source, CompteRendu.Source.IA)
        self.assertEqual(result.texte, "Glycémie : 1,18 g/L.")
        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://generativelanguage.googleapis.com/v1beta/interactions")
        self.assertEqual(request.get_header("X-goog-api-key"), "test-google-api-key")
        self.assertEqual(payload["model"], "gemini-test")
        self.assertFalse(payload["store"])
        self.assertNotIn("321", payload["input"])
        self.assertIn("aucun diagnostic", payload["system_instruction"].lower())
        self.assertEqual(result.fournisseur, "Gemini")
        self.assertEqual(result.modele, "gemini-test")
        self.assertIn("fournisseur=Gemini modèle=gemini-test", captured.output[0])
        self.assertNotIn("test-google-api-key", captured.output[0])

    @override_settings(
        GOOGLE_API_KEY="test-secret-key-never-log",
        GEMINI_MODEL="gemini-test",
        ANTHROPIC_API_KEY="",
    )
    @patch(
        "laboratoire.services_resume.urlopen",
        side_effect=HTTPError(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            429,
            "quota",
            {},
            BytesIO(b'{"error":"sensitive provider response"}'),
        ),
    )
    def test_provider_quota_error_is_logged_without_key_or_result_data(self, mock_urlopen):
        with self.assertLogs("laboratoire.services_resume", level="WARNING") as captured:
            with self.assertRaisesRegex(
                ResumeAPIError,
                "quota ou limite de requêtes dépassé",
            ):
                generer_resume([{
                    "analyse": "Analyse privée",
                    "valeur": "1.23",
                    "patient": "Identité privée",
                }])

        self.assertTrue(any("http_status=429" in line for line in captured.output))
        logs = "\n".join(captured.output)
        self.assertNotIn("test-secret-key-never-log", logs)
        self.assertNotIn("Analyse privée", logs)
        self.assertNotIn("Identité privée", logs)
        self.assertNotIn("sensitive provider response", logs)
        mock_urlopen.assert_called_once()

    @override_settings(
        GOOGLE_API_KEY="",
        GEMINI_API_KEY="",
        ANTHROPIC_API_KEY="",
    )
    def test_missing_api_key_does_not_create_a_rule_based_summary(self):
        with self.assertRaisesRegex(ResumeAPIError, "Aucun fournisseur IA"):
            generer_resume([{"analyse": "Glycémie", "valeur": "1.18"}])

    @override_settings(ANTHROPIC_API_KEY="test-api-key")
    @patch(
        "laboratoire.services_resume._appeler_anthropic",
        return_value="Il est recommandé de consulter un médecin.",
    )
    def test_ai_response_with_recommendation_is_rejected(self, mock_ai):
        with self.assertRaisesRegex(ResumeAPIError, "réponse IA a été écartée"):
            generer_resume([{"analyse": "Glycémie", "valeur": "1.18"}])

        mock_ai.assert_called_once()

    @override_settings(ANTHROPIC_API_KEY="test-api-key")
    @patch(
        "laboratoire.services_resume._appeler_anthropic",
        side_effect=ResumeAPIError,
    )
    def test_api_failure_does_not_fallback_to_local_summary(self, mock_ai):
        with self.assertRaises(ResumeAPIError):
            generer_resume([{"analyse": "Glycémie", "valeur": "1.18"}])

        mock_ai.assert_called_once()

    def creer_demande(self, types, *, priorite=DemandeAnalyse.Priorite.NORMALE, commentaire=""):
        demande = DemandeAnalyse.objects.create(
            patient=self.patient,
            medecin=self.doctor,
            laboratoire=self.lab,
            cree_par=self.doctor,
            priorite=priorite,
            commentaire=commentaire,
        )
        for type_analyse in types:
            AnalyseDemandee.objects.create(
                demande=demande,
                type_analyse=type_analyse,
            )
        return demande

    def faire_avancer(self, prelevement):
        changer_statut(prelevement, Prelevement.Statut.PRELEVE, self.lab)
        return changer_statut(prelevement, Prelevement.Statut.RECU, self.lab)

    def test_creates_one_empty_dated_sample_per_sample_type_and_reuses_it(self):
        analyse_uree = TypeAnalyse.objects.create(
            code="URE-WF",
            nom="Urée",
            type_echantillon=TypeAnalyse.TypeEchantillon.SANG,
        )
        analyse_urine = TypeAnalyse.objects.create(
            code="UR-WF",
            nom="Analyse urinaire",
            type_echantillon=TypeAnalyse.TypeEchantillon.URINE,
        )
        AnalyseDemandee.objects.create(
            demande=self.demande,
            type_analyse=analyse_uree,
        )
        AnalyseDemandee.objects.create(
            demande=self.demande,
            type_analyse=analyse_urine,
        )

        created = creer_prelevements(self.demande, self.doctor)
        self.assertEqual(len(created), 2)
        self.assertEqual(self.demande.prelevements.count(), 2)
        sang = self.demande.prelevements.get(type_prelevement=Prelevement.Type.SANG)
        urine = self.demande.prelevements.get(type_prelevement=Prelevement.Type.URINE)
        self.assertEqual(sang.analyses.count(), 2)
        self.assertEqual(urine.analyses.count(), 1)
        codes = list(
            self.demande.prelevements.values_list("code_prelevement", flat=True),
        )
        self.assertTrue(all(codes))
        self.assertEqual(len(codes), len(set(codes)))
        for sample in self.demande.prelevements.all():
            self.assertEqual(sample.statut, Prelevement.Statut.A_EFFECTUER)
            self.assertIsNone(sample.date_prelevement)
            self.assertIsNone(sample.date_reception)

        self.assertEqual(creer_prelevements(self.demande, self.doctor), [])
        self.assertEqual(self.demande.prelevements.count(), 2)

    def test_migration_backfills_only_unambiguous_existing_samples(self):
        unique_sample = Prelevement.objects.create(
            demande=self.demande,
            type_prelevement=Prelevement.Type.SANG,
        )
        ambiguous_demand = self.creer_demande([self.analyse_sang])
        first_sample = Prelevement.objects.create(
            demande=ambiguous_demand,
            type_prelevement=Prelevement.Type.SANG,
        )
        Prelevement.objects.create(
            demande=ambiguous_demand,
            type_prelevement=Prelevement.Type.SANG,
        )
        unlinked_demand = self.creer_demande([self.analyse_sang])

        backfill_migration = import_module(
            "laboratoire.migrations.0010_backfill_unambiguous_samples",
        )
        create_migration = import_module(
            "laboratoire.migrations.0011_create_missing_legacy_samples",
        )
        backfill_migration.backfill_unambiguous_samples(
            apps,
            SimpleNamespace(connection=connection),
        )
        create_migration.create_missing_legacy_samples(
            apps,
            SimpleNamespace(connection=connection),
        )

        self.demande.analyses.get().refresh_from_db()
        ambiguous_analysis = ambiguous_demand.analyses.get()
        ambiguous_analysis.refresh_from_db()
        unlinked_analysis = unlinked_demand.analyses.get()
        unlinked_analysis.refresh_from_db()
        self.assertEqual(self.demande.analyses.get().prelevement, unique_sample)
        self.assertIsNone(ambiguous_analysis.prelevement)
        self.assertNotEqual(first_sample.pk, ambiguous_analysis.prelevement_id)
        self.assertEqual(
            unlinked_analysis.prelevement.statut,
            Prelevement.Statut.A_EFFECTUER,
        )

    def test_transitions_set_dates_users_and_audit_and_reject_invalid_steps(self):
        sample = creer_prelevements(self.demande, self.doctor)[0]
        self.assertIsNone(sample.date_prelevement)
        self.assertIsNone(sample.date_reception)

        sample = changer_statut(sample, Prelevement.Statut.RECU, self.lab)
        self.assertIsNotNone(sample.date_prelevement)
        self.assertIsNotNone(sample.date_reception)
        self.assertGreaterEqual(sample.date_reception, sample.date_prelevement)
        self.assertEqual(sample.preleve_par, self.lab)
        self.assertEqual(sample.recu_par, self.lab)
        self.assertEqual(
            HistoriqueAction.objects.filter(
                objet_concerne="Prelevement",
                objet_id=sample.pk,
                utilisateur=self.lab,
                type_action="PRELEVEMENT_STATUT_MODIFIE",
            ).count(),
            1,
        )

        legacy_demand = self.creer_demande([self.analyse_sang])
        legacy_sample = creer_prelevements(legacy_demand, self.doctor)[0]
        legacy_sample = changer_statut(
            legacy_sample,
            Prelevement.Statut.PRELEVE,
            self.lab,
        )
        collection_date = legacy_sample.date_prelevement
        legacy_sample = changer_statut(
            legacy_sample,
            Prelevement.Statut.RECU,
            self.lab,
        )
        self.assertEqual(legacy_sample.date_prelevement, collection_date)
        self.assertGreaterEqual(legacy_sample.date_reception, collection_date)

    def test_sample_edit_is_disabled_and_does_not_change_sample_data(self):
        sample = creer_prelevements(self.demande, self.doctor)[0]
        form = PrelevementForm(instance=sample)
        self.assertNotIn("code_prelevement", form.fields)
        self.assertNotIn("date_prelevement", form.fields)
        self.assertNotIn("date_reception", form.fields)

        self.client.force_login(self.lab)
        url = reverse("laboratoire:prelevement_update", args=[sample.pk])
        response = self.client.get(url)
        self.assertRedirects(
            response,
            f"{reverse('laboratoire:prelevement_list')}?onglet=a_traiter&statut=A_EFFECTUER",
            fetch_redirect_response=False,
        )
        self.assertContains(
            self.client.get(response.url),
            "La modification directe des prélèvements est désactivée.",
        )
        response = self.client.post(url, {
            "type_prelevement": Prelevement.Type.URINE,
            "precision_type": "",
            "remarque": "Modification interdite",
        })
        self.assertRedirects(
            response,
            f"{reverse('laboratoire:prelevement_list')}?onglet=a_traiter&statut=A_EFFECTUER",
            fetch_redirect_response=False,
        )
        sample.refresh_from_db()
        self.assertEqual(sample.type_prelevement, Prelevement.Type.SANG)
        self.assertEqual(sample.remarque, "")
        self.assertNotEqual(sample.code_prelevement, "CODE-MANUEL")
        self.assertIsNone(sample.date_prelevement)
        self.assertIsNone(sample.date_reception)

    def test_sample_form_requires_precision_for_other_sample_type(self):
        form = PrelevementForm(
            data={
                "type_prelevement": Prelevement.Type.AUTRE,
                "precision_type": "   ",
                "remarque": "",
            },
            instance=Prelevement(demande=self.demande),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("precision_type", form.errors)

    def test_laboratory_filter_forms_reject_invalid_date_ranges(self):
        demande_filter = DemandeListFilterForm(data={
            "date_debut": "2026-12-31",
            "date_fin": "2026-01-01",
        })
        self.assertFalse(demande_filter.is_valid())
        self.assertIn("date_fin", demande_filter.errors)

        self.client.force_login(self.lab)
        response = self.client.get(reverse("laboratoire:prelevement_list"), {
            "onglet": "a_traiter",
            "date_debut": "not-a-date",
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn("date_debut", response.context["filter_form"].errors)
        self.assertContains(response, "Saisissez une date valide.")

    def test_free_text_inputs_enforce_server_side_limits(self):
        cancel_form = DemandeAnnulationForm(data={"motif": "   "})
        self.assertFalse(cancel_form.is_valid())
        self.assertIn("motif", cancel_form.errors)

        settings_form = ParametresLaboratoireForm(data={
            "nom": "",
            "adresse": "",
            "telephone": "",
            "entete_compte_rendu": "x" * 2001,
            "signature_compte_rendu": "",
            "motifs_rejet": "x" * 121,
            "delai_alerte_urgente_minutes": "60",
        })
        self.assertFalse(settings_form.is_valid())
        self.assertIn("entete_compte_rendu", settings_form.errors)
        self.assertIn("motifs_rejet", settings_form.errors)

    def test_reprinting_label_keeps_code_and_only_shows_recorded_collection_date(self):
        sample = creer_prelevements(self.demande, self.doctor)[0]
        self.client.force_login(self.lab)
        url = reverse("laboratoire:prelevement_etiquette", args=[sample.pk])

        first_print = self.client.get(url)
        list_url = (
            f"{reverse('laboratoire:prelevement_list')}"
            "?onglet=a_traiter&statut=A_EFFECTUER"
        )
        self.assertRedirects(first_print, list_url, fetch_redirect_response=False)
        detail_response = self.client.get(list_url)
        self.assertContains(detail_response, "Étiquette après réception")
        self.assertNotContains(
            detail_response,
            reverse("laboratoire:prelevement_etiquette", args=[sample.pk]),
        )
        sample.refresh_from_db()
        self.assertEqual(sample.statut, Prelevement.Statut.A_EFFECTUER)
        self.assertIsNone(sample.date_prelevement)

        sample = changer_statut(sample, Prelevement.Statut.RECU, self.lab)
        detail_after_receipt = self.client.get(
            reverse("laboratoire:prelevement_list"),
            {"onglet": "resultats", "statut": "RECU"},
        )
        self.assertContains(
            detail_after_receipt,
            reverse("laboratoire:prelevement_etiquette", args=[sample.pk]),
        )
        printed_after_collection = self.client.get(url)
        second_print = self.client.get(url)
        self.assertEqual(printed_after_collection.status_code, 200)
        self.assertEqual(second_print.status_code, 200)
        self.assertContains(printed_after_collection, sample.code_prelevement)
        self.assertContains(
            printed_after_collection,
            timezone.localtime(sample.date_prelevement).strftime("%d/%m/%Y %H:%M"),
        )
        self.assertEqual(
            printed_after_collection.context["prelevement"].code_prelevement,
            second_print.context["prelevement"].code_prelevement,
        )
        sample.refresh_from_db()
        self.assertEqual(sample.statut, Prelevement.Statut.RECU)
        self.assertEqual(
            sample.code_prelevement,
            printed_after_collection.context["prelevement"].code_prelevement,
        )

    def test_sample_form_and_label_preserve_request_status_statistics(self):
        sample = creer_prelevements(self.demande, self.doctor)[0]
        self.client.force_login(self.lab)
        status_counts_before = get_report_data()["statuts"]

        update_response = self.client.post(
            reverse("laboratoire:prelevement_update", args=[sample.pk]),
            {
                "type_prelevement": Prelevement.Type.SANG,
                "precision_type": "",
                "remarque": "Contrôle du prélèvement",
            },
        )
        self.assertRedirects(
            update_response,
            f"{reverse('laboratoire:prelevement_list')}?onglet=a_traiter&statut=A_EFFECTUER",
            fetch_redirect_response=False,
        )
        list_after_blocked_edit = self.client.get(update_response.url)
        self.assertContains(
            list_after_blocked_edit,
            "La modification directe des prélèvements est désactivée.",
        )
        status_counts_after_edit = get_report_data()["statuts"]
        self.assertEqual(status_counts_after_edit, status_counts_before)
        sample.refresh_from_db()
        self.assertEqual(sample.remarque, "")
        self.assertEqual(
            {item["code"]: item["nombre"] for item in status_counts_before},
            {
                DemandeAnalyse.Statut.EN_ATTENTE: 1,
                DemandeAnalyse.Statut.EN_COURS: 0,
                DemandeAnalyse.Statut.TERMINEE: 0,
                DemandeAnalyse.Statut.ANNULEE: 0,
            },
        )
        sample = changer_statut(sample, Prelevement.Statut.RECU, self.lab)
        status_counts_before_print = get_report_data()["statuts"]
        label_url = reverse("laboratoire:prelevement_etiquette", args=[sample.pk])
        self.assertEqual(self.client.get(label_url).status_code, 200)
        self.assertEqual(self.client.get(label_url).status_code, 200)

        status_counts_after = get_report_data()["statuts"]
        self.assertEqual(status_counts_after, status_counts_before_print)
        self.assertEqual(
            {item["code"]: item["nombre"] for item in status_counts_after},
            {
                DemandeAnalyse.Statut.EN_ATTENTE: 0,
                DemandeAnalyse.Statut.EN_COURS: 1,
                DemandeAnalyse.Statut.TERMINEE: 0,
                DemandeAnalyse.Statut.ANNULEE: 0,
            },
        )
        self.demande.refresh_from_db()
        self.assertEqual(self.demande.statut, DemandeAnalyse.Statut.EN_COURS)

    def test_sample_dates_cannot_be_set_in_the_future(self):
        sample = creer_prelevements(self.demande, self.doctor)[0]
        sample.statut = Prelevement.Statut.PRELEVE
        sample.date_prelevement = timezone.now() + timedelta(days=1)

        with self.assertRaises(ValidationError):
            sample.full_clean()

    def test_rejection_requires_a_reason_and_retry_relinks_analyses(self):
        sample = creer_prelevements(self.demande, self.doctor)[0]
        changer_statut(sample, Prelevement.Statut.PRELEVE, self.lab)
        with self.assertRaises(ValidationError):
            changer_statut(
                sample,
                Prelevement.Statut.REJETE,
                self.lab,
                motif="Autre",
            )

        sample = changer_statut(
            sample,
            Prelevement.Statut.REJETE,
            self.lab,
            motif="Autre",
            remarque="Tube endommagé",
        )
        self.assertEqual(sample.motif_rejet, "Autre")
        self.assertEqual(sample.remarque, "Tube endommagé")

        retry = refaire_prelevement(sample, self.lab)
        self.assertNotEqual(retry.code_prelevement, sample.code_prelevement)
        self.assertEqual(retry.prelevement_precedent, sample)
        self.assertEqual(retry.statut, Prelevement.Statut.A_EFFECTUER)
        self.assertIsNone(retry.date_prelevement)
        self.assertIsNone(retry.date_reception)
        self.assertEqual(self.analyse_sang.demandes.get().prelevement, retry)
        self.assertTrue(
            HistoriqueAction.objects.filter(
                utilisateur=self.lab,
                type_action="PRELEVEMENT_REFAIT",
                objet_id=retry.pk,
            ).exists()
        )

    def test_urgent_validation_and_request_cancellation_are_audited(self):
        urgent = DemandeAnalyse(
            patient=self.patient,
            medecin=self.doctor,
            laboratoire=self.lab,
            priorite=DemandeAnalyse.Priorite.URGENTE,
        )
        with self.assertRaises(ValidationError):
            urgent.full_clean()

        sample = creer_prelevements(self.demande, self.doctor)[0]
        cancelled = annuler_demande(
            demande=self.demande,
            utilisateur=self.doctor,
            motif="Prescription non nécessaire",
        )
        sample.refresh_from_db()
        self.analyse_sang.demandes.get(demande=self.demande).refresh_from_db()
        self.assertEqual(cancelled.statut, DemandeAnalyse.Statut.ANNULEE)
        self.assertEqual(cancelled.motif_annulation, "Prescription non nécessaire")
        self.assertEqual(sample.statut, Prelevement.Statut.ANNULE)
        self.assertEqual(
            self.analyse_sang.demandes.get(demande=self.demande).statut,
            AnalyseDemandee.Statut.ANNULEE,
        )
        self.assertTrue(
            HistoriqueAction.objects.filter(
                utilisateur=self.doctor,
                type_action="DEMANDE_ANNULEE",
                objet_id=self.demande.pk,
            ).exists()
        )

        another = self.creer_demande([self.analyse_sang])
        started_sample = creer_prelevements(another, self.doctor)[0]
        changer_statut(started_sample, Prelevement.Statut.PRELEVE, self.lab)
        with self.assertRaises(ValidationError):
            annuler_demande(
                demande=another,
                utilisateur=self.doctor,
                motif="Trop tard",
            )

    def test_results_are_blocked_before_receipt_and_validated_by_laboratory(self):
        sample = creer_prelevements(self.demande, self.doctor)[0]
        with self.assertRaises(ValidationError):
            envoyer_resultats(
                analyse_demandee=self.demande.analyses.get(),
                utilisateur=self.lab,
                donnees={"valeur": "0.9"},
            )

        sample = self.faire_avancer(sample)
        resultat = envoyer_resultats(
            analyse_demandee=self.demande.analyses.get(),
            utilisateur=self.lab,
            donnees={"valeur": "0.9"},
            prelevement=sample,
        )
        sample.refresh_from_db()
        self.demande.refresh_from_db()
        self.assertEqual(resultat.statut, Resultat.Statut.VALIDE)
        self.assertEqual(resultat.valide_par, self.lab)
        self.assertEqual(resultat.prelevement, sample)
        self.assertEqual(sample.statut, Prelevement.Statut.TERMINE)
        self.assertEqual(self.demande.statut, DemandeAnalyse.Statut.TERMINEE)
        self.assertTrue(
            HistoriqueAction.objects.filter(
                utilisateur=self.lab,
                type_action="RESULTAT_ENVOYE",
                objet_id=resultat.pk,
            ).exists()
        )

    def test_result_correction_increments_version_and_records_previous_value(self):
        sample = creer_prelevements(self.demande, self.doctor)[0]
        sample = self.faire_avancer(sample)
        resultat = envoyer_resultats(
            analyse_demandee=self.demande.analyses.get(),
            utilisateur=self.lab,
            donnees={"valeur": "0.9", "unite": "g/L"},
            prelevement=sample,
        )
        values = {"valeur": "0.95", "unite": "g/L"}
        with self.assertRaises(ValidationError):
            corriger_resultat(
                resultat=resultat,
                utilisateur=self.lab,
                donnees=values,
                motif=" ",
            )

        corrected = corriger_resultat(
            resultat=resultat,
            utilisateur=self.lab,
            donnees=values,
            motif="Erreur de saisie",
        )
        action = HistoriqueAction.objects.get(
            type_action="RESULTAT_CORRIGE",
            objet_id=resultat.pk,
        )
        self.assertEqual(corrected.version, 2)
        self.assertEqual(corrected.motif_correction, "Erreur de saisie")
        self.assertEqual(action.details["avant"]["valeur"], "0.9")
        self.assertEqual(action.details["motif"], "Erreur de saisie")

    def test_role_scopes_demands_and_results_and_admin_is_read_only(self):
        sample = creer_prelevements(self.demande, self.doctor)[0]
        sample = self.faire_avancer(sample)
        resultat = envoyer_resultats(
            analyse_demandee=self.demande.analyses.get(),
            utilisateur=self.lab,
            donnees={"valeur": "1.0"},
            prelevement=sample,
        )
        other_doctor = User.objects.create_user(
            username="other-doctor",
            password="test-password",
            role=User.Role.DOCTEUR,
        )
        other_demand = DemandeAnalyse.objects.create(
            patient=self.patient,
            medecin=other_doctor,
            laboratoire=self.lab,
            cree_par=other_doctor,
        )

        self.assertEqual(list(demandes_visibles(self.doctor)), [self.demande])
        self.assertNotIn(other_demand, demandes_visibles(self.doctor))
        self.assertEqual(list(resultats_visibles(self.patient)), [resultat])
        self.assertEqual(list(resultats_visibles(self.admin)), [resultat])
        other_patient = User.objects.create_user(
            username="other-patient-workflow",
            password="test-password",
            role=User.Role.PATIENT,
        )
        other_lab = User.objects.create_user(
            username="other-lab-workflow",
            password="test-password",
            role=User.Role.LABORATOIRE,
        )
        self.assertFalse(resultats_visibles(other_patient).exists())
        self.assertIn(self.demande, demandes_visibles(other_lab))
        self.assertTrue(
            HistoriqueAction.objects.filter(
                utilisateur=self.lab,
                type_action="RESULTAT_ENVOYE",
            ).exists()
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse("laboratoire:prelevement_list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="etape" value="PRELEVE"')
        self.assertEqual(
            self.client.post(
                reverse("laboratoire:prelevement_etape", args=[sample.pk]),
                {"etape": "PRELEVE"},
            ).status_code,
            403,
        )

    def test_laboratory_team_ids_support_lazy_users_and_admins(self):
        from .permissions import laboratory_team_user_ids

        lazy_lab = SimpleLazyObject(lambda: self.lab)
        self.assertEqual(
            list(laboratory_team_user_ids(lazy_lab)),
            [self.lab.pk],
        )
        self.assertEqual(
            set(laboratory_team_user_ids(self.admin)),
            {self.lab.pk},
        )
        self.assertFalse(laboratory_team_user_ids(AnonymousUser()).exists())

    def test_lab_dashboard_is_dedicated_to_laboratory(self):
        dashboard_url = reverse("lab_dashboard")
        creer_prelevements(self.demande, self.doctor)
        self.client.force_login(self.lab)
        response = self.client.get(dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tableau de bord")
        self.assertContains(response, "Prélèvements à effectuer")
        self.assertContains(response, self.patient.username)
        self.assertContains(
            response,
            reverse("laboratoire:prelevement_list"),
        )
        self.assertNotContains(response, "File des demandes")

        self.client.force_login(self.admin)
        response = self.client.get(dashboard_url)
        self.assertRedirects(
            response,
            reverse("laboratoire:demande_list"),
            fetch_redirect_response=False,
        )
        response = self.client.get(response.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "File des demandes")

        self.client.force_login(self.doctor)
        response = self.client.get(dashboard_url)
        self.assertRedirects(
            response,
            reverse("dashboard"),
            fetch_redirect_response=False,
        )

    def test_doctor_patient_history_only_shows_results_from_own_requests(self):
        other_doctor = User.objects.create_user(
            username="other-history-doctor",
            password="test-password",
            role=User.Role.DOCTEUR,
        )
        other_type = TypeAnalyse.objects.create(
            code="OTHER-HISTORY",
            nom="Analyse confidentielle",
        )
        other_demand = DemandeAnalyse.objects.create(
            patient=self.patient,
            medecin=other_doctor,
            cree_par=other_doctor,
        )
        other_analysis = AnalyseDemandee.objects.create(
            demande=other_demand,
            type_analyse=other_type,
        )
        Resultat.objects.create(
            analyse_demandee=other_analysis,
            valeur="DONNEE-PRIVEE",
            saisi_par=other_doctor,
            valide_par=other_doctor,
            statut=Resultat.Statut.VALIDE,
        )

        self.client.force_login(self.doctor)
        response = self.client.get(reverse(
            "laboratoire:doctor_patient_history",
            args=[self.patient.pk],
        ))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "DONNEE-PRIVEE")

    def test_doctor_request_creates_pending_sample_and_admin_can_only_read_it(self):
        self.client.force_login(self.doctor)
        form_url = reverse("laboratoire:demande_create")
        modal_response = self.client.get(f"{form_url}?modal=1")
        self.assertEqual(modal_response.status_code, 200)
        self.assertContains(modal_response, "data-prescription-form")

        invalid_response = self.client.post(
            f"{form_url}?modal=1",
            {
                "patient": self.patient.pk,
                "priorite": DemandeAnalyse.Priorite.URGENTE,
                "commentaire": "",
                "analyses": [],
                "bilans": [],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(invalid_response.status_code, 200)
        self.assertContains(invalid_response, "Motif médical")
        self.assertContains(invalid_response, "sélectionner au moins une analyse")
        self.assertFalse(DemandeAnalyse.objects.filter(
            priorite=DemandeAnalyse.Priorite.URGENTE,
        ).exists())

        response = self.client.post(f"{form_url}?modal=1", {
            "patient": self.patient.pk,
            "priorite": DemandeAnalyse.Priorite.NORMALE,
            "commentaire": "Contrôle",
            "analyses": [self.analyse_sang.pk],
            "bilans": [],
            "medecin": self.admin.pk,
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        demande = DemandeAnalyse.objects.get(commentaire="Contrôle")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["redirect_url"],
            reverse("laboratoire:demande_list"),
        )
        list_response = self.client.get(response.json()["redirect_url"])
        self.assertContains(list_response, "La demande d’analyses a été créée.")
        sample = demande.prelevements.get()
        self.assertEqual(sample.statut, Prelevement.Statut.A_EFFECTUER)
        self.assertIsNone(sample.date_prelevement)
        self.assertIsNone(sample.date_reception)
        self.assertEqual(demande.medecin, self.doctor)
        self.assertNotIn("laboratoire", DemandeAnalyseForm(user=self.doctor).fields)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("laboratoire:prelevement_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, sample.code_prelevement)
        self.assertNotContains(response, 'name="etape" value="PRELEVE"')

    def test_doctor_can_edit_a_request_in_the_centered_modal(self):
        self.client.force_login(self.doctor)
        detail_url = reverse("laboratoire:demande_detail", args=[self.demande.pk])
        update_url = reverse("laboratoire:demande_update", args=[self.demande.pk])

        detail_response = self.client.get(detail_url)
        self.assertIn("no-store", detail_response["Cache-Control"])
        self.assertContains(detail_response, 'data-request-dialog')
        self.assertContains(detail_response, "Modifier la demande")
        self.assertContains(detail_response, "demande_modal.js")
        self.assertContains(detail_response, 'id="cancel-request-dialog"')
        self.assertNotContains(detail_response, "onsubmit=")

        modal_response = self.client.get(f"{update_url}?modal=1")
        self.assertEqual(modal_response.status_code, 200)
        self.assertContains(modal_response, "data-prescription-form")
        self.assertContains(modal_response, "Enregistrer les modifications")
        self.assertContains(modal_response, f'action="{update_url}?modal=1"')

        invalid_response = self.client.post(
            f"{update_url}?modal=1",
            {
                "patient": self.patient.pk,
                "priorite": DemandeAnalyse.Priorite.URGENTE,
                "commentaire": "",
                "analyses": [],
                "bilans": [],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(invalid_response.status_code, 200)
        self.assertContains(invalid_response, "Motif médical")
        self.assertContains(invalid_response, "sélectionner au moins une analyse")

        save_response = self.client.post(
            f"{update_url}?modal=1",
            {
                "patient": self.patient.pk,
                "priorite": DemandeAnalyse.Priorite.HAUTE,
                "commentaire": "Demande mise à jour",
                "analyses": [self.analyse_sang.pk],
                "bilans": [],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.json()["redirect_url"], detail_url)
        self.demande.refresh_from_db()
        self.assertEqual(self.demande.priorite, DemandeAnalyse.Priorite.HAUTE)
        self.assertEqual(self.demande.commentaire, "Demande mise à jour")
        self.assertTrue(HistoriqueAction.objects.filter(
            utilisateur=self.doctor,
            type_action="DEMANDE_MODIFIEE",
            objet_id=self.demande.pk,
        ).exists())

    def test_request_cancellation_form_works_with_csrf_checks_enabled(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.doctor)
        detail_url = reverse(
            "laboratoire:demande_detail",
            args=[self.demande.pk],
        )
        detail_response = csrf_client.get(detail_url)
        self.assertIn("no-store", detail_response["Cache-Control"])
        csrf_token = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"',
            detail_response.content.decode(),
        )
        self.assertIsNotNone(csrf_token)

        cancel_response = csrf_client.post(
            reverse("laboratoire:demande_cancel", args=[self.demande.pk]),
            {
                "csrfmiddlewaretoken": csrf_token.group(1),
                "motif": "Annulation de test",
            },
            follow=True,
        )

        self.assertEqual(cancel_response.status_code, 200)
        self.demande.refresh_from_db()
        self.assertEqual(
            self.demande.statut,
            DemandeAnalyse.Statut.ANNULEE,
        )

    def test_unchecking_a_bundle_removes_its_analyses_when_editing(self):
        analyse_crp = TypeAnalyse.objects.create(
            code="CRP-WF",
            nom="CRP",
            unite="mg/L",
        )
        analyse_tsh = TypeAnalyse.objects.create(
            code="TSH-WF",
            nom="TSH",
            unite="mUI/L",
        )
        bilan = BilanPredefini.objects.create(nom="Bilan inflammatoire")
        bilan.analyses.set([self.analyse_sang, analyse_crp])
        AnalyseDemandee.objects.create(
            demande=self.demande,
            type_analyse=analyse_crp,
        )
        AnalyseDemandee.objects.create(
            demande=self.demande,
            type_analyse=analyse_tsh,
        )
        update_url = reverse("laboratoire:demande_update", args=[self.demande.pk])

        self.client.force_login(self.doctor)
        modal_response = self.client.get(f"{update_url}?modal=1")

        self.assertContains(modal_response, 'data-analysis-ids="')
        self.assertRegex(
            modal_response.content.decode(),
            rf'name="bilans"[^>]*value="{bilan.pk}"[^>]*checked',
        )
        response = self.client.post(
            f"{update_url}?modal=1",
            {
                "patient": self.patient.pk,
                "priorite": DemandeAnalyse.Priorite.NORMALE,
                "commentaire": "Bilan ajusté",
                "analyses": [analyse_tsh.pk],
                "bilans": [],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        active_analysis_ids = set(
            self.demande.analyses.exclude(
                statut=AnalyseDemandee.Statut.ANNULEE,
            ).values_list("type_analyse_id", flat=True)
        )
        self.assertEqual(active_analysis_ids, {analyse_tsh.pk})
        self.assertEqual(
            self.demande.analyses.filter(
                statut=AnalyseDemandee.Statut.ANNULEE,
            ).count(),
            2,
        )
        detail_response = self.client.get(
            reverse("laboratoire:demande_detail", args=[self.demande.pk])
        )
        self.assertContains(
            detail_response,
            "Analyses retirées — conservées dans l’historique",
        )
        self.assertContains(detail_response, "TSH")
        self.assertContains(detail_response, "CRP")

    def test_patient_is_disabled_when_editing_a_request(self):
        another_patient = User.objects.create_user(
            username="another-patient-workflow",
            first_name="Autre",
            last_name="Patient",
            role=User.Role.PATIENT,
        )
        AssociationMedecinPatient.objects.create(
            medecin=self.doctor,
            patient=another_patient,
        )
        update_url = reverse("laboratoire:demande_update", args=[self.demande.pk])
        self.client.force_login(self.doctor)

        modal_response = self.client.get(f"{update_url}?modal=1")

        self.assertContains(modal_response, "Patient actuel :")
        self.assertContains(modal_response, "patient-workflow")
        self.assertContains(modal_response, 'name="patient"')
        self.assertContains(modal_response, "disabled")
        self.assertNotContains(modal_response, f'value="{another_patient.pk}"')
        response = self.client.post(
            f"{update_url}?modal=1",
            {
                "patient": another_patient.pk,
                "priorite": DemandeAnalyse.Priorite.NORMALE,
                "commentaire": "Patient corrigé",
                "analyses": [self.analyse_sang.pk],
                "bilans": [],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.demande.refresh_from_db()
        self.assertEqual(self.demande.patient, self.patient)

    def test_admin_supervision_is_read_only_and_shows_request_statistics(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("laboratoire:supervision"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "En attente")
        self.assertContains(response, "En cours")
        self.assertContains(response, "Terminées")
        self.assertNotContains(response, "Réaffecter")
        self.assertNotContains(response, "Annuler (motif obligatoire)")

    def test_admin_laboratory_menu_links_to_existing_pages_only(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("laboratoire:demande_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="nav-laboratoire-menu"')
        self.assertEqual(response.content.decode().count('class="nav-mega-link"'), 2)
        for route in (
            "laboratoire:type_list",
            "laboratoire:historique",
        ):
            with self.subTest(route=route):
                self.assertContains(response, reverse(route))
        self.assertNotContains(response, reverse("laboratoire:supervision"))
        self.assertNotContains(response, reverse("laboratoire:prelevement_list"))
        for route in (
            "laboratoire:bilan_list",
            "laboratoire:demande_list",
            "laboratoire:prelevement_list",
            "laboratoire:supervision",
            "laboratoire:rapports",
        ):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(reverse(route)).status_code, 200)

        catalogue_response = self.client.get(reverse("laboratoire:type_list"))
        self.assertContains(catalogue_response, reverse("laboratoire:bilan_list"))
        self.assertNotContains(catalogue_response, reverse("laboratoire:parametres"))
        self.assertNotContains(catalogue_response, "← Demandes")

        self.client.force_login(self.doctor)
        doctor_response = self.client.get(reverse("laboratoire:demande_list"))
        self.assertNotContains(doctor_response, "Gestion du laboratoire")
        self.assertNotContains(doctor_response, 'id="nav-laboratoire-menu"')

    def test_admin_can_manage_analysis_catalog_in_modals_and_archive_entries(self):
        self.client.force_login(self.admin)
        list_url = reverse("laboratoire:type_list")
        create_url = reverse("laboratoire:type_create")

        response = self.client.get(list_url)
        self.assertContains(response, "catalogue_modal.js")
        self.assertContains(response, "Archiver")
        self.assertContains(response, "data-open-catalog-dialog")
        self.assertContains(response, "data-confirm-archive")

        modal_response = self.client.get(f"{create_url}?modal=1")
        self.assertEqual(modal_response.status_code, 200)
        for field in (
            'name="code"',
            'name="nom"',
            'name="description"',
            'name="unite"',
            'name="type_echantillon"',
            'name="valeur_reference_min"',
            'name="valeur_reference_max"',
            'name="seuil_critique_bas"',
            'name="seuil_critique_haut"',
            'name="tarif"',
            'name="actif"',
        ):
            with self.subTest(field=field):
                self.assertContains(modal_response, field)
        self.assertContains(modal_response, 'type="number"')
        self.assertContains(modal_response, 'step="any"')

        invalid_response = self.client.post(
            f"{create_url}?modal=1",
            {
                "code": "CATALOG-RANGE",
                "nom": "Références incorrectes",
                "type_echantillon": TypeAnalyse.TypeEchantillon.SANG,
                "valeur_reference_min": "8",
                "valeur_reference_max": "2",
                "actif": "on",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(invalid_response.status_code, 200)
        self.assertContains(
            invalid_response,
            "La valeur maximale doit être supérieure à la valeur minimale.",
        )
        self.assertFalse(TypeAnalyse.objects.filter(code="CATALOG-RANGE").exists())

        created = self.client.post(
            f"{create_url}?modal=1",
            {
                "code": "CATALOG-NEW",
                "nom": "Analyse catalogue",
                "description": "Analyse de contrôle",
                "unite": "g/L",
                "type_echantillon": TypeAnalyse.TypeEchantillon.SANG,
                "valeur_reference_min": "0.5",
                "valeur_reference_max": "1.5",
                "seuil_critique_bas": "0.1",
                "seuil_critique_haut": "3",
                "tarif": "12.50",
                "actif": "on",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(created.status_code, 200)
        self.assertTrue(created.json()["success"])
        analyse = TypeAnalyse.objects.get(code="CATALOG-NEW")
        self.assertTrue(analyse.actif)
        self.assertTrue(HistoriqueAction.objects.filter(
            utilisateur=self.admin,
            type_action="TYPE_ANALYSE_CREE",
            objet_id=analyse.pk,
        ).exists())

        edit_response = self.client.get(
            f"{reverse('laboratoire:type_update', args=[analyse.pk])}?modal=1",
        )
        self.assertContains(edit_response, 'value="CATALOG-NEW"')
        updated = self.client.post(
            f"{reverse('laboratoire:type_update', args=[analyse.pk])}?modal=1",
            {
                "code": "CATALOG-NEW",
                "nom": "Analyse catalogue modifiée",
                "description": "Description mise à jour",
                "unite": "mmol/L",
                "type_echantillon": TypeAnalyse.TypeEchantillon.URINE,
                "valeur_reference_min": "0.4",
                "valeur_reference_max": "1.4",
                "seuil_critique_bas": "0.1",
                "seuil_critique_haut": "3",
                "tarif": "14.50",
                "actif": "on",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertTrue(updated.json()["success"])
        analyse.refresh_from_db()
        self.assertEqual(analyse.nom, "Analyse catalogue modifiée")
        self.assertEqual(analyse.type_echantillon, TypeAnalyse.TypeEchantillon.URINE)
        self.assertTrue(HistoriqueAction.objects.filter(
            utilisateur=self.admin,
            type_action="TYPE_ANALYSE_MODIFIE",
            objet_id=analyse.pk,
        ).exists())
        self.client.post(reverse("laboratoire:type_toggle_active", args=[analyse.pk]))
        analyse.refresh_from_db()
        self.assertFalse(analyse.actif)
        active_catalogue = self.client.get(list_url)
        self.assertNotContains(active_catalogue, "Analyse catalogue modifiée")
        archived_catalogue = self.client.get(f"{list_url}?archives=1")
        self.assertContains(archived_catalogue, "Analyse catalogue modifiée")
        self.assertContains(archived_catalogue, "Réactiver")
        self.client.post(reverse("laboratoire:type_toggle_active", args=[analyse.pk]))
        analyse.refresh_from_db()
        self.assertTrue(analyse.actif)
        self.assertTrue(HistoriqueAction.objects.filter(
            utilisateur=self.admin,
            type_action="TYPE_ANALYSE_ARCHIVE",
            objet_id=analyse.pk,
        ).exists())
        self.assertTrue(HistoriqueAction.objects.filter(
            utilisateur=self.admin,
            type_action="TYPE_ANALYSE_REACTIVE",
            objet_id=analyse.pk,
        ).exists())

    def test_admin_can_manage_bundles_in_modals_and_archive_entries(self):
        self.client.force_login(self.admin)
        list_url = reverse("laboratoire:bilan_list")
        create_url = reverse("laboratoire:bilan_create")

        response = self.client.get(list_url)
        self.assertContains(response, "catalogue_modal.js")
        self.assertContains(response, "Créer un bilan")
        modal_response = self.client.get(f"{create_url}?modal=1")
        self.assertEqual(modal_response.status_code, 200)
        for field in ('name="nom"', 'name="description"', 'name="analyses"', 'name="actif"'):
            with self.subTest(field=field):
                self.assertContains(modal_response, field)

        invalid_response = self.client.post(
            f"{create_url}?modal=1",
            {"nom": "Bilan vide", "description": "", "analyses": [], "actif": "on"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(invalid_response.status_code, 200)
        self.assertContains(invalid_response, "Ce champ est obligatoire.")
        self.assertFalse(BilanPredefini.objects.filter(nom="Bilan vide").exists())

        created = self.client.post(
            f"{create_url}?modal=1",
            {
                "nom": "Bilan catalogue",
                "description": "Bilan de contrôle",
                "analyses": [self.analyse_sang.pk],
                "actif": "on",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(created.status_code, 200)
        self.assertTrue(created.json()["success"])
        bilan = BilanPredefini.objects.get(nom="Bilan catalogue")
        self.assertTrue(bilan.actif)
        self.assertEqual(list(bilan.analyses.all()), [self.analyse_sang])
        self.assertContains(self.client.get(list_url), "data-confirm-archive")
        edit_response = self.client.get(
            f"{reverse('laboratoire:bilan_update', args=[bilan.pk])}?modal=1",
        )
        self.assertContains(edit_response, "Bilan catalogue")
        updated = self.client.post(
            f"{reverse('laboratoire:bilan_update', args=[bilan.pk])}?modal=1",
            {
                "nom": "Bilan catalogue modifié",
                "description": "Description actualisée",
                "analyses": [self.analyse_sang.pk],
                "actif": "on",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertTrue(updated.json()["success"])
        bilan.refresh_from_db()
        self.assertEqual(bilan.description, "Description actualisée")
        updated_audit = HistoriqueAction.objects.get(
            utilisateur=self.admin,
            type_action="BILAN_MODIFIE",
            objet_id=bilan.pk,
        )
        self.assertEqual(
            updated_audit.details["apres"]["description"],
            "Description actualisée",
        )
        inactive_analysis = TypeAnalyse.objects.create(
            code="BILAN-ARCHIVE",
            nom="Analyse archivée",
            actif=False,
        )
        bilan.analyses.add(inactive_analysis)
        invalid_reactivation = self.client.post(
            f"{reverse('laboratoire:bilan_update', args=[bilan.pk])}?modal=1",
            {
                "nom": "Bilan catalogue modifié",
                "description": "Description actualisée",
                "analyses": [inactive_analysis.pk],
                "actif": "on",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(invalid_reactivation.status_code, 200)
        self.assertContains(
            invalid_reactivation,
            "Un bilan actif doit contenir au moins une analyse active.",
        )
        bilan.refresh_from_db()
        self.assertTrue(bilan.actif)
        self.assertEqual(bilan.analyses.count(), 2)

        self.client.post(reverse("laboratoire:bilan_toggle_active", args=[bilan.pk]))
        bilan.refresh_from_db()
        self.assertFalse(bilan.actif)
        self.assertNotContains(self.client.get(list_url), bilan.nom)
        self.assertContains(
            self.client.get(f"{list_url}?archives=1"),
            bilan.nom,
        )
        self.client.post(reverse("laboratoire:bilan_toggle_active", args=[bilan.pk]))
        bilan.refresh_from_db()
        self.assertTrue(bilan.actif)
        self.assertTrue(HistoriqueAction.objects.filter(
            utilisateur=self.admin,
            type_action="BILAN_ARCHIVE",
            objet_id=bilan.pk,
        ).exists())
        self.assertTrue(HistoriqueAction.objects.filter(
            utilisateur=self.admin,
            type_action="BILAN_REACTIVE",
            objet_id=bilan.pk,
        ).exists())

    def test_results_form_saves_private_draft_then_publishes_only_after_validation(self):
        prelevement = creer_prelevements(self.demande, self.doctor)[0]
        prelevement = self.faire_avancer(prelevement)
        second_type = TypeAnalyse.objects.create(
            code="UREA-DRAFT",
            nom="Urée",
            unite="mmol/L",
            valeur_reference_min=Decimal("2.500"),
            valeur_reference_max=Decimal("7.800"),
        )
        second_analysis = AnalyseDemandee.objects.create(
            demande=self.demande,
            type_analyse=second_type,
            prelevement=prelevement,
        )
        url = reverse("laboratoire:prelevement_resultats", args=[prelevement.pk])
        self.client.force_login(self.lab)
        analysis = self.demande.analyses.get(type_analyse=self.analyse_sang)

        empty_draft = self.client.post(url, {
            "action": "brouillon",
            f"valeur_{analysis.pk}": "",
            f"valeur_{second_analysis.pk}": "",
        })
        self.assertEqual(empty_draft.status_code, 200)
        self.assertContains(empty_draft, "Saisissez au moins une valeur")
        self.assertFalse(Resultat.objects.exists())

        draft_response = self.client.post(url, {
            "action": "brouillon",
            f"valeur_{analysis.pk}": "0.91",
            f"unite_{analysis.pk}": "g/L",
            f"valeur_reference_{analysis.pk}": "0.70 – 1.10 g/L",
            f"observation_{analysis.pk}": "Contrôle technique",
            f"valeur_{second_analysis.pk}": "",
            f"unite_{second_analysis.pk}": "mmol/L",
            f"valeur_reference_{second_analysis.pk}": "2.5 – 7.8 mmol/L",
            f"observation_{second_analysis.pk}": "",
        })
        self.assertRedirects(draft_response, url)
        draft = Resultat.objects.get(analyse_demandee=analysis)
        self.assertEqual(draft.statut, Resultat.Statut.EN_SAISIE)
        self.assertIsNone(draft.date_validation)
        self.assertIsNone(draft.valide_par)
        incomplete_draft = Resultat.objects.get(analyse_demandee=second_analysis)
        self.assertEqual(incomplete_draft.valeur, "")
        self.assertEqual(incomplete_draft.statut, Resultat.Statut.EN_SAISIE)
        self.assertFalse(resultats_visibles(self.patient).exists())
        draft_form_response = self.client.get(url)
        self.assertContains(draft_form_response, 'value="0.91"')
        self.assertContains(draft_form_response, "Contrôle technique")

        update_draft_response = self.client.post(url, {
            "action": "brouillon",
            f"valeur_{analysis.pk}": "0.95",
            f"unite_{analysis.pk}": "g/L",
            f"valeur_reference_{analysis.pk}": "0.70 – 1.10 g/L",
            f"observation_{analysis.pk}": "Valeur corrigée",
            f"valeur_{second_analysis.pk}": "",
            f"unite_{second_analysis.pk}": "mmol/L",
            f"valeur_reference_{second_analysis.pk}": "2.5 – 7.8 mmol/L",
            f"observation_{second_analysis.pk}": "",
        })
        self.assertRedirects(update_draft_response, url)
        draft.refresh_from_db()
        self.assertEqual(draft.valeur, "0.95")
        self.assertEqual(draft.observation, "Valeur corrigée")
        self.assertEqual(
            Resultat.objects.filter(analyse_demandee=analysis).count(),
            1,
        )

        incomplete_publish = self.client.post(url, {
            "action": "valider",
            f"valeur_{analysis.pk}": "0.95",
            f"valeur_{second_analysis.pk}": "",
        })
        self.assertEqual(incomplete_publish.status_code, 200)
        self.assertContains(incomplete_publish, "obligatoire")
        draft.refresh_from_db()
        self.assertEqual(draft.statut, Resultat.Statut.EN_SAISIE)

        invalid_numeric_publish = self.client.post(url, {
            "action": "valider",
            f"valeur_{analysis.pk}": "1.2.3",
            f"unite_{analysis.pk}": "g/L",
            f"valeur_reference_{analysis.pk}": "0.70 – 1.10 g/L",
            f"valeur_{second_analysis.pk}": "4.2",
            f"unite_{second_analysis.pk}": "mmol/L",
        })
        self.assertEqual(invalid_numeric_publish.status_code, 200)
        self.assertContains(invalid_numeric_publish, "Saisissez un nombre valide")
        draft.refresh_from_db()
        self.assertEqual(draft.statut, Resultat.Statut.EN_SAISIE)

        invalid_unit_publish = self.client.post(url, {
            "action": "valider",
            f"valeur_{analysis.pk}": "0.95",
            f"unite_{analysis.pk}": "mmol/L",
            f"valeur_reference_{analysis.pk}": "0.70 – 1.10 g/L",
            f"valeur_{second_analysis.pk}": "4.2",
            f"unite_{second_analysis.pk}": "mmol/L",
        })
        self.assertEqual(invalid_unit_publish.status_code, 200)
        self.assertContains(
            invalid_unit_publish,
            "L’unité doit correspondre au catalogue",
        )
        draft.refresh_from_db()
        self.assertEqual(draft.statut, Resultat.Statut.EN_SAISIE)

        publish_response = self.client.post(url, {
            "action": "valider",
            f"valeur_{analysis.pk}": "0.95",
            f"unite_{analysis.pk}": "g/L",
            f"valeur_reference_{analysis.pk}": "0.70 – 1.10 g/L",
            f"observation_{analysis.pk}": "Valeur corrigée",
            f"commentaire_patient_{analysis.pk}": "Résultat à revoir lors de votre prochain rendez-vous.",
            f"valeur_{second_analysis.pk}": "4.2",
            f"unite_{second_analysis.pk}": "mmol/L",
            f"valeur_reference_{second_analysis.pk}": "2.5 – 7.8 mmol/L",
            f"observation_{second_analysis.pk}": "",
        })
        self.assertRedirects(
            publish_response,
            f"{reverse('laboratoire:prelevement_list')}?onglet=clotures&statut=TERMINE",
            fetch_redirect_response=False,
        )
        draft.refresh_from_db()
        prelevement.refresh_from_db()
        self.assertEqual(draft.statut, Resultat.Statut.VALIDE)
        self.assertEqual(draft.commentaire_interne, "Valeur corrigée")
        self.assertEqual(
            draft.commentaire_patient,
            "Résultat à revoir lors de votre prochain rendez-vous.",
        )
        self.assertIsNotNone(draft.date_validation)
        self.assertEqual(draft.valide_par, self.lab)
        self.assertEqual(prelevement.statut, Prelevement.Statut.TERMINE)
        self.assertEqual(self.demande.analyses.count(), 2)
        self.assertEqual(Resultat.objects.filter(analyse_demandee=analysis).count(), 1)
        completed_list = self.client.get(publish_response.url)
        self.assertContains(completed_list, "Les résultats ont été validés et publiés.")
        self.assertContains(completed_list, prelevement.code_prelevement)
        self.client.force_login(self.doctor)
        detail_response = self.client.get(
            reverse("laboratoire:demande_detail", args=[self.demande.pk]),
        )
        self.assertContains(detail_response, "0.95")
        self.assertContains(detail_response, "Validé")

    def test_only_laboratory_can_publish_a_saved_result(self):
        prelevement = creer_prelevements(self.demande, self.doctor)[0]
        prelevement = self.faire_avancer(prelevement)
        analysis = self.demande.analyses.get()
        from .services import enregistrer_resultats_brouillon

        draft = enregistrer_resultats_brouillon(
            resultats={analysis: {"valeur": "0.92"}},
            utilisateur=self.lab,
            prelevement=prelevement,
        )[0]
        validate_url = reverse("laboratoire:resultat_validate", args=[draft.pk])

        self.client.force_login(self.doctor)
        self.assertEqual(self.client.post(validate_url).status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.statut, Resultat.Statut.EN_SAISIE)

        self.client.force_login(self.lab)
        response = self.client.post(validate_url)
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.statut, Resultat.Statut.VALIDE)
        self.assertEqual(draft.valide_par, self.lab)
    def test_list_prioritizes_urgent_samples_and_filters_by_code_status_and_dates(self):
        urgent_type = TypeAnalyse.objects.create(
            code="URG-WF",
            nom="Analyse urgente",
        )
        urgent = self.creer_demande(
            [urgent_type],
            priorite=DemandeAnalyse.Priorite.URGENTE,
            commentaire="Motif médical urgent",
        )
        normal_sample = creer_prelevements(self.demande, self.doctor)[0]
        urgent_sample = creer_prelevements(urgent, self.doctor)[0]

        self.client.force_login(self.lab)
        response = self.client.get(reverse("laboratoire:prelevement_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["prelevements"]),
            [urgent_sample, normal_sample],
        )
        response = self.client.get(reverse("laboratoire:prelevement_list"), {
            "onglet": "a_traiter",
            "q": normal_sample.code_prelevement,
            "statut": Prelevement.Statut.A_EFFECTUER,
            "date_debut": timezone.localdate().isoformat(),
            "date_fin": timezone.localdate().isoformat(),
        })
        self.assertEqual(list(response.context["prelevements"]), [normal_sample])

    def test_three_sample_tabs_filter_workflow_statuses(self):
        pending_sample = creer_prelevements(self.demande, self.doctor)[0]

        received_demand = self.creer_demande([self.analyse_sang])
        received_sample = self.faire_avancer(
            creer_prelevements(received_demand, self.doctor)[0],
        )

        completed_type = TypeAnalyse.objects.create(
            code="COMPLETE-TAB",
            nom="Analyse terminée",
            unite="g/L",
        )
        completed_demand = self.creer_demande([completed_type])
        completed_sample = self.faire_avancer(
            creer_prelevements(completed_demand, self.doctor)[0],
        )
        envoyer_resultats(
            utilisateur=self.lab,
            prelevement=completed_sample,
            resultats={
                completed_demand.analyses.get(): {
                    "valeur": "0.95",
                    "unite": "g/L",
                },
            },
        )

        self.client.force_login(self.lab)
        list_url = reverse("laboratoire:prelevement_list")
        expected_groups = {
            "a_traiter": {pending_sample.pk},
            "resultats": {received_sample.pk},
            "clotures": {completed_sample.pk},
        }
        for tab, expected_ids in expected_groups.items():
            with self.subTest(tab=tab):
                response = self.client.get(list_url, {"onglet": tab})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    {item.pk for item in response.context["prelevements"]},
                    expected_ids,
                )
        closed_response = self.client.get(
            list_url,
            {"onglet": "clotures", "statut": Prelevement.Statut.REJETE},
        )
        self.assertEqual(
            set(closed_response.context["statut_choices"]),
            {
                (Prelevement.Statut.TERMINE, "Terminé"),
                (Prelevement.Statut.REJETE, "Refusé"),
                (Prelevement.Statut.ANNULE, "Annulé"),
            },
        )

    def test_laboratory_uses_three_sample_lists_and_result_entry_stays_in_workflow(self):
        sample = creer_prelevements(self.demande, self.doctor)[0]
        self.client.force_login(self.lab)
        request_list_response = self.client.get(
            reverse("laboratoire:demande_list"),
        )
        self.assertRedirects(
            request_list_response,
            reverse("laboratoire:prelevement_list"),
            fetch_redirect_response=False,
        )
        sample_list = self.client.get(reverse("laboratoire:prelevement_list"))
        self.assertEqual(sample_list.status_code, 200)
        self.assertContains(
            sample_list,
            f'href="{reverse("laboratoire:prelevement_list")}" class="nav-item-link" id="nav-laboratoire"',
        )
        self.assertEqual(
            sample_list.context["onglets"],
            [
                ("a_traiter", "À traiter"),
                ("resultats", "Résultats à saisir"),
                ("clotures", "Clôturés"),
            ],
        )
        self.assertContains(sample_list, "Prélèvements du laboratoire")
        self.assertContains(sample_list, "À traiter")
        self.assertContains(sample_list, "Résultats à saisir")
        self.assertContains(sample_list, "Clôturés")
        self.assertNotContains(sample_list, "Tableau de bord du laboratoire")
        self.assertNotContains(sample_list, "lab-stats")
        self.assertNotContains(
            sample_list,
            reverse("laboratoire:prelevement_update", args=[sample.pk]),
        )
        self.assertNotContains(
            sample_list,
            reverse("laboratoire:demande_detail", args=[self.demande.pk]),
        )
        self.assertContains(sample_list, ">Confirmer la réception</button>")
        self.assertNotContains(sample_list, "data-reject-url=")
        self.assertNotContains(
            sample_list,
            reverse("laboratoire:prelevement_etiquette", args=[sample.pk]),
        )
        early_rejection = self.client.post(
            reverse("laboratoire:prelevement_rejeter", args=[sample.pk]),
            {"motif": "Autre", "remarque": "Échantillon non reçu"},
        )
        self.assertEqual(early_rejection.status_code, 302)
        sample.refresh_from_db()
        self.assertEqual(sample.statut, Prelevement.Statut.A_EFFECTUER)

        early_receive = self.client.post(
            reverse("laboratoire:prelevement_etape", args=[sample.pk]),
            {"etape": "RECU"},
        )
        self.assertRedirects(
            early_receive,
            f"{reverse('laboratoire:prelevement_list')}?onglet=resultats&statut=RECU",
            fetch_redirect_response=False,
        )
        sample.refresh_from_db()
        self.assertEqual(sample.statut, Prelevement.Statut.RECU)
        self.assertIsNotNone(sample.date_prelevement)
        self.assertIsNotNone(sample.date_reception)
        self.demande.refresh_from_db()
        self.assertEqual(self.demande.statut, DemandeAnalyse.Statut.EN_COURS)
        response = self.client.get(early_receive.url)
        self.assertContains(response, "réception du prélèvement est confirmée")
        self.assertContains(response, "Prélèvement reçu")
        self.assertContains(response, "Refuser")
        self.assertContains(
            response,
            reverse("laboratoire:prelevement_etiquette", args=[sample.pk]),
        )
        self.assertEqual(sample.recu_par, self.lab)
        self.assertEqual(self.demande.statut, DemandeAnalyse.Statut.EN_COURS)
        self.assertContains(response, "Saisir / reprendre les résultats")

        result_entry_response = self.client.post(
            reverse("laboratoire:prelevement_etape", args=[sample.pk]),
            {"etape": "RESULTATS"},
        )
        result_url = reverse("laboratoire:prelevement_resultats", args=[sample.pk])
        self.assertRedirects(result_entry_response, result_url, fetch_redirect_response=False)
        result_form_response = self.client.get(result_url)
        self.assertEqual(result_form_response.status_code, 200)
        self.assertContains(result_form_response, "lab-result-form")
        result_list_url = (
            f'{reverse("laboratoire:prelevement_list")}'
            '?onglet=resultats&amp;statut=RECU'
        )
        self.assertContains(result_form_response, f'href="{result_list_url}"', count=2)
        self.assertContains(result_form_response, "Retour à la liste des résultats à saisir")
        self.assertContains(result_form_response, ">Annuler</a>")
        self.assertContains(result_form_response, self.patient.username)
        self.assertContains(result_form_response, f"#{self.demande.pk}")
        self.assertContains(result_form_response, sample.code_prelevement)
        self.assertContains(result_form_response, self.analyse_sang.nom)
        self.assertContains(result_form_response, f'name="valeur_{self.demande.analyses.get().pk}"')
        self.assertNotContains(result_form_response, "Enregistrer le brouillon")
        self.assertContains(result_form_response, "Valider et publier les résultats")
        self.assertContains(result_form_response, ">Annuler</a>")
        self.assertNotContains(result_form_response, "Aide à la vérification")

    def test_rejection_redirects_to_refused_list_and_keeps_sample_visible(self):
        sample = creer_prelevements(self.demande, self.doctor)[0]
        self.faire_avancer(sample)
        self.client.force_login(self.lab)

        response = self.client.post(
            reverse("laboratoire:prelevement_rejeter", args=[sample.pk]),
            {"motif": "Autre", "remarque": "Tube endommagé"},
        )

        self.assertRedirects(
            response,
            f"{reverse('laboratoire:prelevement_list')}?onglet=clotures&statut=REJETE",
            fetch_redirect_response=False,
        )
        sample.refresh_from_db()
        self.assertEqual(sample.statut, Prelevement.Statut.REJETE)
        list_response = self.client.get(response.url)
        self.assertContains(list_response, "Le prélèvement a été refusé et tracé.")
        self.assertContains(list_response, sample.code_prelevement)
        self.assertContains(list_response, "Tube endommagé")
        self.assertTrue(HistoriqueAction.objects.filter(
            type_action="PRELEVEMENT_STATUT_MODIFIE",
            objet_id=sample.pk,
            utilisateur=self.lab,
        ).exists())

    def test_results_entry_reports_missing_analysis_link_instead_of_fake_success(self):
        sample = creer_prelevements(self.demande, self.doctor)[0]
        self.faire_avancer(sample)
        self.demande.analyses.update(prelevement=None)
        self.client.force_login(self.lab)

        response = self.client.get(
            reverse("laboratoire:prelevement_resultats", args=[sample.pk]),
        )

        self.assertRedirects(
            response,
            f"{reverse('laboratoire:prelevement_list')}?onglet=resultats&statut=RECU",
            fetch_redirect_response=False,
        )
        list_response = self.client.get(response.url)
        self.assertContains(list_response, "Aucune analyse active n’est associée")
        self.assertNotContains(list_response, "Tous les résultats de ce prélèvement sont déjà validés")
        self.assertFalse(Resultat.objects.exists())

    def test_request_list_analysis_count_excludes_withdrawn_analyses(self):
        withdrawn_analysis = TypeAnalyse.objects.create(
            code="WITHDRAWN-WF",
            nom="Analyse retirée",
        )
        AnalyseDemandee.objects.create(
            demande=self.demande,
            type_analyse=withdrawn_analysis,
            statut=AnalyseDemandee.Statut.ANNULEE,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("laboratoire:demande_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["demandes"].get().nombre_analyses, 1)
        self.assertContains(response, "Glycémie")
        self.assertNotContains(response, "Analyse retirée")

    def test_rejection_modal_opens_for_an_authorized_sample(self):
        sample = creer_prelevements(self.demande, self.doctor)[0]
        self.faire_avancer(sample)
        self.client.force_login(self.lab)

        response = self.client.get(
            reverse("laboratoire:prelevement_list"),
            {"onglet": "resultats", "refuser": sample.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["refuser_prelevement"], sample)
        self.assertContains(response, 'id="reject-dialog"')
        self.assertContains(response, "Confirmer le refus")

    def test_descriptive_summary_uses_published_results_and_hides_patient_identity(self):
        low_type = TypeAnalyse.objects.create(
            code="SUMMARY-LOW",
            nom="Analyse basse",
            unite="mg/L",
            valeur_reference_min=Decimal("10"),
            valeur_reference_max=Decimal("20"),
        )
        high_type = TypeAnalyse.objects.create(
            code="SUMMARY-HIGH",
            nom="Analyse élevée",
            unite="mg/L",
            valeur_reference_min=Decimal("10"),
            valeur_reference_max=Decimal("20"),
        )
        draft_type = TypeAnalyse.objects.create(
            code="SUMMARY-DRAFT",
            nom="Analyse non publiée",
        )
        low_analysis = AnalyseDemandee.objects.create(
            demande=self.demande,
            type_analyse=low_type,
        )
        high_analysis = AnalyseDemandee.objects.create(
            demande=self.demande,
            type_analyse=high_type,
        )
        draft_analysis = AnalyseDemandee.objects.create(
            demande=self.demande,
            type_analyse=draft_type,
        )
        sample = creer_prelevements(self.demande, self.doctor)[0]
        sample = self.faire_avancer(sample)
        Resultat.objects.create(
            analyse_demandee=draft_analysis,
            prelevement=sample,
            valeur="123",
            saisi_par=self.lab,
            statut=Resultat.Statut.EN_SAISIE,
        )
        envoyer_resultats(
            utilisateur=self.lab,
            prelevement=sample,
            resultats={
                self.demande.analyses.get(type_analyse=self.analyse_sang): {
                    "valeur": "0.95",
                    "unite": "g/L",
                },
                low_analysis: {"valeur": "9", "unite": "mg/L"},
                high_analysis: {"valeur": "21", "unite": "mg/L"},
            },
        )

        previous_demand = self.creer_demande([self.analyse_sang])
        previous_sample = creer_prelevements(previous_demand, self.doctor)[0]
        previous_sample = self.faire_avancer(previous_sample)
        envoyer_resultats(
            utilisateur=self.lab,
            prelevement=previous_sample,
            resultats={
                previous_demand.analyses.get(): {
                    "valeur": "4.8",
                    "unite": "mmol/L",
                },
            },
        )
        Resultat.objects.filter(
            analyse_demandee=previous_demand.analyses.get(),
        ).update(date_validation=timezone.now() - timedelta(days=1))

        lignes = preparer_donnees(self.demande)
        by_name = {ligne["analyse"]: ligne for ligne in lignes}
        self.assertEqual(by_name["Glycémie"]["statut"], "normal")
        self.assertEqual(by_name["Analyse basse"]["statut"], "bas")
        self.assertEqual(by_name["Analyse élevée"]["statut"], "élevé")
        self.assertEqual(
            by_name["Glycémie"]["evolution"],
            "Aucun résultat précédent comparable",
        )
        self.assertNotIn("Analyse non publiée", by_name)
        self.assertNotIn(self.patient.username, str(lignes))
        self.assertNotIn("patient_id", str(lignes))

    def test_evolution_uses_latest_prior_compatible_unit_and_calculates_trend(self):
        current_sample = self.faire_avancer(
            creer_prelevements(self.demande, self.doctor)[0],
        )
        envoyer_resultats(
            utilisateur=self.lab,
            prelevement=current_sample,
            resultats={
                self.demande.analyses.get(): {
                    "valeur": "0.95",
                    "unite": "g/L",
                },
            },
        )
        older_demand = self.creer_demande([self.analyse_sang])
        older_sample = self.faire_avancer(
            creer_prelevements(older_demand, self.doctor)[0],
        )
        envoyer_resultats(
            utilisateur=self.lab,
            prelevement=older_sample,
            resultats={
                older_demand.analyses.get(): {
                    "valeur": "0.90",
                    "unite": "g/L",
                },
            },
        )
        Resultat.objects.filter(
            analyse_demandee__demande=older_demand,
        ).update(date_validation=timezone.now() - timedelta(days=2))

        incompatible_demand = self.creer_demande([self.analyse_sang])
        incompatible_sample = self.faire_avancer(
            creer_prelevements(incompatible_demand, self.doctor)[0],
        )
        envoyer_resultats(
            utilisateur=self.lab,
            prelevement=incompatible_sample,
            resultats={
                incompatible_demand.analyses.get(): {
                    "valeur": "4.8",
                    "unite": "mmol/L",
                },
            },
        )
        Resultat.objects.filter(
            analyse_demandee__demande=incompatible_demand,
        ).update(date_validation=timezone.now() - timedelta(days=1))

        line = preparer_donnees(self.demande)[0]

        self.assertEqual(line["valeur_precedente"], "0.90")
        self.assertEqual(line["unite_precedente"], "g/L")
        self.assertIsNotNone(line["date_precedente"])
        self.assertEqual(line["variation_pct"], "5.56")
        self.assertEqual(line["tendance"], "en hausse")
        self.assertIn("5.56%", line["evolution"])
        self.assertEqual(len(line["historique"]), 2)

    def test_previous_zero_and_inconsistent_references_do_not_create_a_trend(self):
        current_sample = self.faire_avancer(
            creer_prelevements(self.demande, self.doctor)[0],
        )
        envoyer_resultats(
            utilisateur=self.lab,
            prelevement=current_sample,
            resultats={
                self.demande.analyses.get(): {
                    "valeur": "0.95",
                    "unite": "g/L",
                },
            },
        )
        previous_demand = self.creer_demande([self.analyse_sang])
        previous_sample = self.faire_avancer(
            creer_prelevements(previous_demand, self.doctor)[0],
        )
        Resultat.objects.create(
            analyse_demandee=previous_demand.analyses.get(),
            prelevement=previous_sample,
            valeur="0",
            unite="g/L",
            saisi_par=self.lab,
            valide_par=self.lab,
            statut=Resultat.Statut.VALIDE,
            date_validation=timezone.now() - timedelta(days=1),
        )

        line = preparer_donnees(self.demande)[0]

        self.assertEqual(line["tendance"], "insuffisante")
        self.assertIsNone(line["variation_pct"])
        self.assertIn("valeur précédente nulle", line["evolution"])

        TypeAnalyse.objects.filter(pk=self.analyse_sang.pk).update(
            valeur_reference_min=Decimal("2"),
            valeur_reference_max=Decimal("1"),
        )
        incoherent_line = preparer_donnees(self.demande)[0]
        self.assertFalse(incoherent_line["donnee_coherente"])
        self.assertEqual(incoherent_line["tendance"], "insuffisante")
        self.assertIsNone(incoherent_line["variation_pct"])
        self.assertEqual(incoherent_line["statut"], "non déterminé")

    def test_result_submission_rejects_nonpositive_numeric_values(self):
        sample = self.faire_avancer(
            creer_prelevements(self.demande, self.doctor)[0],
        )
        analysis = self.demande.analyses.get()

        for value in ("0", "-35.6"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValidationError,
                    "strictement supérieur à zéro",
                ):
                    envoyer_resultats(
                        utilisateur=self.lab,
                        prelevement=sample,
                        resultats={
                            analysis: {
                                "valeur": value,
                                "unite": "g/L",
                            },
                        },
                    )

        self.assertFalse(Resultat.objects.filter(
            analyse_demandee=analysis,
        ).exists())

    @override_settings(
        GOOGLE_API_KEY="test-google-api-key",
        GEMINI_MODEL="gemini-test",
        ANTHROPIC_API_KEY="",
    )
    @patch(
        "laboratoire.services_resume._appeler_gemini",
        return_value="Résumé descriptif fictif, non médical.",
    )
    def test_result_unit_mismatch_is_not_compared_to_configured_references(
        self,
        mock_gemini,
    ):
        sample = self.faire_avancer(
            creer_prelevements(self.demande, self.doctor)[0],
        )
        envoyer_resultats(
            utilisateur=self.lab,
            prelevement=sample,
            resultats={
                self.demande.analyses.get(): {
                    "valeur": "4.8",
                    "unite": "mmol/L",
                },
            },
        )

        line = preparer_donnees(self.demande)[0]

        self.assertEqual(line["statut"], "non déterminé")
        self.assertIn("unité du résultat différente", line["reference"])
        self.assertFalse(line["donnee_coherente"])
        from .services_resume import _donnees_pseudonymisees

        row = _donnees_pseudonymisees([line])[0]
        self.assertEqual(row["statut"], "non déterminé")
        self.assertEqual(row["valeur_precedente"], "")
        self.assertEqual(
            row["evolution"],
            "Comparaison non calculée : données à vérifier",
        )
        generated = generer_resume([line])
        self.assertEqual(
            generated.texte,
            "Résumé descriptif fictif, non médical.",
        )
        mock_gemini.assert_called_once_with([line], model="gemini-test")

    @override_settings(
        GOOGLE_API_KEY="test-google-api-key",
        GEMINI_MODEL="gemini-primary-test",
        GEMINI_FALLBACK_MODEL="gemini-fallback-test",
        ANTHROPIC_API_KEY="",
    )
    @patch("laboratoire.services_resume.urlopen")
    def test_gemini_503_retries_with_configured_fallback_model(self, mock_urlopen):
        mock_urlopen.side_effect = [
            HTTPError(
                "https://generativelanguage.googleapis.com/v1beta/interactions",
                503,
                "service unavailable",
                {},
                BytesIO(b'{"error":{"code":"service_unavailable"}}'),
            ),
            BytesIO(json.dumps({
                "status": "completed",
                "steps": [{
                    "type": "model_output",
                    "content": [{
                        "type": "text",
                        "text": "Résumé descriptif fictif.",
                    }],
                }],
            }).encode("utf-8")),
        ]

        with self.assertLogs(
            "laboratoire.services_resume",
            level="WARNING",
        ) as captured:
            result = generer_resume([{
                "analyse": "Glycémie",
                "valeur": "0.95",
                "unite": "g/L",
            }])

        sent_models = [
            json.loads(call.args[0].data.decode("utf-8"))["model"]
            for call in mock_urlopen.call_args_list
        ]
        self.assertEqual(
            sent_models,
            ["gemini-primary-test", "gemini-fallback-test"],
        )
        self.assertEqual(result.texte, "Résumé descriptif fictif.")
        self.assertEqual(result.modele, "gemini-fallback-test")
        self.assertIn("repli=gemini-fallback-test", captured.output[0])
        self.client.force_login(self.doctor)
        page = self.client.get(
            reverse("laboratoire:compte_rendu", args=[self.demande.pk]),
        )
        self.assertNotContains(page, "Courbe d’évolution")
        self.assertNotContains(page, "lab-evolution-charts")

    @override_settings(
        GOOGLE_API_KEY="test-google-api-key",
        GEMINI_MODEL="gemini-primary-test",
        GEMINI_FALLBACK_MODEL="gemini-fallback-test",
        ANTHROPIC_API_KEY="",
    )
    @patch("laboratoire.services_resume.urlopen")
    def test_gemini_timeout_retries_with_configured_fallback_model(
        self,
        mock_urlopen,
    ):
        mock_urlopen.side_effect = [
            URLError(socket.timeout("timed out")),
            BytesIO(json.dumps({
                "status": "completed",
                "steps": [{
                    "type": "model_output",
                    "content": [{
                        "type": "text",
                        "text": "Résumé descriptif fictif.",
                    }],
                }],
            }).encode("utf-8")),
        ]

        with self.assertLogs(
            "laboratoire.services_resume",
            level="WARNING",
        ) as captured:
            result = generer_resume([{
                "analyse": "Glycémie",
                "valeur": "0.95",
                "unite": "g/L",
            }])

        sent_models = [
            json.loads(call.args[0].data.decode("utf-8"))["model"]
            for call in mock_urlopen.call_args_list
        ]
        self.assertEqual(
            sent_models,
            ["gemini-primary-test", "gemini-fallback-test"],
        )
        self.assertEqual(result.texte, "Résumé descriptif fictif.")
        self.assertEqual(result.modele, "gemini-fallback-test")
        self.assertIn("cause=timeout", captured.output[0])

    @override_settings(
        GOOGLE_API_KEY="test-google-api-key",
        GEMINI_MODEL="gemini-primary-test",
        GEMINI_FALLBACK_MODEL="gemini-fallback-test",
        ANTHROPIC_API_KEY="",
    )
    @patch(
        "laboratoire.services_resume.urlopen",
        side_effect=[
            URLError(socket.timeout("timed out")),
            URLError(socket.timeout("timed out")),
        ],
    )
    def test_summary_timeout_is_reported_without_saving_a_report(
        self,
        mock_urlopen,
    ):
        sample = self.faire_avancer(
            creer_prelevements(self.demande, self.doctor)[0],
        )
        envoyer_resultats(
            utilisateur=self.lab,
            prelevement=sample,
            resultats={
                self.demande.analyses.get(): {
                    "valeur": "0.95",
                    "unite": "g/L",
                },
            },
        )
        self.client.force_login(self.doctor)

        response = self.client.post(
            reverse("laboratoire:generer_resume", args=[self.demande.pk]),
            follow=True,
        )

        self.assertContains(response, "Le fournisseur IA n’a pas répondu")
        self.assertContains(response, "Aucun résumé n’a été enregistré")
        self.assertFalse(CompteRendu.objects.filter(
            demande=self.demande,
        ).exists())
        self.assertEqual(mock_urlopen.call_count, 2)

    @override_settings(
        ANTHROPIC_API_KEY="summary-workflow-test-key",
        IA_MODELE="summary-workflow-test",
    )
    @patch(
        "laboratoire.services_resume._appeler_anthropic",
        return_value="Résumé IA : glycémie publiée à 0,95 g/L.",
    )
    def test_ai_summary_comparison_approval_and_permissions(self, mock_ai):
        sample = creer_prelevements(self.demande, self.doctor)[0]
        sample = self.faire_avancer(sample)
        envoyer_resultats(
            utilisateur=self.lab,
            prelevement=sample,
            resultats={
                self.demande.analyses.get(): {
                    "valeur": "0.95",
                    "unite": "g/L",
                },
            },
        )
        generate_url = reverse("laboratoire:generer_resume", args=[self.demande.pk])
        report_url = reverse("laboratoire:compte_rendu", args=[self.demande.pk])
        self.client.force_login(self.doctor)
        doctor_dashboard = self.client.get(reverse("doctor_dashboard"))
        self.assertEqual(doctor_dashboard.status_code, 200)
        self.assertContains(doctor_dashboard, "SmartResult — résumés descriptifs")
        self.assertContains(doctor_dashboard, f'href="{report_url}"')
        self.assertContains(doctor_dashboard, "Comparer les résultats")
        self.assertContains(
            doctor_dashboard,
            "l’IA prépare un résumé descriptif",
        )
        detail_page = self.client.get(
            reverse("laboratoire:demande_detail", args=[self.demande.pk]),
        )
        self.assertContains(detail_page, "Comparer les résultats")
        self.assertContains(detail_page, "lab-ai-note")
        self.assertContains(detail_page, "données pseudonymisées")
        doctor_request_list = self.client.get(
            reverse("laboratoire:demande_list"),
        )
        self.assertContains(doctor_request_list, f'href="{report_url}"')
        self.assertContains(
            doctor_request_list,
            "Comparez les résultats publiés et leur historique",
        )
        comparison_page = self.client.get(report_url)
        self.assertEqual(comparison_page.status_code, 200)
        self.assertContains(comparison_page, "Votre comparaison avec l’historique")
        self.assertContains(
            comparison_page,
            "Générer le résumé IA de cette comparaison",
        )
        self.assertRedirects(
            self.client.post(generate_url),
            report_url,
        )
        report = CompteRendu.objects.get(demande=self.demande)
        self.assertEqual(report.source, CompteRendu.Source.IA)
        self.assertEqual(report.statut, CompteRendu.Statut.BROUILLON)
        report_page = self.client.get(report_url)
        self.assertEqual(report_page.status_code, 200)
        self.assertContains(report_page, "Votre comparaison avec l’historique")
        self.assertContains(report_page, "Glycémie")
        self.assertContains(report_page, "Résumé IA à vérifier")
        self.assertContains(report_page, "Approuver le résumé IA")
        self.assertNotContains(report_page, 'name="texte_final"')
        self.assertNotContains(report_page, "Analyser l’évolution avec l’IA")
        mock_ai.assert_called_once()
        self.assertTrue(HistoriqueAction.objects.filter(
            utilisateur=self.doctor,
            type_action="COMPTE_RENDU_GENERE",
            objet_id=report.pk,
        ).exists())

        other_doctor = User.objects.create_user(
            username="summary-other-doctor",
            password="test-password-123",
            role=User.Role.DOCTEUR,
        )
        for user in (other_doctor, self.patient, self.lab, self.admin):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                self.assertEqual(self.client.get(report_url).status_code, 403)
                self.assertEqual(self.client.post(generate_url).status_code, 403)

        self.client.force_login(self.doctor)
        approval = self.client.post(report_url, {
            "action": "approuver",
            "texte_final": "Texte arbitraire envoyé par le navigateur.",
        })
        self.assertRedirects(approval, report_url)
        report.refresh_from_db()
        self.assertEqual(report.statut, CompteRendu.Statut.APPROUVE)
        self.assertEqual(
            report.texte_final,
            "Résumé IA : glycémie publiée à 0,95 g/L.",
        )
        self.assertIsNotNone(report.approuve_le)
        approved_page = self.client.get(report_url)
        self.assertContains(approved_page, "Résumé approuvé")
        self.assertContains(
            approved_page,
            "Résumé IA : glycémie publiée à 0,95 g/L.",
        )
        self.assertNotContains(approved_page, 'name="texte_final"')
        self.assertTrue(HistoriqueAction.objects.filter(
            utilisateur=self.doctor,
            type_action="COMPTE_RENDU_APPROUVE",
            objet_id=report.pk,
        ).exists())

        self.client.post(report_url, {
            "action": "brouillon",
            "texte_final": "Texte modifié après approbation",
        })
        report.refresh_from_db()
        self.assertNotEqual(
            report.texte_final,
            "Texte modifié après approbation",
        )

    @override_settings(
        ANTHROPIC_API_KEY="test-api-key",
        IA_MODELE="test-model",
    )
    @patch(
        "laboratoire.services_resume._appeler_anthropic",
        return_value="Glycémie : 0,95 g/L, dans les références fournies.",
    )
    def test_ai_summary_is_saved_with_ai_source_and_requires_doctor_review(
        self,
        mock_ai,
    ):
        sample = self.faire_avancer(
            creer_prelevements(self.demande, self.doctor)[0],
        )
        envoyer_resultats(
            utilisateur=self.lab,
            prelevement=sample,
            resultats={
                self.demande.analyses.get(): {
                    "valeur": "0.95",
                    "unite": "g/L",
                },
            },
        )
        self.client.force_login(self.doctor)
        response = self.client.post(
            reverse("laboratoire:generer_resume", args=[self.demande.pk]),
        )

        self.assertRedirects(
            response,
            reverse("laboratoire:compte_rendu", args=[self.demande.pk]),
        )
        report = CompteRendu.objects.get(demande=self.demande)
        self.assertEqual(report.source, CompteRendu.Source.IA)
        self.assertEqual(report.statut, CompteRendu.Statut.BROUILLON)
        self.assertEqual(
            report.texte_final,
            "Glycémie : 0,95 g/L, dans les références fournies.",
        )
        self.assertContains(
            self.client.get(
                reverse("laboratoire:compte_rendu", args=[self.demande.pk]),
            ),
            "Généré par IA",
        )
        self.assertContains(
            self.client.get(
                reverse("laboratoire:compte_rendu", args=[self.demande.pk]),
            ),
            "lab-badge--ai",
        )
        mock_ai.assert_called_once()

    @override_settings(
        GOOGLE_API_KEY="test-google-api-key",
        GEMINI_MODEL="gemini-test",
        ANTHROPIC_API_KEY="",
    )
    @patch(
        "laboratoire.services_resume._appeler_gemini",
        return_value="Résumé descriptif généré par Gemini.",
    )
    def test_legacy_summary_can_be_replaced_from_comparison_page(self, mock_gemini):
        sample = self.faire_avancer(
            creer_prelevements(self.demande, self.doctor)[0],
        )
        envoyer_resultats(
            utilisateur=self.lab,
            prelevement=sample,
            resultats={
                self.demande.analyses.get(): {
                    "valeur": "0.95",
                    "unite": "g/L",
                },
            },
        )
        CompteRendu.objects.create(
            demande=self.demande,
            medecin=self.doctor,
            texte_genere="Ancien texte issu des règles.",
            texte_final="Ancien texte issu des règles.",
            source=CompteRendu.Source.REGLES,
        )
        self.client.force_login(self.doctor)
        comparison_url = reverse(
            "laboratoire:compte_rendu",
            args=[self.demande.pk],
        )
        page = self.client.get(comparison_url)
        self.assertContains(page, "Générer le résumé IA maintenant")
        self.assertContains(
            page,
            reverse("laboratoire:generer_resume", args=[self.demande.pk]),
        )

        response = self.client.post(
            reverse("laboratoire:generer_resume", args=[self.demande.pk]),
            follow=True,
        )

        self.assertContains(response, "Résumé descriptif généré par Gemini.")
        self.assertContains(response, "Généré par IA")
        self.assertNotContains(response, "Ancien texte issu des règles.")
        report = CompteRendu.objects.get(demande=self.demande)
        self.assertEqual(report.source, CompteRendu.Source.IA)
        self.assertEqual(
            report.texte_final,
            "Résumé descriptif généré par Gemini.",
        )
        mock_gemini.assert_called_once()

    @override_settings(
        GOOGLE_API_KEY="",
        GEMINI_API_KEY="",
        ANTHROPIC_API_KEY="",
    )
    def test_legacy_rule_summary_is_hidden_until_an_ai_summary_is_generated(self):
        legacy_text = "Résumé automatique ancien à ne pas présenter comme IA."
        CompteRendu.objects.create(
            demande=self.demande,
            medecin=self.doctor,
            texte_genere=legacy_text,
            texte_final=legacy_text,
            source=CompteRendu.Source.REGLES,
        )
        self.client.force_login(self.doctor)

        response = self.client.get(
            reverse("laboratoire:compte_rendu", args=[self.demande.pk]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ancienne version (non IA)")
        self.assertContains(response, "Aucun résumé IA n’a encore été généré")
        self.assertContains(response, "GOOGLE_API_KEY")
        self.assertContains(response, "GEMINI_MODEL=gemini-3.8-flash")
        self.assertNotContains(response, legacy_text)
        self.assertNotContains(response, "Ancien brouillon masqué")
        self.assertNotContains(response, "Résumé automatique (règles)")

    @override_settings(
        GOOGLE_API_KEY="",
        GEMINI_API_KEY="",
        ANTHROPIC_API_KEY="",
    )
    def test_summary_generation_without_ai_provider_does_not_save_a_report(self):
        sample = self.faire_avancer(
            creer_prelevements(self.demande, self.doctor)[0],
        )
        envoyer_resultats(
            utilisateur=self.lab,
            prelevement=sample,
            resultats={
                self.demande.analyses.get(): {
                    "valeur": "0.95",
                    "unite": "g/L",
                },
            },
        )
        self.client.force_login(self.doctor)

        comparison_url = reverse("laboratoire:compte_rendu", args=[self.demande.pk])
        comparison_page = self.client.get(comparison_url)
        self.assertEqual(comparison_page.status_code, 200)
        self.assertContains(comparison_page, "Votre comparaison avec l’historique")
        self.assertContains(comparison_page, "Configurez")
        self.assertNotContains(
            comparison_page,
            "Générer le résumé IA de cette comparaison",
        )

        response = self.client.post(
            reverse("laboratoire:generer_resume", args=[self.demande.pk]),
            follow=True,
        )

        self.assertContains(response, "Aucun fournisseur IA n’est configuré")
        self.assertFalse(CompteRendu.objects.filter(demande=self.demande).exists())


class DoctorDemoGuideTests(TestCase):
    def test_doctor_request_page_shows_safe_laboratory_demo_steps(self):
        doctor = User.objects.create_user(
            username="doctor-laboratory-demo-guide",
            password="test-password",
            role=User.Role.DOCTEUR,
        )
        self.client.force_login(doctor)

        response = self.client.get(reverse("laboratoire:demande_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tester le suivi médecin–laboratoire")
        self.assertContains(response, "python manage.py seed_laboratory_demo")
        self.assertContains(response, "ne calculent pas un risque d’AVC")
        self.assertContains(response, "data-open-request-modal")
