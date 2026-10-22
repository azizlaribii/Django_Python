from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import Creneau, RendezVous
from .services import RendezVousError

User = get_user_model()
Statut = RendezVous.Statut


def make_user(username, role, **extra):
    return User.objects.create_user(username=username, password="pass12345", role=role, **extra)


def make_creneau(medecin, dans_heures=48, duree=30):
    debut = timezone.now().replace(second=0, microsecond=0) + timedelta(hours=dans_heures)
    return Creneau.objects.create(medecin=medecin, debut=debut, fin=debut + timedelta(minutes=duree))


class BaseRdvTest(TestCase):
    def setUp(self):
        self.doc = make_user("doc", User.Role.DOCTEUR, first_name="Sami", last_name="Ben Ali")
        self.doc2 = make_user("doc2", User.Role.DOCTEUR, last_name="Trabelsi")
        self.pat = make_user("pat", User.Role.PATIENT, first_name="Amel", last_name="Haddad")
        self.pat2 = make_user("pat2", User.Role.PATIENT)
        self.admin = make_user("adm", User.Role.ADMIN)
        self.lab = make_user("lab", User.Role.LABORATOIRE)
        self.creneau = make_creneau(self.doc)


class ReservationServiceTests(BaseRdvTest):
    def test_patient_reserve_en_attente(self):
        rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="Contrôle", par=self.pat)
        self.assertEqual(rdv.statut, Statut.EN_ATTENTE)
        self.assertEqual(rdv.medecin, self.doc)
        self.assertFalse(Creneau.objects.get(pk=self.creneau.pk).est_disponible)

    def test_medecin_reserve_confirme_directement(self):
        rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="Suivi", par=self.doc)
        self.assertEqual(rdv.statut, Statut.CONFIRME)
        self.assertIsNotNone(rdv.date_confirmation)

    def test_double_reservation_refusee(self):
        services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)
        with self.assertRaisesMessage(RendezVousError, "déjà réservé"):
            services.reserver(creneau=self.creneau, patient=self.pat2, motif="B", par=self.pat2)
        self.assertEqual(RendezVous.objects.count(), 1)

    def test_contrainte_base_de_donnees_double_reservation(self):
        RendezVous.objects.create(creneau=self.creneau, patient=self.pat, medecin=self.doc, motif="A")
        with self.assertRaises(IntegrityError), transaction.atomic():
            RendezVous.objects.create(creneau=self.creneau, patient=self.pat2, medecin=self.doc, motif="B")

    def test_patient_ne_peut_pas_avoir_deux_rdv_simultanes(self):
        autre = Creneau.objects.create(
            medecin=self.doc2, debut=self.creneau.debut + timedelta(minutes=15),
            fin=self.creneau.fin + timedelta(minutes=15),
        )
        services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)
        with self.assertRaisesMessage(RendezVousError, "déjà un rendez-vous"):
            services.reserver(creneau=autre, patient=self.pat, motif="B", par=self.pat)

    def test_creneau_passe_ou_bloque_refuse(self):
        passe = make_creneau(self.doc, dans_heures=-3)
        with self.assertRaises(RendezVousError):
            services.reserver(creneau=passe, patient=self.pat, motif="A", par=self.pat)
        self.creneau.est_bloque = True
        self.creneau.save()
        with self.assertRaises(RendezVousError):
            services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)

    def test_patient_ne_reserve_pas_pour_un_autre(self):
        with self.assertRaises(RendezVousError):
            services.reserver(creneau=self.creneau, patient=self.pat2, motif="A", par=self.pat)

    def test_medecin_ne_reserve_que_ses_creneaux(self):
        with self.assertRaises(RendezVousError):
            services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.doc2)

    def test_motif_obligatoire(self):
        with self.assertRaises(RendezVousError):
            services.reserver(creneau=self.creneau, patient=self.pat, motif="  ", par=self.pat)

    def test_annulation_libere_le_creneau(self):
        rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)
        services.annuler(rdv, par=self.pat, motif="Empêchement")
        rdv.refresh_from_db()
        self.assertEqual(rdv.statut, Statut.ANNULE)
        self.assertEqual(rdv.annule_par, self.pat)
        # Le créneau est de nouveau réservable par quelqu'un d'autre.
        rdv2 = services.reserver(creneau=self.creneau, patient=self.pat2, motif="B", par=self.pat2)
        self.assertEqual(rdv2.statut, Statut.EN_ATTENTE)

    def test_patient_ne_peut_pas_annuler_trop_tard(self):
        proche = make_creneau(self.doc, dans_heures=1)
        rdv = services.reserver(creneau=proche, patient=self.pat, motif="A", par=self.pat)
        with self.assertRaisesMessage(RendezVousError, "Annulation en ligne impossible"):
            services.annuler(rdv, par=self.pat)
        services.annuler(rdv, par=self.doc)  # le médecin, lui, peut toujours annuler
        self.assertEqual(rdv.statut, Statut.ANNULE)

    def test_confirmation_par_le_bon_medecin(self):
        rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)
        with self.assertRaises(RendezVousError):
            services.confirmer(rdv, par=self.doc2)
        with self.assertRaises(RendezVousError):
            services.confirmer(rdv, par=self.pat)
        services.confirmer(rdv, par=self.doc)
        self.assertEqual(rdv.statut, Statut.CONFIRME)

    def test_cloture_seulement_apres_le_debut(self):
        rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.doc)
        with self.assertRaises(RendezVousError):
            services.cloturer(rdv, par=self.doc, statut=Statut.TERMINE)
        rdv2 = RendezVous.objects.create(
            creneau=make_creneau(self.doc, dans_heures=-1), patient=self.pat2, medecin=self.doc,
            motif="B", statut=Statut.CONFIRME,
        )
        services.cloturer(rdv2, par=self.doc, statut=Statut.ABSENT, notes="Non venu")
        self.assertEqual(rdv2.statut, Statut.ABSENT)

    def test_signal_emis(self):
        from .signals import rdv_statut_change
        recus = []
        def ecouteur(sender, rdv, ancien_statut, par, **kw):
            recus.append((rdv.statut, ancien_statut))
        rdv_statut_change.connect(ecouteur)
        try:
            with self.captureOnCommitCallbacks(execute=True):
                rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)
            with self.captureOnCommitCallbacks(execute=True):
                services.confirmer(rdv, par=self.doc)
        finally:
            rdv_statut_change.disconnect(ecouteur)
        self.assertEqual(recus, [(Statut.EN_ATTENTE, None), (Statut.CONFIRME, Statut.EN_ATTENTE)])


