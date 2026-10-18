import io
from datetime import timedelta
from decimal import Decimal
from zipfile import ZipFile

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    AssociationMedecinPatient,
    DossierMedical,
    ResultatLaboratoire,
    User,
)
from .models import (
    AnalyseDemandee,
    BilanPredefini,
    DemandeAnalyse,
    HistoriqueAction,
    ParametresLaboratoire,
    Prelevement,
    Resultat,
    TypeAnalyse,
)
from .services import (
    enregistrer_prelevement,
    enregistrer_resultat,
    valider_resultat,
)


class LaboratoireTests(TestCase):
    def setUp(self):
        self.responsable_group, _ = Group.objects.get_or_create(
            name="Biologiste responsable",
        )
        self.doctor = User.objects.create_user(
            username="doctor-lab-test", password="secret", role=User.Role.DOCTEUR,
        )
        self.patient = User.objects.create_user(
            username="patient-lab-test", password="secret", role=User.Role.PATIENT,
        )
        self.lab = User.objects.create_user(
            username="lab-test", password="secret", role=User.Role.LABORATOIRE,
        )
        self.admin = User.objects.create_user(
            username="admin-lab-test", password="secret", role=User.Role.ADMIN,
        )
        AssociationMedecinPatient.objects.create(
            medecin=self.doctor, patient=self.patient,
        )
        self.type_analyse = TypeAnalyse.objects.create(
            code="GLY", nom="Glycémie", unite="g/L",
            valeur_reference_min=Decimal("0.700"),
            valeur_reference_max=Decimal("1.100"),
        )
        self.demande = DemandeAnalyse.objects.create(
            patient=self.patient, medecin=self.doctor, laboratoire=self.lab,
            cree_par=self.doctor,
        )
        self.analyse = AnalyseDemandee.objects.create(
            demande=self.demande, type_analyse=self.type_analyse,
        )

    def test_catalogue_bilans_and_settings_are_admin_only(self):
        admin_urls = (
            reverse("laboratoire:type_list"),
            reverse("laboratoire:bilan_list"),
            reverse("laboratoire:parametres"),
        )
        self.client.force_login(self.lab)
        for url in admin_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(
                    response, reverse("dashboard"), fetch_redirect_response=False,
                )

        self.client.force_login(self.admin)
        for url in admin_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_admin_can_manage_catalog_critical_thresholds_and_bilans(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("laboratoire:type_create"), {
            "code": "TEST-CRIT",
            "nom": "Analyse critique",
            "description": "",
            "unite": "mmol/L",
            "valeur_reference_min": "3.000",
            "valeur_reference_max": "7.000",
            "seuil_critique_bas": "1.000",
            "seuil_critique_haut": "10.000",
            "tarif": "12.50",
            "actif": "on",
        })
        self.assertRedirects(response, reverse("laboratoire:type_list"))
        analyse_type = TypeAnalyse.objects.get(code="TEST-CRIT")
        self.assertEqual(analyse_type.seuil_critique_bas, Decimal("1.000"))
        self.assertEqual(analyse_type.seuil_critique_haut, Decimal("10.000"))

        response = self.client.post(reverse("laboratoire:bilan_create"), {
            "nom": "Bilan rénal",
            "description": "Bilan de contrôle",
            "analyses": [analyse_type.pk],
            "actif": "on",
        })
        self.assertRedirects(response, reverse("laboratoire:bilan_list"))
        bilan = BilanPredefini.objects.get(nom="Bilan rénal")
        self.assertEqual(list(bilan.analyses.values_list("pk", flat=True)), [analyse_type.pk])

        self.client.post(reverse("laboratoire:type_update", args=[analyse_type.pk]), {
            "code": "TEST-CRIT",
            "nom": "Analyse critique",
            "description": "",
            "unite": "mmol/L",
            "valeur_reference_min": "3.000",
            "valeur_reference_max": "7.000",
            "seuil_critique_bas": "1.000",
            "seuil_critique_haut": "10.000",
            "tarif": "12.50",
        })
        analyse_type.refresh_from_db()
        self.assertFalse(analyse_type.actif)

    def test_doctor_can_prescribe_the_active_analyses_in_a_bilan(self):
        bilan = BilanPredefini.objects.create(nom="Bilan lipidique")
        bilan.analyses.add(self.type_analyse)
        self.client.force_login(self.doctor)
        response = self.client.post(reverse("laboratoire:demande_create"), {
            "patient": self.patient.pk,
            "laboratoire": self.lab.pk,
            "priorite": DemandeAnalyse.Priorite.NORMALE,
            "commentaire": "Prescription avec bilan",
            "analyses": [],
            "bilans": [bilan.pk],
        })
        demande = DemandeAnalyse.objects.get(commentaire="Prescription avec bilan")
        self.assertRedirects(
            response, reverse("laboratoire:demande_detail", args=[demande.pk]),
        )
        self.assertEqual(
            list(demande.analyses.values_list("type_analyse_id", flat=True)),
            [self.type_analyse.pk],
        )

    def test_laboratory_settings_drive_rejection_suggestions_and_urgent_alerts(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("laboratoire:parametres"), {
            "nom": "Laboratoire Central",
            "adresse": "1 rue des Tests",
            "telephone": "0102030405",
            "entete_compte_rendu": "Résultats d’analyses",
            "signature_compte_rendu": "Dr Test",
            "motifs_rejet": "Échantillon hémolysé\nQuantité insuffisante\nMauvais tube",
            "delai_alerte_urgente_minutes": "30",
        })
        self.assertRedirects(response, reverse("laboratoire:parametres"))
        settings = ParametresLaboratoire.objects.get(pk=1)
        self.assertEqual(
            settings.motifs_rejet,
            ["Échantillon hémolysé", "Quantité insuffisante", "Mauvais tube"],
        )

        self.demande.priorite = DemandeAnalyse.Priorite.URGENTE
        self.demande.date_demande = timezone.now() - timedelta(minutes=31)
        self.demande.save(update_fields=["priorite", "date_demande"])
        self.client.force_login(self.lab)
        response = self.client.get(reverse("laboratoire:demande_list"))
        self.assertContains(response, "En retard")
        response = self.client.get(reverse(
            "laboratoire:prelevement_create", args=[self.demande.pk],
        ))
        self.assertContains(response, "Mauvais tube")

    def test_critical_thresholds_are_ordered_and_flag_critical_results(self):
        self.type_analyse.seuil_critique_bas = Decimal("0.100")
        self.type_analyse.seuil_critique_haut = Decimal("2.000")
        self.type_analyse.save()
        self.type_analyse.seuil_critique_bas = Decimal("3.000")
        with self.assertRaises(ValidationError):
            self.type_analyse.full_clean()

        resultat = enregistrer_resultat(
            analyse_demandee=self.analyse,
            prelevement=None,
            utilisateur=self.lab,
            donnees={"valeur": "2.0"},
        )
        self.assertTrue(resultat.potentiellement_critique)

    def test_admin_supervision_actions_and_exports_are_restricted(self):
        self.client.force_login(self.lab)
        for url in (
            reverse("laboratoire:supervision"),
            reverse("laboratoire:rapports"),
            reverse("laboratoire:rapports_export", args=["csv"]),
            reverse("laboratoire:demande_reaffecter", args=[self.demande.pk]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(
                    response, reverse("dashboard"), fetch_redirect_response=False,
                )

        self.client.force_login(self.admin)
        response = self.client.get(reverse("laboratoire:supervision"))
        self.assertContains(response, "Supervision de l’activité")
        self.assertContains(response, self.patient.username)

        another_lab = User.objects.create_user(
            username="lab-reassigned-test", ******, role=User.Role.LABORATOIRE,
        )
        response = self.client.post(
            reverse("laboratoire:demande_reaffecter", args=[self.demande.pk]),
            {"laboratoire": another_lab.pk},
        )
        self.assertRedirects(response, reverse("laboratoire:supervision"))
        self.demande.refresh_from_db()
        self.assertEqual(self.demande.laboratoire, another_lab)
        self.assertEqual(self.demande.statut, DemandeAnalyse.Statut.EN_COURS)

        response = self.client.post(
            reverse("laboratoire:demande_annuler_admin", args=[self.demande.pk]),
            {"motif": "Demande créée par erreur"},
        )
        self.assertRedirects(response, reverse("laboratoire:supervision"))
        self.demande.refresh_from_db()
        self.assertEqual(self.demande.statut, DemandeAnalyse.Statut.ANNULEE)
        self.assertEqual(self.demande.motif_annulation, "Demande créée par erreur")
        annulation = HistoriqueAction.objects.get(
            objet_id=self.demande.pk,
            type_action="DEMANDE_ANNULEE",
        )
        self.assertEqual(
            annulation.details["apres"]["motif_annulation"],
            "Demande créée par erreur",
        )

    def test_admin_report_filters_metrics_and_exports(self):
        self.type_analyse.tarif = Decimal("25.50")
        self.type_analyse.save()
        self.demande.date_demande = timezone.now() - timedelta(days=1)
        self.demande.save(update_fields=["date_demande"])
        Prelevement.objects.create(
            demande=self.demande,
            code_prelevement="REPORT-REJECTED",
            type_prelevement=Prelevement.Type.SANG,
            statut=Prelevement.Statut.REJETE,
            motif_rejet="Tube hémolysé",
        )
        Resultat.objects.create(
            analyse_demandee=self.analyse,
            valeur="0.9",
            statut=Resultat.Statut.EN_ATTENTE_VALIDATION,
            saisi_par=self.lab,
        )
        self.client.force_login(self.admin)
        date_debut = (timezone.localdate() - timedelta(days=2)).isoformat()
        date_fin = timezone.localdate().isoformat()
        response = self.client.get(reverse("laboratoire:rapports"), {
            "date_debut": date_debut,
            "date_fin": date_fin,
        })
        self.assertEqual(
            response.context["report"]["chiffre_affaires"], Decimal("25.50"),
        )
        self.assertContains(response, "Glycémie")
        self.assertContains(response, "Résultats à valider")

        csv_response = self.client.get(
            reverse("laboratoire:rapports_export", args=["csv"]),
            {"date_debut": date_debut, "date_fin": date_fin},
        )
        self.assertEqual(csv_response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Demandes", csv_response.content.decode("utf-8-sig"))

        xlsx_response = self.client.get(
            reverse("laboratoire:rapports_export", args=["xlsx"]),
            {"date_debut": date_debut, "date_fin": date_fin},
        )
        with ZipFile(io.BytesIO(xlsx_response.content)) as workbook:
            self.assertIn("xl/workbook.xml", workbook.namelist())
            self.assertIn("xl/worksheets/sheet2.xml", workbook.namelist())

    def test_resultat_validation_and_traceability(self):
        resultat = enregistrer_resultat(
            analyse_demandee=self.analyse,
            prelevement=None,
            utilisateur=self.lab,
            donnees={"valeur": "1.3", "unite": "g/L", "valeur_reference": "0.7–1.1"},
        )
        self.assertEqual(resultat.statut, Resultat.Statut.EN_ATTENTE_VALIDATION)
        self.assertTrue(resultat.potentiellement_anormal)
        self.assertEqual(self.demande.__class__.objects.get(pk=self.demande.pk).statut,
                         DemandeAnalyse.Statut.EN_COURS)

        with self.assertRaises(ValidationError):
            valider_resultat(resultat=resultat, utilisateur=self.admin)
        self.responsable_group.user_set.add(self.lab)
        valider_resultat(resultat=resultat, utilisateur=self.lab)
        resultat.refresh_from_db()
        self.assertEqual(resultat.statut, Resultat.Statut.VALIDE)
        self.assertEqual(resultat.valide_par, self.lab)
        self.assertIsNotNone(resultat.date_validation)
        self.assertEqual(self.demande.__class__.objects.get(pk=self.demande.pk).statut,
                         DemandeAnalyse.Statut.TERMINEE)
        self.assertTrue(HistoriqueAction.objects.filter(type_action="RESULTAT_VALIDE").exists())

    def test_correction_of_validated_result_requires_revalidation(self):
        self.responsable_group.user_set.add(self.lab)
        resultat = enregistrer_resultat(
            analyse_demandee=self.analyse, prelevement=None, utilisateur=self.lab,
            donnees={"valeur": "0.9"},
        )
        valider_resultat(resultat=resultat, utilisateur=self.lab)
        enregistrer_resultat(
            analyse_demandee=self.analyse, prelevement=None, utilisateur=self.lab,
            donnees={"valeur": "0.95", "observation": "Correction après contrôle"},
            resultat=resultat,
        )
        resultat.refresh_from_db()
        self.assertEqual(resultat.statut, Resultat.Statut.CORRIGE)
        self.assertIsNone(resultat.valide_par)
        self.assertTrue(HistoriqueAction.objects.filter(type_action="RESULTAT_CORRIGE").exists())

    def test_rejected_sample_requires_reason_and_cannot_have_result(self):
        sample = Prelevement(
            demande=self.demande,
            code_prelevement="SAMPLE-001",
            type_prelevement=Prelevement.Type.SANG,
            statut=Prelevement.Statut.REJETE,
        )
        with self.assertRaises(ValidationError):
            enregistrer_prelevement(
                prelevement=sample, utilisateur=self.lab,
                donnees={
                    "code_prelevement": sample.code_prelevement,
                    "type_prelevement": sample.type_prelevement,
                    "statut": sample.statut,
                    "motif_rejet": "",
                },
            )
        sample.motif_rejet = "Tube hémolysé"
        sample.save()
        with self.assertRaises(ValidationError):
            enregistrer_resultat(
                analyse_demandee=self.analyse, prelevement=sample,
                utilisateur=self.lab, donnees={"valeur": "0.9"},
            )

    def test_received_sample_is_saved_and_audited(self):
        sample = Prelevement(
            demande=self.demande,
            code_prelevement="SAMPLE-RECEIVED",
            type_prelevement=Prelevement.Type.SANG,
            statut=Prelevement.Statut.RECU,
        )
        enregistrer_prelevement(
            prelevement=sample,
            utilisateur=self.lab,
            donnees={
                "code_prelevement": sample.code_prelevement,
                "type_prelevement": sample.type_prelevement,
                "statut": sample.statut,
            },
        )
        self.assertIsNotNone(sample.pk)
        self.assertIsNotNone(sample.date_reception)
        self.assertTrue(
            HistoriqueAction.objects.filter(
                objet_concerne="Prelevement",
                objet_id=sample.pk,
                type_action="PRELEVEMENT_CREE",
            ).exists()
        )

        sample.statut = Prelevement.Statut.PRELEVE
        sample.motif_rejet = ""
        sample.save()
        with self.assertRaises(ValidationError):
            enregistrer_resultat(
                analyse_demandee=self.analyse, prelevement=sample,
                utilisateur=self.lab, donnees={"valeur": "0.9"},
            )

    def test_doctor_can_prescribe_and_patient_cannot_access_requests(self):
        self.client.force_login(self.doctor)
        response = self.client.post(reverse("laboratoire:demande_create"), {
            "patient": self.patient.pk,
            "laboratoire": self.lab.pk,
            "priorite": DemandeAnalyse.Priorite.URGENTE,
            "commentaire": "À jeun",
            "analyses": [self.type_analyse.pk],
        })
        created = DemandeAnalyse.objects.get(commentaire="À jeun")
        self.assertRedirects(response, reverse("laboratoire:demande_detail", args=[created.pk]))
        self.assertEqual(created.medecin, self.doctor)
        self.assertEqual(created.analyses.count(), 1)

        self.client.force_login(self.patient)
        response = self.client.get(reverse("laboratoire:demande_list"))
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)

    def test_doctor_cannot_read_another_doctors_request(self):
        other_doctor = User.objects.create_user(
            username="doctor-other-test", password="secret", role=User.Role.DOCTEUR,
        )
        other_request = DemandeAnalyse.objects.create(
            patient=self.patient, medecin=other_doctor, laboratoire=self.lab,
        )
        self.client.force_login(self.doctor)
        response = self.client.get(reverse("laboratoire:demande_detail", args=[other_request.pk]))
        self.assertRedirects(response, reverse("laboratoire:demande_list"), fetch_redirect_response=False)

    def test_laboratory_queue_shows_own_and_unassigned_requests(self):
        another_lab = User.objects.create_user(
            username="another-lab-test", ******, role=User.Role.LABORATOIRE,
        )
        unassigned = DemandeAnalyse.objects.create(
            patient=self.patient, medecin=self.doctor,
        )
        assigned_elsewhere = DemandeAnalyse.objects.create(
            patient=self.patient, medecin=self.doctor, laboratoire=another_lab,
        )
        self.client.force_login(self.lab)
        response = self.client.get(reverse("laboratoire:demande_list"))
        self.assertContains(
            response, reverse("laboratoire:demande_detail", args=[self.demande.pk]),
        )
        self.assertContains(
            response, reverse("laboratoire:demande_detail", args=[unassigned.pk]),
        )
        self.assertNotContains(
            response, reverse("laboratoire:demande_detail", args=[assigned_elsewhere.pk]),
        )

    def test_patient_sees_only_their_validated_results(self):
        self.responsable_group.user_set.add(self.lab)
        own_result = enregistrer_resultat(
            analyse_demandee=self.analyse, prelevement=None, utilisateur=self.lab,
            donnees={"valeur": "0.91"},
        )
        valider_resultat(resultat=own_result, utilisateur=self.lab)
        pending_result = Resultat.objects.create(
            analyse_demandee=self.analyse, valeur="1.02", saisi_par=self.lab,
        )

        other_patient = User.objects.create_user(
            username="patient-other-test", ******, role=User.Role.PATIENT,
        )
        other_request = DemandeAnalyse.objects.create(
            patient=other_patient, medecin=self.doctor, laboratoire=self.lab,
        )
        other_analysis = AnalyseDemandee.objects.create(
            demande=other_request, type_analyse=self.type_analyse,
        )
        other_result = enregistrer_resultat(
            analyse_demandee=other_analysis, prelevement=None, utilisateur=self.lab,
            donnees={"valeur": "0.83"},
        )
        valider_resultat(resultat=other_result, utilisateur=self.lab)

        self.client.force_login(self.patient)
        response = self.client.get(reverse("laboratoire:mes_resultats"))
        self.assertContains(response, own_result.valeur)
        self.assertNotContains(response, pending_result.valeur)
        self.assertNotContains(response, other_result.valeur)
        self.assertContains(response, "Avancement de mes demandes")
        self.assertContains(response, "Nouveau résultat disponible")
        self.assertContains(response, "Historique de mes résultats")
        dashboard = self.client.get(reverse("patient_dashboard"))
        self.assertContains(dashboard, "nouveau")

        filtered_response = self.client.get(
            reverse("laboratoire:mes_resultats"),
            {
                "analyse": self.type_analyse.pk,
                "date_debut": timezone.localdate().isoformat(),
                "date_fin": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(filtered_response.status_code, 200)
        self.assertContains(filtered_response, "<circle", html=False)
        self.assertEqual(len(filtered_response.context["chart_points"]), 1)

        own_pdf = self.client.get(reverse(
            "laboratoire:patient_report_pdf", args=[self.demande.pk],
        ))
        self.assertEqual(own_pdf["Content-Type"], "application/pdf")
        self.assertTrue(own_pdf.content.startswith(b"%PDF-1.4"))
        self.assertIn(b"0.91", own_pdf.content)
        other_pdf = self.client.get(reverse(
            "laboratoire:patient_report_pdf", args=[other_request.pk],
        ))
        self.assertEqual(other_pdf.status_code, 404)
        pending_pdf = self.client.get(reverse(
            "laboratoire:patient_report_pdf", args=[DemandeAnalyse.objects.create(
                patient=self.patient, medecin=self.doctor, laboratoire=self.lab,
            ).pk],
        ))
        self.assertRedirects(
            pending_pdf, reverse("laboratoire:mes_resultats"),
            fetch_redirect_response=False,
        )

    def test_patient_result_page_includes_only_published_legacy_results(self):
        dossier = DossierMedical.objects.create(
            patient=self.patient, numero_dossier="DM-LAB-PATIENT-RESULTS",
        )
        published = ResultatLaboratoire.objects.create(
            dossier=dossier,
            medecin_prescripteur=self.doctor,
            laboratoire=self.lab,
            type_analyse="NFS",
            reference="AN-PATIENT-PUBLISHED",
            statut="DISPONIBLE",
            valeurs="Hémoglobine : 13 g/dL",
        )
        pending = ResultatLaboratoire.objects.create(
            dossier=dossier,
            medecin_prescripteur=self.doctor,
            laboratoire=self.lab,
            type_analyse="Glycémie",
            reference="AN-PATIENT-PENDING",
            statut="EN_COURS",
            valeurs="Valeur en attente",
        )
        self.client.force_login(self.patient)
        response = self.client.get(reverse("laboratoire:mes_resultats"))
        self.assertContains(response, published.reference)
        self.assertNotContains(response, pending.reference)
        self.assertNotContains(response, pending.valeurs)
        self.assertContains(response, published.valeurs.split(":")[0])
        for url in (reverse("patient_dashboard"), reverse("patient_dossier")):
            response = self.client.get(url)
            self.assertContains(response, published.reference)
            self.assertNotContains(response, pending.reference)
            self.assertNotContains(response, pending.valeurs)
        dashboard = self.client.get(reverse("patient_dashboard"))
        self.assertContains(
            dashboard, reverse("laboratoire:mes_resultats"),
        )
        patient_pdf = self.client.get(reverse(
            "laboratoire:patient_legacy_report_pdf", args=[published.pk],
        ))
        self.assertEqual(patient_pdf["Content-Type"], "application/pdf")
        self.assertTrue(patient_pdf.content.startswith(b"%PDF-1.4"))
        hidden_legacy_pdf = self.client.get(reverse(
            "laboratoire:patient_legacy_report_pdf", args=[pending.pk],
        ))
        self.assertEqual(hidden_legacy_pdf.status_code, 404)

    def test_doctor_can_review_associated_patient_results_and_download_pdf(self):
        self.responsable_group.user_set.add(self.lab)
        self.type_analyse.seuil_critique_haut = Decimal("1.000")
        self.type_analyse.save(update_fields=["seuil_critique_haut"])
        first_result = enregistrer_resultat(
            analyse_demandee=self.analyse,
            prelevement=None,
            utilisateur=self.lab,
            donnees={"valeur": "1.2", "unite": "g/L"},
        )
        valider_resultat(resultat=first_result, utilisateur=self.lab)

        second_request = DemandeAnalyse.objects.create(
            patient=self.patient,
            medecin=self.doctor,
            laboratoire=self.lab,
        )
        second_analysis = AnalyseDemandee.objects.create(
            demande=second_request,
            type_analyse=self.type_analyse,
        )
        second_result = enregistrer_resultat(
            analyse_demandee=second_analysis,
            prelevement=None,
            utilisateur=self.lab,
            donnees={"valeur": "1.3", "unite": "g/L"},
        )
        valider_resultat(resultat=second_result, utilisateur=self.lab)
        Prelevement.objects.create(
            demande=second_request,
            code_prelevement="DOCTOR-REJECTED-SAMPLE",
            type_prelevement=Prelevement.Type.SANG,
            statut=Prelevement.Statut.REJETE,
            motif_rejet="Échantillon hémolysé",
        )

        self.client.force_login(self.doctor)
        history = self.client.get(reverse(
            "laboratoire:doctor_patient_history", args=[self.patient.pk],
        ), {"analyse": self.type_analyse.pk})
        self.assertEqual(history.status_code, 200)
        self.assertContains(history, "Évolution dans le temps")
        self.assertContains(history, "1.2")
        self.assertContains(history, "1.3")
        self.assertContains(history, "<circle", html=False)
        self.assertContains(history, "class=\"lab-history-abnormal\"", html=False)

        notifications = self.client.get(reverse("laboratoire:doctor_notifications"))
        self.assertContains(notifications, "Valeur potentiellement critique")
        self.assertContains(notifications, "Résultat validé disponible")
        self.assertContains(notifications, "Échantillon rejeté")

        pdf = self.client.get(reverse(
            "laboratoire:doctor_report_pdf", args=[self.demande.pk],
        ))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF-1.4"))
        self.assertIn(b"1.2", pdf.content)

    def test_doctor_patient_history_is_limited_to_associated_patients(self):
        other_patient = User.objects.create_user(
            username="patient-not-associated-lab", ******, role=User.Role.PATIENT,
        )
        self.client.force_login(self.doctor)
        response = self.client.get(reverse(
            "laboratoire:doctor_patient_history", args=[other_patient.pk],
        ))
        self.assertEqual(response.status_code, 404)

    def test_only_lab_responsable_can_validate_for_their_team(self):
        team, _ = Group.objects.get_or_create(name="Équipe Laboratoire test")
        responsible_group, _ = Group.objects.get_or_create(
            name="Biologiste responsable",
        )
        laboratory_member = User.objects.create_user(
            username="laboratory-member-test", ******, role=User.Role.LABORATOIRE,
        )
        team.user_set.add(self.lab, laboratory_member)
        responsible_group.user_set.add(laboratory_member)
        self.assertFalse(laboratory_member.has_perm("laboratoire.valider_resultat"))
        result = enregistrer_resultat(
            analyse_demandee=self.analyse, prelevement=None, utilisateur=self.lab,
            donnees={"valeur": "0.94"},
        )

        self.client.force_login(laboratory_member)
        response = self.client.post(
            reverse("laboratoire:resultat_validate", args=[result.pk]),
        )
        self.assertRedirects(
            response,
            reverse("laboratoire:demande_detail", args=[self.demande.pk]),
        )
        result.refresh_from_db()
        self.assertEqual(result.statut, Resultat.Statut.VALIDE)
        self.assertEqual(result.valide_par, laboratory_member)
        signed_pdf = self.client.get(reverse(
            "laboratoire:doctor_report_pdf", args=[self.demande.pk],
        ))
        self.assertEqual(signed_pdf["Content-Type"], "application/pdf")
        self.assertIn(b"Biologiste validateur", signed_pdf.content)
        self.client.force_login(self.lab)
        other_request = DemandeAnalyse.objects.create(
            patient=self.patient,
            medecin=self.doctor,
            laboratoire=self.lab,
        )
        other_analysis = AnalyseDemandee.objects.create(
            demande=other_request,
            type_analyse=self.type_analyse,
        )
        unvalidated = enregistrer_resultat(
            analyse_demandee=other_analysis,
            prelevement=None,
            utilisateur=self.lab,
            donnees={"valeur": "0.96"},
        )
        with self.assertRaises(ValidationError):
            valider_resultat(resultat=unvalidated, utilisateur=self.lab)
        unrelated_laboratory = User.objects.create_user(
            username="laboratory-other-team", ******, role=User.Role.LABORATOIRE,
        )
        self.client.force_login(unrelated_laboratory)
        response = self.client.get(
            reverse("laboratoire:demande_detail", args=[self.demande.pk]),
        )
        self.assertRedirects(
            response,
            reverse("laboratoire:demande_list"),
            fetch_redirect_response=False,
        )

    def test_responsable_rejects_result_with_comment_and_operator_resubmits(self):
        responsible_group, _ = Group.objects.get_or_create(
            name="Biologiste responsable",
        )
        responsible_group.user_set.add(self.lab)
        result = enregistrer_resultat(
            analyse_demandee=self.analyse,
            prelevement=None,
            utilisateur=self.lab,
            donnees={"valeur": "0.9"},
        )
        self.client.force_login(self.lab)
        queue = self.client.get(reverse("laboratoire:validation_queue"))
        self.assertContains(queue, "Résultats à valider")
        response = self.client.post(
            reverse("laboratoire:resultat_reject", args=[result.pk]),
            {"commentaire": ""},
        )
        result.refresh_from_db()
        self.assertEqual(result.statut, Resultat.Statut.EN_ATTENTE_VALIDATION)
        self.assertContains(
            self.client.get(reverse("laboratoire:demande_list")),
            "Validation biologiste",
        )

        # Remove the responsable role to verify that operators cannot reject.
        responsible_group.user_set.remove(self.lab)
        response = self.client.post(
            reverse("laboratoire:resultat_reject", args=[result.pk]),
            {"commentaire": "Valeur à recontrôler"},
        )
        self.assertRedirects(response, reverse("laboratoire:demande_list"))
        result.refresh_from_db()
        self.assertNotEqual(result.statut, Resultat.Statut.REJETE)
        responsible_group.user_set.add(self.lab)
        response = self.client.post(
            reverse("laboratoire:resultat_reject", args=[result.pk]),
            {"commentaire": "Valeur à recontrôler"},
        )
        self.assertRedirects(response, reverse("laboratoire:validation_queue"))
        result.refresh_from_db()
        self.assertEqual(result.statut, Resultat.Statut.REJETE)
        self.assertEqual(result.commentaire_rejet, "Valeur à recontrôler")

        responsible_group.user_set.remove(self.lab)
        response = self.client.post(
            reverse("laboratoire:resultat_update", args=[result.pk]),
            {"valeur": "0.95", "unite": "g/L", "valeur_reference": "", "interpretation": "", "observation": ""},
        )
        self.assertRedirects(
            response,
            reverse("laboratoire:demande_detail", args=[self.demande.pk]),
        )
        result.refresh_from_db()
        self.assertEqual(result.statut, Resultat.Statut.EN_ATTENTE_VALIDATION)
        self.assertEqual(result.commentaire_rejet, "")

    def test_operator_queue_filters_and_sample_label_use_automatic_barcode(self):
        urgent = DemandeAnalyse.objects.create(
            patient=self.patient,
            medecin=self.doctor,
            laboratoire=self.lab,
            priorite=DemandeAnalyse.Priorite.URGENTE,
        )
        self.client.force_login(self.lab)
        response = self.client.get(
            reverse("laboratoire:demande_list"),
            {"priorite": DemandeAnalyse.Priorite.URGENTE, "q": self.patient.username},
        )
        self.assertContains(
            response,
            reverse("laboratoire:demande_detail", args=[urgent.pk]),
        )
        self.assertNotContains(
            response,
            reverse("laboratoire:demande_detail", args=[self.demande.pk]),
        )
        prelevement = Prelevement.objects.create(
            demande=urgent,
            type_prelevement=Prelevement.Type.SANG,
        )
        self.assertTrue(prelevement.code_prelevement.startswith("LAB-"))
        label = self.client.get(reverse(
            "laboratoire:prelevement_etiquette", args=[prelevement.pk],
        ))
        self.assertContains(label, prelevement.code_prelevement)
        self.assertContains(label, "<svg", html=False)

    def test_automatic_interpretation_distinguishes_reference_and_critical_values(self):
        self.type_analyse.seuil_critique_bas = Decimal("0.300")
        self.type_analyse.seuil_critique_haut = Decimal("2.000")
        self.type_analyse.save()
        result = Resultat.objects.create(
            analyse_demandee=self.analyse,
            valeur="0.5",
            saisi_par=self.lab,
        )
        self.assertEqual(result.interpretation_automatique, "Bas")
        result.valeur = "0.9"
        self.assertEqual(result.interpretation_automatique, "Normal")
        result.valeur = "1.2"
        self.assertEqual(result.interpretation_automatique, "Élevé")
        result.valeur = "2.1"
        self.assertEqual(result.interpretation_automatique, "Critique")

    def test_non_laboratory_user_cannot_validate(self):
        result = enregistrer_resultat(
            analyse_demandee=self.analyse, prelevement=None, utilisateur=self.lab,
            donnees={"valeur": "0.92"},
        )
        with self.assertRaises(ValidationError):
            valider_resultat(resultat=result, utilisateur=self.doctor)

    def test_history_displays_friendly_action_and_change_labels(self):
        HistoriqueAction.objects.create(
            utilisateur=self.doctor,
            type_action="DEMANDE_CREEE",
            objet_concerne="DemandeAnalyse",
            objet_id=self.demande.pk,
            details={
                "patient_id": self.patient.pk,
                "laboratoire_id": self.lab.pk,
                "priorite": "URGENTE",
                "analyses": [self.type_analyse.pk],
            },
        )
        self.client.force_login(self.lab)
        response = self.client.get(reverse("laboratoire:historique"))
        self.assertContains(response, "Demande créée")
        self.assertContains(response, "Laboratoire destinataire")
        self.assertContains(response, "Urgente")

    def test_technical_admin_cannot_validate_legacy_lab_results(self):
        dossier = DossierMedical.objects.create(
            patient=self.patient, numero_dossier="DM-LAB-TEST",
        )
        legacy_result = ResultatLaboratoire.objects.create(
            dossier=dossier,
            medecin_prescripteur=self.doctor,
            laboratoire=self.lab,
            type_analyse="Glycémie",
            reference="AN-LAB-TEST",
        )
        url = reverse("lab_update_resultat", args=[legacy_result.pk])
        self.client.force_login(self.admin)
        response = self.client.post(url, {"statut": "TRANSMIS", "valeurs": "0.9"})
        self.assertEqual(response.status_code, 403)
        legacy_result.refresh_from_db()
        self.assertEqual(legacy_result.statut, "EN_ATTENTE")

        self.client.force_login(self.lab)
        response = self.client.post(url, {"statut": "INVALID", "valeurs": "0.9"})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(url, {"statut": "DISPONIBLE", "valeurs": "0.9"})
        self.assertEqual(response.status_code, 200)
        legacy_result.refresh_from_db()
        self.assertEqual(legacy_result.statut, "DISPONIBLE")
        self.assertTrue(
            HistoriqueAction.objects.filter(
                objet_concerne="ResultatLaboratoire",
                objet_id=legacy_result.pk,
                type_action="RESULTAT_LEGACY_MODIFIE",
            ).exists()
        )

        unauthorized_lab = User.objects.create_user(
            username="legacy-lab-without-validator",
            ******,
            role=User.Role.LABORATOIRE,
        )
        unauthorized_dossier = DossierMedical.objects.create(
            patient=self.patient, numero_dossier="DM-LAB-UNAUTHORIZED",
        )
        unauthorized_result = ResultatLaboratoire.objects.create(
            dossier=unauthorized_dossier,
            medecin_prescripteur=self.doctor,
            laboratoire=unauthorized_lab,
            type_analyse="Glycémie",
            reference="AN-LAB-UNAUTHORIZED",
        )
        self.client.force_login(unauthorized_lab)
        self.assertFalse(unauthorized_lab.has_perm("laboratoire.valider_resultat"))
        response = self.client.post(
            reverse("lab_update_resultat", args=[unauthorized_result.pk]),
            {"statut": "DISPONIBLE", "valeurs": "0.9"},
        )
        self.assertEqual(response.status_code, 200)
        unauthorized_result.refresh_from_db()
        self.assertEqual(unauthorized_result.statut, "DISPONIBLE")
