from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import DossierMedical, ResultatLaboratoire, User

from .forms import ResultatForm
from .ia.chatbot import answer_question, classify_intent
from .models import DemandeAnalyse, Resultat, TypeAnalyse


class PatientLaboratoryInterfaceTests(TestCase):
    def setUp(self):
        self.patient = User.objects.create_user(
            username="patient-interface",
            password="test-password",
            role=User.Role.PATIENT,
        )
        self.other_patient = User.objects.create_user(
            username="other-patient-interface",
            password="test-password",
            role=User.Role.PATIENT,
        )
        self.doctor = User.objects.create_user(
            username="doctor-interface",
            password="test-password",
            role=User.Role.DOCTEUR,
        )
        self.lab = User.objects.create_user(
            username="laboratory-interface",
            password="test-password",
            role=User.Role.LABORATOIRE,
        )
        self.analysis_type = TypeAnalyse.objects.create(
            code="A1C-INTERFACE",
            nom="Hémoglobine glyquée",
            unite="%",
            valeur_reference_min=Decimal("4.000"),
            valeur_reference_max=Decimal("5.600"),
            seuil_critique_haut=Decimal("9.000"),
        )
        self.url = reverse("laboratoire:mes_resultats")

    def create_result(self, patient, value, *, days_ago=0, **fields):
        demande = DemandeAnalyse.objects.create(
            patient=patient,
            medecin=self.doctor,
            laboratoire=self.lab,
            cree_par=self.doctor,
        )
        analyse = demande.analyses.create(type_analyse=self.analysis_type)
        date_validation = timezone.now() - timedelta(days=days_ago)
        return Resultat.objects.create(
            analyse_demandee=analyse,
            saisi_par=self.lab,
            valide_par=self.lab,
            statut=Resultat.Statut.VALIDE,
            valeur=str(value),
            unite="%",
            date_validation=date_validation,
            **fields,
        )

    def test_patient_page_only_contains_own_published_results(self):
        self.create_result(self.patient, "5.0")
        self.create_result(self.other_patient, "PRIVATE-RESULT")
        self.client.force_login(self.patient)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "5.0")
        self.assertNotContains(response, "PRIVATE-RESULT")

    def test_patient_page_hides_internal_comment_and_shows_patient_comment(self):
        self.create_result(
            self.patient,
            "5.0",
            observation="vérifier la valeur saisie et les références du laboratoire",
            commentaire_interne="vérifier la valeur saisie et les références du laboratoire",
            commentaire_patient="Votre résultat est disponible.",
        )
        self.client.force_login(self.patient)

        response = self.client.get(self.url)

        self.assertContains(response, "Votre résultat est disponible.")
        self.assertNotContains(
            response,
            "vérifier la valeur saisie et les références du laboratoire",
        )

    def test_patient_badges_distinguish_normal_and_out_of_range(self):
        self.create_result(self.patient, "5.0")
        self.create_result(self.patient, "7.2")
        self.client.force_login(self.patient)

        response = self.client.get(self.url)

        self.assertContains(response, "Normal")
        self.assertContains(response, "Hors norme")
        self.assertContains(response, "aria-label=\"Valeur 7.2 %; plage normale")

    def test_critical_value_is_flagged_for_doctor_review(self):
        self.create_result(self.patient, "10.2")
        self.client.force_login(self.patient)

        response = self.client.get(self.url)

        self.assertContains(response, "À revoir avec votre médecin")

    def test_interpretations_with_diagnosis_or_treatment_are_hidden_from_patient(self):
        self.create_result(
            self.patient,
            "7.2",
            interpretation=(
                "Dyslipidémie confirmée. Adaptation thérapeutique recommandée."
            ),
        )
        self.client.force_login(self.patient)

        response = self.client.get(self.url)

        self.assertContains(response, "À discuter avec votre médecin")
        self.assertNotContains(response, "Dyslipidémie confirmée")
        self.assertNotContains(response, "Adaptation thérapeutique")

    def test_reference_bar_is_omitted_when_a_bound_is_missing(self):
        resultat = self.create_result(self.patient, "5.0")
        TypeAnalyse.objects.filter(pk=self.analysis_type.pk).update(
            valeur_reference_max=None,
        )
        self.client.force_login(self.patient)

        response = self.client.get(self.url)

        self.assertContains(response, "Référence non renseignée")
        self.assertNotContains(response, 'class="patient-reference"')

    def test_result_form_rejects_zero_and_negative_values(self):
        resultat = self.create_result(self.patient, "5.0")
        form_data = {
            "valeur": "0",
            "unite": "%",
            "valeur_reference": "",
            "interpretation": "",
            "observation": "",
            "commentaire_patient": "",
            "motif_correction": "Correction de test",
        }

        form = ResultatForm(instance=resultat, data=form_data)

        self.assertFalse(form.is_valid())
        self.assertIn(
            "strictement supérieur à zéro",
            str(form.errors["valeur"]),
        )
        form_data["valeur"] = "-1"
        form = ResultatForm(instance=resultat, data=form_data)
        self.assertFalse(form.is_valid())

    def test_invalid_result_report_command_only_reports_existing_values(self):
        self.create_result(self.patient, "0")
        output = StringIO()

        call_command("report_invalid_lab_results", stdout=output)

        self.assertIn("Résultats à vérifier : 1", output.getvalue())
        self.assertIn("aucune donnée modifiée ou supprimée", output.getvalue())

    def test_history_can_filter_by_analysis_and_abnormal_results(self):
        self.create_result(self.patient, "5.0")
        self.create_result(self.patient, "7.2")
        self.client.force_login(self.patient)

        response = self.client.get(self.url, {
            "recherche": "glyquée",
            "hors_norme": "on",
        })

        self.assertContains(response, "7.2")
        self.assertNotContains(response, ">5.0<")

    def test_repeated_analysis_shows_direction_of_change(self):
        self.create_result(self.patient, "4.8", days_ago=2)
        self.create_result(self.patient, "5.2", days_ago=1)
        self.client.force_login(self.patient)

        response = self.client.get(self.url)

        self.assertContains(response, "en hausse depuis le dernier résultat")

    def test_repeated_analysis_can_show_decrease_and_stability(self):
        self.create_result(self.patient, "6.0", days_ago=3)
        self.create_result(self.patient, "5.0", days_ago=2)
        self.client.force_login(self.patient)

        decreasing_response = self.client.get(self.url)

        self.assertContains(
            decreasing_response,
            "en baisse depuis le dernier résultat",
        )
        Resultat.objects.all().delete()
        self.create_result(self.patient, "4.8", days_ago=2)
        self.create_result(self.patient, "5.0", days_ago=1)

        stable_response = self.client.get(self.url)

        self.assertContains(
            stable_response,
            "stable depuis le dernier résultat",
        )

    def test_chart_coordinates_are_valid_svg_numbers_under_localized_settings(self):
        self.create_result(self.patient, "4.8", days_ago=2)
        self.create_result(self.patient, "5.2", days_ago=1)
        self.client.force_login(self.patient)

        response = self.client.get(self.url, {"analyse": self.analysis_type.pk})

        self.assertContains(response, 'class="patient-chart"')
        self.assertContains(response, 'cx="30.0"')
        self.assertContains(response, 'cx="570.0"')
        self.assertNotContains(response, 'cx="30,0"')

    def test_single_or_invalid_previous_result_does_not_show_a_trend(self):
        self.create_result(self.patient, "5.0")
        self.client.force_login(self.patient)

        response = self.client.get(self.url)

        self.assertNotContains(response, "depuis le dernier résultat")
        Resultat.objects.all().delete()
        self.create_result(self.patient, "0", days_ago=2)
        self.create_result(self.patient, "5.0", days_ago=1)

        response_with_invalid_previous = self.client.get(self.url)

        self.assertNotContains(
            response_with_invalid_previous,
            "depuis le dernier résultat",
        )

    def test_patient_pdf_does_not_include_internal_comment(self):
        resultat = self.create_result(
            self.patient,
            "5.0",
            observation="Commentaire réservé au laboratoire.",
            commentaire_interne="Commentaire réservé au laboratoire.",
            commentaire_patient="Message à destination du patient.",
        )
        self.client.force_login(self.patient)

        response = self.client.get(reverse(
            "laboratoire:patient_report_pdf",
            args=[resultat.analyse_demandee.demande_id],
        ))
        pdf_text = response.content.decode("latin-1")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Commentaire réservé au laboratoire", pdf_text)
        self.assertIn("Message à destination du patient", pdf_text)

    def test_patient_pdf_uses_application_brand_and_result_sections(self):
        resultat = self.create_result(
            self.patient,
            "5.0",
            commentaire_patient="Votre résultat est disponible.",
        )
        self.client.force_login(self.patient)

        response = self.client.get(reverse(
            "laboratoire:patient_report_pdf",
            args=[resultat.analyse_demandee.demande_id],
        ))
        pdf_text = response.content.decode("latin-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment; filename=", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF-1.4"))
        self.assertIn("Santé", pdf_text)
        self.assertIn("Connect", pdf_text)
        self.assertIn("COMPTE RENDU D'ANALYSES", pdf_text)
        self.assertIn("Hémoglobine glyquée", pdf_text)
        self.assertIn("5.0 %", pdf_text)
        self.assertIn("VALEURS DE RÉFÉRENCE", pdf_text)
        self.assertIn("Votre résultat est disponible.", pdf_text)

    def test_patient_pdf_paginates_long_patient_comments(self):
        long_comment = "Information destinée au patient. " * 180
        resultat = self.create_result(
            self.patient,
            "5.0",
            commentaire_patient=long_comment,
        )
        self.client.force_login(self.patient)

        response = self.client.get(reverse(
            "laboratoire:patient_report_pdf",
            args=[resultat.analyse_demandee.demande_id],
        ))

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.content.count(b"/Type /Page "), 2)
        self.assertIn(b"Page 1 / 2", response.content)
        self.assertIn(b"Page 2 / 2", response.content)

    def test_legacy_patient_pdf_uses_the_same_branded_layout_and_access_scope(self):
        dossier = DossierMedical.objects.create(
            patient=self.patient,
            numero_dossier="DM-PDF-TEST",
        )
        resultat = ResultatLaboratoire.objects.create(
            dossier=dossier,
            medecin_prescripteur=self.doctor,
            laboratoire=self.lab,
            type_analyse="Bilan sanguin",
            reference="PDF-LEGACY-1",
            statut="DISPONIBLE",
            valeurs="Hémoglobine : 14,2 g/dL",
            interpretation="Résultat à discuter avec le médecin.",
        )
        self.client.force_login(self.patient)

        response = self.client.get(reverse(
            "laboratoire:patient_legacy_report_pdf",
            args=[resultat.pk],
        ))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF-1.4"))
        self.assertIn("Santé".encode("cp1252"), response.content)
        self.assertIn("Bilan sanguin".encode("cp1252"), response.content)
        self.assertIn("PDF-LEGACY-1".encode("cp1252"), response.content)
        other_patient = User.objects.create_user(
            username="other-pdf-patient",
            password="pdf-test-password",
            role=User.Role.PATIENT,
        )
        self.client.force_login(other_patient)
        denied_response = self.client.get(reverse(
            "laboratoire:patient_legacy_report_pdf",
            args=[resultat.pk],
        ))
        self.assertEqual(denied_response.status_code, 404)

    def test_patient_cannot_download_another_patients_report(self):
        other_result = self.create_result(self.other_patient, "5.0")
        self.client.force_login(self.patient)

        response = self.client.get(reverse(
            "laboratoire:patient_report_pdf",
            args=[other_result.analyse_demandee.demande_id],
        ))

        self.assertEqual(response.status_code, 404)

    def test_page_includes_collapsible_notifications_and_chat_interface(self):
        self.create_result(self.patient, "5.0")
        self.client.force_login(self.patient)

        response = self.client.get(self.url)

        self.assertContains(response, "<details>", html=False)
        self.assertContains(response, 'role="dialog"')
        self.assertContains(response, 'role="log"')
        self.assertContains(response, "Une question ?")
        self.assertContains(response, "data-contact-url")

    def test_patient_dashboard_sections_are_grouped_responsively(self):
        self.client.force_login(self.patient)

        response = self.client.get(self.url)
        content = response.content.decode()

        self.assertContains(response, 'class="patient-dashboard-grid"')
        grid_start = content.index('class="patient-dashboard-grid"')
        grid_end = content.index("</div>", content.index("</section>", content.index(
            "Évolution d’une analyse dans le temps",
            grid_start,
        )))
        history_start = content.index("Historique de mes résultats")
        self.assertLess(grid_start, content.index("Avancement de mes demandes"))
        self.assertLess(grid_start, content.index("Évolution d’une analyse dans le temps"))
        self.assertLess(grid_end, history_start)