class CreneauServiceTests(BaseRdvTest):
    def _lundi_prochain(self):
        d = timezone.localdate() + timedelta(days=7)
        return d - timedelta(days=d.weekday())

    def test_generation_avec_pause(self):
        lundi = self._lundi_prochain()
        crees, ignores = services.generer_creneaux(
            medecin=self.doc2, date_debut=lundi, date_fin=lundi + timedelta(days=6), jours=[0, 2],
            heure_debut=time(9, 0), heure_fin=time(12, 0), duree_minutes=30,
            pause_debut=time(10, 0), pause_fin=time(10, 30),
        )
        # 9:00, 9:30, 10:30, 11:00, 11:30 = 5 créneaux × 2 jours
        self.assertEqual((crees, ignores), (10, 0))
        heures = sorted({timezone.localtime(c.debut).strftime("%H:%M") for c in Creneau.objects.filter(medecin=self.doc2)})
        self.assertEqual(heures, ["09:00", "09:30", "10:30", "11:00", "11:30"])

    def test_generation_sans_doublon(self):
        lundi = self._lundi_prochain()
        args = dict(medecin=self.doc2, date_debut=lundi, date_fin=lundi, jours=[0],
                    heure_debut=time(9, 0), heure_fin=time(10, 0), duree_minutes=30)
        self.assertEqual(services.generer_creneaux(**args), (2, 0))
        self.assertEqual(services.generer_creneaux(**args), (0, 2))

    def test_chevauchement_detecte(self):
        from django.core.exceptions import ValidationError
        c = Creneau(medecin=self.doc, debut=self.creneau.debut + timedelta(minutes=10),
                    fin=self.creneau.fin + timedelta(minutes=10))
        with self.assertRaises(ValidationError):
            c.full_clean()

    def test_blocage_et_suppression(self):
        services.basculer_blocage(self.creneau, par=self.doc)
        self.assertTrue(self.creneau.est_bloque)
        with self.assertRaises(RendezVousError):
            services.basculer_blocage(self.creneau, par=self.doc2)
        services.supprimer_creneau(self.creneau, par=self.doc)
        self.assertFalse(Creneau.objects.exists())

    def test_creneau_avec_historique_non_supprimable(self):
        rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)
        services.annuler(rdv, par=self.pat)
        with self.assertRaises(RendezVousError):
            services.supprimer_creneau(self.creneau, par=self.doc)


