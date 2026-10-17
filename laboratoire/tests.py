from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import (
    AssociationMedecinPatient,
    DossierMedical,
    ResultatLaboratoire,
    User,
)
from .models import (
    AnalyseDemandee,
    DemandeAnalyse,
    HistoriqueAction,
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
        valider_resultat(resultat=resultat, utilisateur=self.lab)
        resultat.refresh_from_db()
        self.assertEqual(resultat.statut, Resultat.Statut.VALIDE)
        self.assertEqual(resultat.valide_par, self.lab)
        self.assertIsNotNone(resultat.date_validation)
        self.assertEqual(self.demande.__class__.objects.get(pk=self.demande.pk).statut,
                         DemandeAnalyse.Statut.TERMINEE)
        self.assertTrue(HistoriqueAction.objects.filter(type_action="RESULTAT_VALIDE").exists())

    def test_correction_of_validated_result_requires_revalidation(self):
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

    def test_laboratory_member_can_validate_without_special_permission(self):
        team, _ = Group.objects.get_or_create(name="Équipe Laboratoire test")
        laboratory_member = User.objects.create_user(
            username="laboratory-member-test", ******, role=User.Role.LABORATOIRE,
        )
        team.user_set.add(self.lab, laboratory_member)
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