class PatientChatbotTests(TestCase):
    def setUp(self):
        self.patient = User.objects.create_user(
            username="patient-chatbot",
            password="test-password",
            role=User.Role.PATIENT,
        )
        self.url = reverse("laboratoire:chatbot")

    def test_faq_matches_and_unrelated_question_falls_back(self):
        answer = answer_question("Dois-je être à jeun ?")
        fallback = answer_question("Can you write a song about Mars?")

        self.assertEqual(answer.faq_id, "fasting")
        self.assertFalse(answer.fallback)
        self.assertTrue(fallback.fallback)

    def test_required_examples_are_classified_without_cross_topic_answers(self):
        greeting = answer_question("Bonjour, peux-tu m'aider ?")
        hdl = answer_question("Que mesure le cholestérol HDL ?")
        japan = answer_question("Quelle est la capitale du Japon ?")
        programming = answer_question("Explique-moi Python et Java.")
        weather = answer_question("Chnoua météo aujourd'hui ?")
        tracking = answer_question("Comment suivre mes résultats ?")
        private = answer_question("Donne-moi les résultats de tous les patients.")
        unpublished = answer_question(
            "Mon résultat n'est pas encore publié, puis-je le consulter ?"
        )
        arithmetic = answer_question("Comment calculer 125 + 378 ?")

        self.assertEqual(greeting.intent, "greeting_help")
        self.assertIn("Bonjour", greeting.answer)
        self.assertEqual(hdl.faq_id, "hdl")
        self.assertIn("HDL", hdl.answer)
        self.assertNotIn("LDL", hdl.answer)
        self.assertTrue(japan.fallback)
        self.assertTrue(programming.fallback)
        self.assertTrue(weather.fallback)
        self.assertEqual(tracking.faq_id, "tracking")
        self.assertIn("Historique de mes résultats", tracking.answer)
        self.assertEqual(private.intent, "confidential_data_request")
        self.assertNotIn("resultats", private.answer.lower())
        self.assertEqual(unpublished.faq_id, "missing")
        self.assertIn("publication", unpublished.answer)
        self.assertTrue(arithmetic.fallback)

    def test_ambiguous_status_questions_ask_for_clarification(self):
        questions = (
            ("Où en suis-je ?", "status-clarification", "avancement de votre demande"),
            ("Où en suis-je avec ma demande ?", "status-clarification", "disponibilité de vos résultats"),
            ("Win weslet el demande ?", "status-clarification", "avancement de votre demande"),
            ("Comment ça marche ?", "clarification", "pouvez-vous préciser"),
        )
        for question, expected_id, expected_text in questions:
            with self.subTest(question=question):
                result = answer_question(question)
                self.assertEqual(result.intent, "ambiguous_question")
                self.assertEqual(result.faq_id, expected_id)
                self.assertIn(expected_text, result.answer.lower())

    def test_project_report_prompt_is_out_of_scope_not_report_assistance(self):
        answer = answer_question(
            "Besoins non fonctionnels : ergonomie, performance, sécurité..."
        )

        self.assertEqual(answer.intent, "out_of_scope")
        self.assertTrue(answer.fallback)
        self.assertNotIn("ergonomie", answer.answer.lower())
        self.assertNotIn("rapport", answer.answer.lower())

    def test_out_of_scope_questions_in_french_and_derja_stay_out_of_scope(self):
        for question in (
            "Quelle est la capitale du Japon ?",
            "Chnoua capital Japon ?",
            "Explique-moi la programmation en Python.",
            "Comment fonctionne une voiture électrique ?",
            "Kifech tekhdem karhba électrique ?",
            "Donne-moi une recette de pizza.",
            "Chnoua météo lyom ?",
        ):
            with self.subTest(question=question):
                answer = answer_question(question)
                self.assertEqual(answer.intent, "out_of_scope")
                self.assertTrue(answer.fallback)
                self.assertNotIn("glucose", answer.answer.lower())
                self.assertNotIn("ne peux pas recommander", answer.answer.lower())

    def test_classifier_handles_typos_and_tunisian_transliteration(self):
        typo_greeting = answer_question("Bonjor, peux-tu m'aider ?")
        typo_hdl = answer_question("Que mesure le cholestrol HDL ?")
        tunisian_fast = answer_question("Lezemni nsoum 9bal analyse?")
        arabic_fast = answer_question("هل يجب أن أكون صائما قبل التحليل؟")

        self.assertEqual(typo_greeting.intent, "greeting_help")
        self.assertEqual(typo_hdl.faq_id, "hdl")
        self.assertEqual(tunisian_fast.faq_id, "fasting")
        self.assertEqual(arabic_fast.faq_id, "fasting")
        self.assertEqual(
            classify_intent("Explique-moi Python et Java.").category,
            "out_of_scope",
        )

    def test_medical_treatment_requests_are_not_prescribed(self):
        answer = answer_question("Quel médicament dois-je prendre ?")

        self.assertEqual(answer.intent, "medical_request")
        self.assertIn("ne peux pas recommander", answer.answer)
        self.assertNotIn("mg", answer.answer)

    def test_requested_french_and_tunisian_intents_are_routed_correctly(self):
        examples = (
            ("Bonjour, peux-tu m'aider ?", "greeting_help", "greeting"),
            ("C'est quoi une analyse de glycémie ?", "glycemia", "glycemia"),
            ("Chnouwa analyse glycémie ?", "glycemia", "glycemia"),
            ("Que mesure le cholestérol HDL ?", "hdl", "hdl"),
            ("Chnouwa HDL ?", "hdl", "hdl"),
            ("Que signifie LDL ?", "ldl", "ldl"),
            ("Comment consulter mes résultats ?", "result_access", "tracking"),
            ("Mes résultats sont-ils disponibles ?", "result_publication_status", "missing"),
            ("Kifech nchouf résultat mte3i ?", "result_access", "tracking"),
            ("Dois-je être à jeun ?", "fasting", "fasting"),
            ("Comment être à jeun ?", "fasting", "fasting"),
            ("Comment être à jeun ?", "fasting", "fasting"),
            ("Quand le résultat sera-t-il disponible ?", "analysis_delay", "delay"),
            ("Délai des résultats", "analysis_delay", "delay"),
            ("Wa9tech yetla3 el résultat ?", "analysis_delay", "delay"),
            ("Kifech naaref ken résultat mte3i thadhar ?", "result_publication_status", "missing"),
            ("Comment fonctionne la traçabilité d'un prélèvement ?", "sample_tracking_general", "sample-tracking-general"),
            ("Quelle est la capitale du Japon ?", "out_of_scope", None),
            ("Explique-moi la programmation en Python", "out_of_scope", None),
            ("Explique Python et Java", "out_of_scope", None),
            ("Comment fonctionne une voiture électrique ?", "out_of_scope", None),
            ("Donne-moi une recette de pizza", "out_of_scope", None),
            ("Chnoua capital Japon ?", "out_of_scope", None),
            ("Kifech tekhdem karhba électrique ?", "out_of_scope", None),
            ("Chnoua météo lyom ?", "out_of_scope", None),
            ("Qui a modifié le résultat de cette analyse ?", "result_history_access", "audit-history"),
            ("Donne-moi les résultats médicaux de tous les patients", "confidential_data_request", "privacy-denied"),
            ("Quel médicament dois-je prendre ?", "medical_request", "medical-safety"),
            ("Que faire si mon résultat est hors norme ?", "laboratory_info", "high-low"),
        )
        for question, expected_intent, expected_id in examples:
            with self.subTest(question=question):
                result = answer_question(question)
                self.assertEqual(result.intent, expected_intent)
                self.assertEqual(result.faq_id, expected_id)
                if expected_intent == "out_of_scope":
                    self.assertTrue(result.fallback)
                    self.assertIsNone(result.faq_id)
                else:
                    self.assertGreaterEqual(
                        classify_intent(question).confidence,
                        0.75,
                    )

    def test_glycemia_and_hdl_answers_are_topic_specific(self):
        glycemia = answer_question("C'est quoi une analyse de glycémie ?")
        glycemia_tn = answer_question("Chnouwa analyse glycémie ?")
        hdl = answer_question("Que mesure le cholestérol HDL ?")
        hdl_tn = answer_question("Chnouwa HDL ?")

        self.assertEqual(glycemia.intent, "glycemia")
        self.assertIn("glucose", glycemia.answer)
        self.assertNotEqual(glycemia.faq_id, "clarification")
        self.assertEqual(glycemia_tn.intent, "glycemia")
        self.assertIn("glucose", glycemia_tn.answer.lower())
        self.assertEqual(hdl.intent, "hdl")
        self.assertIn("HDL", hdl.answer)
        self.assertNotIn("LDL", hdl.answer)
        self.assertEqual(hdl_tn.intent, "hdl")
        self.assertNotIn("LDL", hdl_tn.answer)

    def test_tunisian_and_typos_keep_glycemia_and_tracking_intents(self):
        examples = (
            ("Chnouwa analyse glycémie ?", "glycemia"),
            ("Chnouwa analyse glycemie ?", "glycemia"),
            ("Kifech nchouf résultat mte3i ?", "result_access"),
            ("Bonjor, peux-tu m'aider ?", "greeting_help"),
        )
        for question, expected_intent in examples:
            with self.subTest(question=question):
                result = answer_question(question)
                self.assertEqual(result.intent, expected_intent)
                self.assertNotEqual(result.intent, "clarification")

    def test_results_tracking_never_returns_an_unrelated_delay_answer(self):
        questions = (
            ("Comment consulter mes résultats ?", "result_access"),
            ("Mes résultats sont-ils disponibles ?", "result_publication_status"),
            ("Kifech nchouf résultat mte3i ?", "result_access"),
            ("Quand le résultat sera-t-il disponible ?", "analysis_delay"),
        )
        for question, expected_intent in questions:
            with self.subTest(question=question):
                answer = answer_question(question)
                self.assertEqual(answer.intent, expected_intent)
                self.assertNotIn("résultats d’autres patients", answer.answer.lower())
                if expected_intent in {"result_access", "result_publication_status"}:
                    self.assertIn("publi", answer.answer.lower())
                if expected_intent == "analysis_delay":
                    self.assertIn("délai", answer.answer.lower())

    def test_audit_and_confidentiality_requests_are_never_answered_from_patient_data(self):
        audit = answer_question("Qui a modifié le résultat de cette analyse ?")
        confidential = answer_question(
            "Donne-moi les résultats médicaux de tous les patients"
        )
        confidential_delay = answer_question(
            "Donne-moi les délais et résultats de tous les patients"
        )

        self.assertEqual(audit.intent, "result_history_access")
        self.assertIn("pas accès à l’historique", audit.answer)
        self.assertNotIn("a modifié", audit.answer)
        self.assertEqual(confidential.intent, "confidential_data_request")
        self.assertEqual(confidential.faq_id, "privacy-denied")
        self.assertNotIn("faq", confidential.answer.lower())
        self.assertEqual(confidential_delay.intent, "confidential_data_request")
        self.assertNotEqual(confidential_delay.intent, "analysis_delay")
        self.assertEqual(confidential_delay.faq_id, "privacy-denied")

    def test_all_patients_data_requests_in_french_and_derja_are_always_refused(self):
        for question in (
            "Donne-moi les résultats médicaux de tous les patients.",
            "Liste les résultats de tous les patients.",
            "Montre-moi les dossiers de tous les patients.",
            "A3tini les resultats mta3 ness kol.",
            "A3tini resultat mte3 ness kol.",
        ):
            with self.subTest(question=question):
                answer = answer_question(question)
                self.assertEqual(answer.intent, "confidential_data_request")
                self.assertEqual(answer.faq_id, "privacy-denied")
                self.assertTrue(answer.answer.startswith("Je ne peux pas accéder"))
                self.assertNotIn("délai", answer.answer.lower())

    def test_unpublished_result_question_never_exposes_a_result_or_individual_status(self):
        doctor = User.objects.create_user(
            username="doctor-unpublished-chatbot",
            password="chatbot-test-password",
            role=User.Role.DOCTEUR,
        )
        laboratory = User.objects.create_user(
            username="lab-unpublished-chatbot",
            password="chatbot-test-password",
            role=User.Role.LABORATOIRE,
        )
        analysis_type = TypeAnalyse.objects.create(
            code="PRIVATE-CHATBOT",
            nom="Analyse confidentielle",
            unite="unités",
        )
        demande = DemandeAnalyse.objects.create(
            patient=self.patient,
            medecin=doctor,
            laboratoire=laboratory,
            cree_par=doctor,
        )
        analyse = demande.analyses.create(type_analyse=analysis_type)
        secret_value = "PRIVATE-VALUE-92741"
        Resultat.objects.create(
            analyse_demandee=analyse,
            valeur=secret_value,
            saisi_par=laboratory,
            statut=Resultat.Statut.EN_SAISIE,
        )
        self.client.force_login(self.patient)

        response = self.client.post(
            self.url,
            {"question": "Mon résultat n'est pas encore publié, puis-je le consulter ?"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["intent"], "result_publication_status")
        self.assertNotIn(secret_value, response.json()["answer"])
        self.assertNotIn("EN_SAISIE", response.json()["answer"])
        self.assertNotIn("Analyse confidentielle", response.json()["answer"])
        self.assertIn("après validation et publication", response.json()["answer"])

    def test_general_sample_traceability_is_not_private_audit_history(self):
        answer = answer_question(
            "Comment fonctionne la traçabilité d'un prélèvement ?"
        )

        self.assertEqual(answer.intent, "sample_tracking_general")
        self.assertEqual(answer.faq_id, "sample-tracking-general")
        self.assertIn("étapes de statut", answer.answer)
        self.assertNotIn("qui a modifié", answer.answer.lower())

    def test_sensitive_history_question_does_not_invent_an_actor(self):
        answer = answer_question("Qui a modifié le résultat de cette analyse ?")

        self.assertEqual(answer.intent, "result_history_access")
        self.assertEqual(answer.faq_id, "audit-history")
        self.assertIn("ne peux pas identifier l’auteur", answer.answer)
        self.assertNotIn("patient-chatbot", answer.answer)

    def test_validation_author_questions_are_routed_to_authorized_audit_history(self):
        questions = (
            "Est-ce que tu peux me donner le nom du technicien qui a validé cette analyse ?",
            "Qui a validé cette analyse ?",
            "Quel est le nom du technicien ?",
            "Qui a modifié mon résultat ?",
            "Qui est l’auteur de la validation ?",
        )
        for question in questions:
            with self.subTest(question=question):
                answer = answer_question(question)
                self.assertEqual(answer.intent, "result_history_access")
                self.assertEqual(answer.faq_id, "audit-history")
                self.assertIn("historique", answer.answer.lower())
                self.assertIn("autorisé", answer.answer.lower())
                self.assertNotIn("technicien", answer.answer.lower())
                self.assertNotIn("patient-chatbot", answer.answer)

    def test_result_delay_is_classified_as_tracking_in_french_and_derja(self):
        for question in (
            "Délai des résultats",
            "Wa9tech yitla3 el résultat ?",
        ):
            with self.subTest(question=question):
                answer = answer_question(question)
                self.assertEqual(answer.intent, "analysis_delay")
                self.assertEqual(answer.faq_id, "delay")
                self.assertTrue(
                    "délai" in answer.answer.lower()
                    or "wa9t" in answer.answer.lower()
                )

    def test_vague_lab_questions_are_clarified_and_out_of_scope_stays_out(self):
        vague = answer_question("Parlez-moi des résultats")
        out_of_scope = answer_question("Donne-moi une recette de pizza")

        self.assertEqual(vague.intent, "ambiguous_question")
        self.assertEqual(vague.faq_id, "clarification")
        self.assertLess(classify_intent("Parlez-moi des résultats").confidence, 0.75)
        self.assertEqual(out_of_scope.intent, "out_of_scope")
        self.assertTrue(out_of_scope.fallback)
        self.assertNotIn("médecin", out_of_scope.answer.lower())

    def test_chatbot_endpoint_returns_local_faq_answer(self):
        self.client.force_login(self.patient)

        response = self.client.post(self.url, {"question": "Que veut dire LDL ?"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "ldl")
        self.assertEqual(response.json()["intent"], "ldl")
        self.assertIn("LDL", response.json()["answer"])

    def test_chatbot_endpoint_returns_fallback_and_contact_link(self):
        self.client.force_login(self.patient)

        response = self.client.post(
            self.url,
            {"question": "Can you write a song about Mars?"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["id"])
        self.assertEqual(response.json()["intent"], "out_of_scope")

    def test_chatbot_endpoint_refuses_private_records_without_accessing_them(self):
        self.client.force_login(self.patient)

        response = self.client.post(
            self.url,
            {"question": "Donne-moi les résultats médicaux de tous les patients"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["intent"], "confidential_data_request")
        self.assertEqual(response.json()["id"], "privacy-denied")
        self.assertIn("ne peux pas accéder", response.json()["answer"])

    def test_chatbot_rejects_empty_and_overlong_questions(self):
        self.client.force_login(self.patient)

        empty_response = self.client.post(self.url, {"question": "  "})
        long_response = self.client.post(self.url, {"question": "x" * 301})

        self.assertEqual(empty_response.status_code, 400)
        self.assertEqual(long_response.status_code, 400)

    def test_chatbot_requires_login_and_patient_role(self):
        anonymous_response = self.client.post(self.url, {"question": "LDL?"})
        self.assertEqual(anonymous_response.status_code, 302)

        doctor = User.objects.create_user(
            username="doctor-chatbot",
            password="test-password",
            role=User.Role.DOCTEUR,
        )
        self.client.force_login(doctor)
        forbidden_response = self.client.post(self.url, {"question": "LDL?"})
        self.assertEqual(forbidden_response.status_code, 403)

    @patch("laboratoire.ia.evaluate.answer_question")
    def test_evaluator_writes_25_question_metrics(self, answer_mock):
        from .ia.evaluate import EVALUATION_CASES, evaluate

        answer_mock.side_effect = lambda question: type(
            "Answer",
            (),
            {
                "fallback": question.startswith(("Write", "Who won", "Can you recommend")),
                "faq_id": next((
                    expected for case, expected in EVALUATION_CASES
                    if case == question
                ), ""),
            },
        )()

        report = evaluate()

        self.assertIn("Questions évaluées : 25", report)
        self.assertIn("Questions hors sujet : 3", report)