class VuesTests(BaseRdvTest):
    def login(self, user):
        self.client.login(username=user.username, password="pass12345")

    def test_pages_accessibles_par_role(self):
        rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)
        pages = ["rdv_list", "calendrier", "reserver"]
        for user in (self.pat, self.doc, self.admin):
            self.login(user)
            for nom in pages:
                self.assertEqual(self.client.get(reverse(f"rendezvous:{nom}")).status_code, 200, (user, nom))
            if user is not self.pat:
                for nom in ("creneau_list", "creneau_ajouter", "creneau_generer"):
                    self.assertEqual(self.client.get(reverse(f"rendezvous:{nom}")).status_code, 200, (user, nom))
            self.assertEqual(self.client.get(reverse("rendezvous:rdv_detail", args=[rdv.pk])).status_code, 200)
        self.login(self.admin)
        r = self.client.get(reverse("rendezvous:calendrier"), {"medecin": self.doc.pk, "semaine": self.creneau.debut.date()})
        self.assertContains(r, "Amel Haddad")

    def test_laboratoire_refuse(self):
        self.login(self.lab)
        r = self.client.get(reverse("rendezvous:rdv_list"))
        self.assertRedirects(r, reverse("dashboard"), fetch_redirect_response=False)

    def test_patient_ne_gere_pas_les_creneaux(self):
        self.login(self.pat)
        r = self.client.get(reverse("rendezvous:creneau_list"))
        self.assertEqual(r.status_code, 302)

    def test_anonyme_redirige_vers_login(self):
        r = self.client.get(reverse("rendezvous:rdv_list"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r.url)

    def test_rdv_d_un_autre_patient_invisible(self):
        rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)
        self.login(self.pat2)
        self.assertEqual(self.client.get(reverse("rendezvous:rdv_detail", args=[rdv.pk])).status_code, 404)
        self.login(self.doc2)
        self.assertEqual(self.client.get(reverse("rendezvous:rdv_detail", args=[rdv.pk])).status_code, 404)

    def test_parcours_reservation_patient(self):
        self.login(self.pat)
        r = self.client.get(reverse("rendezvous:reserver"), {"medecin": self.doc.pk, "semaine": self.creneau.debut.date()})
        self.assertContains(r, reverse("rendezvous:reserver_creneau", args=[self.creneau.pk]))
        r = self.client.post(reverse("rendezvous:reserver_creneau", args=[self.creneau.pk]), {"motif": "Fièvre"})
        rdv = RendezVous.objects.get()
        self.assertRedirects(r, reverse("rendezvous:rdv_detail", args=[rdv.pk]))
        self.assertEqual((rdv.patient, rdv.statut), (self.pat, Statut.EN_ATTENTE))
        # Le créneau n'est plus proposé.
        r = self.client.get(reverse("rendezvous:reserver_creneau", args=[self.creneau.pk]))
        self.assertEqual(r.status_code, 302)

    def test_parcours_medecin_confirme_puis_patient_annule(self):
        rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)
        self.login(self.doc)
        self.client.post(reverse("rendezvous:rdv_confirmer", args=[rdv.pk]))
        rdv.refresh_from_db()
        self.assertEqual(rdv.statut, Statut.CONFIRME)
        self.login(self.pat)
        self.client.post(reverse("rendezvous:rdv_annuler", args=[rdv.pk]), {"motif_annulation": "Voyage"})
        rdv.refresh_from_db()
        self.assertEqual((rdv.statut, rdv.motif_annulation), (Statut.ANNULE, "Voyage"))

    def test_actions_en_get_refusees(self):
        rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)
        self.login(self.doc)
        self.assertEqual(self.client.get(reverse("rendezvous:rdv_confirmer", args=[rdv.pk])).status_code, 405)

    def test_generation_par_formulaire(self):
        self.login(self.doc2)
        lundi = timezone.localdate() + timedelta(days=7)
        lundi -= timedelta(days=lundi.weekday())
        r = self.client.post(reverse("rendezvous:creneau_generer"), {
            "date_debut": lundi, "date_fin": lundi + timedelta(days=4), "jours": [0, 1, 2, 3, 4],
            "heure_debut": "08:00", "heure_fin": "10:00", "duree_minutes": 30,
            "pause_debut": "", "pause_fin": "",
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Creneau.objects.filter(medecin=self.doc2).count(), 20)

    def test_filtres_liste(self):
        services.reserver(creneau=self.creneau, patient=self.pat, motif="Migraine", par=self.pat)
        c2 = make_creneau(self.doc, dans_heures=72)
        services.reserver(creneau=c2, patient=self.pat2, motif="Vaccin", par=self.doc)
        self.login(self.admin)
        r = self.client.get(reverse("rendezvous:rdv_list"), {"statut": "CONFIRME"})
        self.assertContains(r, "Vaccin")
        self.assertNotContains(r, "Migraine")
        r = self.client.get(reverse("rendezvous:rdv_list"), {"q": "Haddad"})
        self.assertContains(r, "Migraine")
        self.assertNotContains(r, "Vaccin")

    def test_api_creneaux_disponibles(self):
        self.login(self.pat)
        jour = timezone.localtime(self.creneau.debut).date()
        r = self.client.get(reverse("rendezvous:api_creneaux_disponibles"), {"medecin": self.doc.pk, "date": jour})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c["id"] for c in r.json()["creneaux"]], [self.creneau.pk])
        r = self.client.get(reverse("rendezvous:api_creneaux_disponibles"))
        self.assertEqual(r.status_code, 400)


# ==========================================================================
# Modification (Update du CRUD) : créneau et rendez-vous
# ==========================================================================
class ModificationTests(BaseRdvTest):
    def test_modifier_horaire_creneau_libre(self):
        debut = self.creneau.debut + timedelta(hours=2)
        services.modifier_creneau(self.creneau, par=self.doc, debut=debut, fin=debut + timedelta(minutes=45), note="Salle 2")
        self.creneau.refresh_from_db()
        self.assertEqual((self.creneau.debut, self.creneau.duree_minutes, self.creneau.note), (debut, 45, "Salle 2"))

    def test_horaire_creneau_reserve_non_modifiable_mais_note_oui(self):
        services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)
        with self.assertRaisesMessage(RendezVousError, "déplacez d'abord"):
            services.modifier_creneau(self.creneau, par=self.doc, debut=self.creneau.debut + timedelta(hours=1),
                                      fin=self.creneau.fin + timedelta(hours=1))
        services.modifier_creneau(self.creneau, par=self.doc, debut=self.creneau.debut, fin=self.creneau.fin, note="RAS")
        self.assertEqual(Creneau.objects.get(pk=self.creneau.pk).note, "RAS")

    def test_modification_creneau_chevauchement_refuse(self):
        autre = make_creneau(self.doc, dans_heures=50)
        with self.assertRaises(RendezVousError):
            services.modifier_creneau(autre, par=self.doc, debut=self.creneau.debut, fin=self.creneau.fin)

    def test_modification_creneau_par_autre_medecin_refusee(self):
        with self.assertRaises(RendezVousError):
            services.modifier_creneau(self.creneau, par=self.doc2, debut=self.creneau.debut, fin=self.creneau.fin)

    def test_deplacer_par_patient_repasse_en_attente(self):
        rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.doc)
        self.assertEqual(rdv.statut, Statut.CONFIRME)
        nouveau = make_creneau(self.doc, dans_heures=72)
        services.deplacer(rdv, nouveau_creneau=nouveau, par=self.pat, motif="Contrôle")
        rdv.refresh_from_db()
        self.assertEqual((rdv.creneau, rdv.statut, rdv.motif), (nouveau, Statut.EN_ATTENTE, "Contrôle"))
        self.assertTrue(Creneau.objects.get(pk=self.creneau.pk).est_disponible)  # l'ancien créneau est libéré

    def test_deplacer_par_medecin_reste_confirme(self):
        rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)
        services.deplacer(rdv, nouveau_creneau=make_creneau(self.doc, dans_heures=72), par=self.doc)
        self.assertEqual(rdv.statut, Statut.CONFIRME)

    def test_deplacer_vers_creneau_pris_ou_autre_medecin_refuse(self):
        rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)
        pris = make_creneau(self.doc, dans_heures=72)
        services.reserver(creneau=pris, patient=self.pat2, motif="B", par=self.pat2)
        with self.assertRaisesMessage(RendezVousError, "déjà réservé"):
            services.deplacer(rdv, nouveau_creneau=pris, par=self.pat)
        with self.assertRaisesMessage(RendezVousError, "même médecin"):
            services.deplacer(rdv, nouveau_creneau=make_creneau(self.doc2, dans_heures=80), par=self.pat)

    def test_patient_ne_deplace_pas_trop_tard(self):
        rdv = services.reserver(creneau=make_creneau(self.doc, dans_heures=1), patient=self.pat, motif="A", par=self.pat)
        with self.assertRaisesMessage(RendezVousError, "Modification en ligne impossible"):
            services.deplacer(rdv, nouveau_creneau=make_creneau(self.doc, dans_heures=72), par=self.pat)

    def test_vue_deplacer(self):
        rdv = services.reserver(creneau=self.creneau, patient=self.pat, motif="A", par=self.pat)
        nouveau = make_creneau(self.doc, dans_heures=60)
        self.client.login(username="pat", password="pass12345")
        url = reverse("rendezvous:rdv_deplacer", args=[rdv.pk])
        r = self.client.get(url, {"semaine": timezone.localtime(nouveau.debut).date()})
        self.assertContains(r, f'value="{nouveau.pk}"')
        r = self.client.post(url, {"creneau": nouveau.pk, "motif": "Nouveau motif"})
        self.assertRedirects(r, reverse("rendezvous:rdv_detail", args=[rdv.pk]))
        rdv.refresh_from_db()
        self.assertEqual((rdv.creneau_id, rdv.motif), (nouveau.pk, "Nouveau motif"))
        # Un autre patient ne peut pas modifier ce rendez-vous.
        self.client.login(username="pat2", password="pass12345")
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_vue_modifier_creneau(self):
        self.client.login(username="doc", password="pass12345")
        url = reverse("rendezvous:creneau_modifier", args=[self.creneau.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        d = timezone.localtime(self.creneau.debut)
        r = self.client.post(url, {"date": d.date(), "heure_debut": "07:00", "heure_fin": "07:20", "note": "Tôt"})
        self.assertRedirects(r, reverse("rendezvous:creneau_list"))
        self.assertEqual(timezone.localtime(Creneau.objects.get(pk=self.creneau.pk).debut).hour, 7)
        self.client.login(username="doc2", password="pass12345")
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_validation_cote_client_presente(self):
        """Les formulaires ne désactivent plus la validation HTML5 et marquent les champs obligatoires."""
        self.client.login(username="pat", password="pass12345")
        r = self.client.get(reverse("rendezvous:reserver_creneau", args=[self.creneau.pk]))
        self.assertNotContains(r, "novalidate")
        self.assertContains(r, 'name="motif"')
        self.assertContains(r, "required")


# ==========================================================================
# IA : suggestion de spécialité
# ==========================================================================
class IATests(BaseRdvTest):
    def test_suggestions_pertinentes(self):
        from .ia.classifieur import suggerer
        cas = {
            "douleur dans la poitrine en montant les escaliers": "Cardiologie",
            "mon bébé de 6 mois a de la fièvre": "Pédiatrie",
            "plaques rouges qui grattent sur la peau": "Dermatologie",
            "je vois flou de loin": "Ophtalmologie",
        }
        for motif, attendu in cas.items():
            r = suggerer(motif)
            self.assertEqual(r["suggestions"][0]["specialite"], attendu, motif)
            self.assertEqual(len(r["suggestions"]), 3)
            self.assertAlmostEqual(sum(s["probabilite"] for s in r["suggestions"]) <= 1.0001, True)

    def test_motif_trop_court(self):
        from .ia.classifieur import suggerer
        with self.assertRaises(ValueError):
            suggerer("a")

    def test_temps_de_reponse(self):
        from .ia.classifieur import suggerer
        suggerer("échauffement")  # premier appel : chargement du modèle
        r = suggerer("toux sèche depuis deux semaines")
        self.assertLess(r["temps_ms"], 200)

    def test_api_suggestion(self):
        from accounts.models import DoctorProfile
        DoctorProfile.objects.filter(user=self.doc).update(specialite="Cardiologie")
        self.client.login(username="pat", password="pass12345")
        url = reverse("rendezvous:api_suggestion_specialite")
        r = self.client.get(url, {"motif": "palpitations et douleur thoracique"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["suggestions"][0]["specialite"], "Cardiologie")
        self.assertEqual([m["id"] for m in data["suggestions"][0]["medecins"]], [self.doc.pk])
        self.assertTrue(data["suggestions"][0]["medecins"][0]["a_des_creneaux"])
        self.assertEqual(self.client.get(url, {"motif": ""}).status_code, 400)

    def test_api_erreur_modele_geree(self):
        from unittest import mock
        self.client.login(username="pat", password="pass12345")
        with mock.patch("rendezvous.ia.classifieur.get_modele", side_effect=OSError("fichier absent")):
            r = self.client.get(reverse("rendezvous:api_suggestion_specialite"), {"motif": "toux"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("indisponible", r.json()["erreur"])

    def test_api_reservee_aux_utilisateurs_connectes(self):
        r = self.client.get(reverse("rendezvous:api_suggestion_specialite"), {"motif": "toux"})
        self.assertEqual(r.status_code, 302)
        self.client.login(username="lab", password="pass12345")
        r = self.client.get(reverse("rendezvous:api_suggestion_specialite"), {"motif": "toux"})
        self.assertEqual(r.status_code, 302)

    def test_page_performance(self):
        self.client.login(username="doc", password="pass12345")
        r = self.client.get(reverse("rendezvous:ia_performance"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Matrice de confusion")
        self.client.login(username="pat", password="pass12345")
        self.assertEqual(self.client.get(reverse("rendezvous:ia_performance")).status_code, 404)

    def test_evaluation_sans_fuite_de_donnees(self):
        """Les motifs du test indépendant ne figurent pas dans les données d'entraînement."""
        from .ia.classifieur import FICHIER_TEST_INDEPENDANT, charger_donnees, normaliser
        entrainement = {normaliser(t) for t in charger_donnees()[0]}
        test = {normaliser(t) for t in charger_donnees(FICHIER_TEST_INDEPENDANT)[0]}
        self.assertFalse(entrainement & test)


class PagesErreurTests(TestCase):
    def test_page_404_personnalisee(self):
        r = self.client.get("/rendez-vous/page-qui-n-existe-pas/")
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "Page introuvable", status_code=404)


class EvaluationIATests(TestCase):
    def test_evaluation_complete(self):
        """L'évaluation produit des métriques cohérentes et bat largement la référence naïve."""
        from .ia.classifieur import evaluer
        m = evaluer(n_mesures_latence=20)
        for cle in ("f1_macro", "accuracy", "top3_accuracy", "cv_f1_moyenne", "latence_ms_moyenne"):
            self.assertIn(cle, m)
        self.assertEqual(len(m["matrice_confusion"]), m["nb_classes"])
        ind = m["test_independant"]
        self.assertGreater(ind["f1_macro"], m["f1_reference_naive"] + 0.4)
        self.assertGreaterEqual(ind["top3_accuracy"], ind["accuracy"])
        self.assertGreater(ind["f1_macro"], ind["f1_sans_lexique"])  # le lexique apporte un gain mesurable
