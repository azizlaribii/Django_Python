from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Categorie, MouvementStock, Produit
from .services import StockError, enregistrer_mouvement, get_alertes

User = get_user_model()
Type, Motif = MouvementStock.Type, MouvementStock.Motif


def make_user(username, role):
    return User.objects.create_user(username=username, password="pass12345", role=role)


class ServiceTests(TestCase):
    def setUp(self):
        self.p = Produit.objects.create(nom="Gants", quantite=10, seuil_alerte=5)

    def test_entree_augmente_le_stock(self):
        m = enregistrer_mouvement(produit=self.p, type_mouvement=Type.ENTREE, quantite=5, motif=Motif.ACHAT)
        self.p.refresh_from_db()
        self.assertEqual(self.p.quantite, 15)
        self.assertEqual(m.stock_apres, 15)

    def test_sortie_diminue_le_stock(self):
        enregistrer_mouvement(produit=self.p, type_mouvement=Type.SORTIE, quantite=4, motif=Motif.UTILISATION)
        self.p.refresh_from_db()
        self.assertEqual(self.p.quantite, 6)

    def test_sortie_superieure_au_stock_refusee(self):
        with self.assertRaises(StockError):
            enregistrer_mouvement(produit=self.p, type_mouvement=Type.SORTIE, quantite=11, motif=Motif.UTILISATION)
        self.p.refresh_from_db()
        self.assertEqual(self.p.quantite, 10)
        self.assertEqual(MouvementStock.objects.count(), 0)

    def test_motif_incompatible_refuse(self):
        with self.assertRaises(StockError):
            enregistrer_mouvement(produit=self.p, type_mouvement=Type.ENTREE, quantite=1, motif=Motif.UTILISATION)

    def test_produit_perime_non_utilisable_mais_rebut_possible(self):
        Produit.objects.filter(pk=self.p.pk).update(date_peremption=timezone.localdate() - timedelta(days=1))
        self.p.refresh_from_db()
        with self.assertRaises(StockError):
            enregistrer_mouvement(produit=self.p, type_mouvement=Type.SORTIE, quantite=1, motif=Motif.UTILISATION)
        with self.assertRaises(StockError):
            enregistrer_mouvement(produit=self.p, type_mouvement=Type.ENTREE, quantite=1, motif=Motif.ACHAT)
        enregistrer_mouvement(produit=self.p, type_mouvement=Type.SORTIE, quantite=10, motif=Motif.PEREMPTION)
        self.p.refresh_from_db()
        self.assertEqual(self.p.quantite, 0)

    def test_reference_generee_automatiquement(self):
        self.assertEqual(self.p.reference, f"PRD-{self.p.pk:05d}")


class StatutTests(TestCase):
    def test_statuts_et_alertes(self):
        today = timezone.localdate()
        ok = Produit.objects.create(nom="OK", quantite=50, seuil_alerte=10, date_peremption=today + timedelta(days=365))
        rupture = Produit.objects.create(nom="Rupture", quantite=0, seuil_alerte=10)
        faible = Produit.objects.create(nom="Faible", quantite=3, seuil_alerte=10)
        bientot = Produit.objects.create(nom="Bientot", quantite=20, seuil_alerte=5, date_peremption=today + timedelta(days=10))
        expire = Produit.objects.create(nom="Expire", quantite=20, seuil_alerte=5, date_peremption=today - timedelta(days=2))

        self.assertEqual(ok.statuts[0][0], "normal")
        self.assertEqual(rupture.statuts[0][0], "rupture")
        self.assertEqual(faible.statuts[0][0], "faible")
        self.assertEqual(bientot.statuts[0][0], "bientot")
        self.assertEqual(expire.statuts[0][0], "expire")

        a = get_alertes()
        self.assertEqual([p.nom for p in a["rupture"]], ["Rupture"])
        self.assertEqual([p.nom for p in a["faible"]], ["Faible"])
        self.assertEqual([p.nom for p in a["bientot"]], ["Bientot"])
        self.assertEqual([p.nom for p in a["expire"]], ["Expire"])
        self.assertEqual(list(Produit.objects.normaux()), [ok])


class VueTests(TestCase):
    def setUp(self):
        self.labo = make_user("labo", User.Role.LABORATOIRE)
        self.docteur = make_user("doc", User.Role.DOCTEUR)
        self.patient = make_user("pat", User.Role.PATIENT)
        self.admin = make_user("adm", User.Role.ADMIN)
        self.produit = Produit.objects.create(nom="Seringues", quantite=20, seuil_alerte=5)

    def test_anonyme_redirige_vers_login(self):
        r = self.client.get(reverse("stock:dashboard"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("login", r.url)

    def test_patient_refuse(self):
        self.client.login(username="pat", password="pass12345")
        r = self.client.get(reverse("stock:produit_list"))
        self.assertRedirects(r, reverse("dashboard"), fetch_redirect_response=False)

    def test_docteur_lecture_seule(self):
        self.client.login(username="doc", password="pass12345")
        self.assertEqual(self.client.get(reverse("stock:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("stock:produit_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("stock:produit_detail", args=[self.produit.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("stock:produit_create")).status_code, 302)
        r = self.client.post(reverse("stock:mouvement_create", args=[self.produit.pk, "sortie"]),
                             {"quantite": 1, "motif": "UTILISATION"})
        self.assertEqual(r.status_code, 302)
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.quantite, 20)

    def test_labo_cree_produit_avec_stock_initial(self):
        self.client.login(username="labo", password="pass12345")
        cat = Categorie.objects.create(nom="Consommables")
        date = timezone.localdate() + timedelta(days=90)
        r = self.client.post(reverse("stock:produit_create"), {
            "nom": "Compresses", "categorie": cat.pk, "unite": "PAQUET", "quantite_initiale": 30,
            "seuil_alerte": 10, "date_peremption": date.isoformat(),
        })
        p = Produit.objects.get(nom="Compresses")
        self.assertRedirects(r, reverse("stock:produit_detail", args=[p.pk]))
        self.assertEqual(p.quantite, 30)
        self.assertEqual(p.date_peremption, date)
        self.assertEqual(p.mouvements.count(), 1)
        self.assertEqual(p.mouvements.first().utilisateur, self.labo)

    def test_date_peremption_passee_refusee_a_la_creation(self):
        self.client.login(username="labo", password="pass12345")
        hier = timezone.localdate() - timedelta(days=1)
        r = self.client.post(reverse("stock:produit_create"), {
            "nom": "Vieux", "unite": "UNITE", "quantite_initiale": 5, "seuil_alerte": 1,
            "date_peremption": hier.isoformat(),
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Produit.objects.filter(nom="Vieux").exists())

    def test_sortie_via_vue_et_erreur_stock_insuffisant(self):
        self.client.login(username="adm", password="pass12345")
        url = reverse("stock:mouvement_create", args=[self.produit.pk, "sortie"])
        self.client.post(url, {"quantite": 5, "motif": "UTILISATION"})
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.quantite, 15)
        r = self.client.post(url, {"quantite": 100, "motif": "UTILISATION"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Stock insuffisant")
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.quantite, 15)

    def test_suppression_conserve_l_historique(self):
        self.client.login(username="labo", password="pass12345")
        enregistrer_mouvement(produit=self.produit, type_mouvement=Type.ENTREE, quantite=1, motif=Motif.ACHAT)
        self.client.post(reverse("stock:produit_delete", args=[self.produit.pk]))
        self.produit.refresh_from_db()
        self.assertFalse(self.produit.actif)
        self.assertEqual(MouvementStock.objects.count(), 1)
        self.assertEqual(self.client.get(reverse("stock:produit_detail", args=[self.produit.pk])).status_code, 404)

    def test_pages_de_liste(self):
        self.client.login(username="labo", password="pass12345")
        for nom in ["produit_list", "mouvement_list", "categorie_list", "dashboard"]:
            r = self.client.get(reverse(f"stock:{nom}"))
            self.assertEqual(r.status_code, 200, nom)
        r = self.client.get(reverse("stock:produit_list"), {"statut": "faible", "q": "ser"})
        self.assertEqual(r.status_code, 200)


class AffichageSansUtilisateurTests(TestCase):
    def test_mouvement_sans_utilisateur_s_affiche(self):
        labo = make_user("labo2", User.Role.LABORATOIRE)
        p = Produit.objects.create(nom="Gants", quantite=0, seuil_alerte=1)
        enregistrer_mouvement(produit=p, type_mouvement=Type.ENTREE, quantite=3, motif=Motif.ACHAT, utilisateur=None)
        self.client.login(username="labo2", password="pass12345")
        for nom, args in [("dashboard", []), ("mouvement_list", []), ("produit_detail", [p.pk])]:
            r = self.client.get(reverse(f"stock:{nom}", args=args))
            self.assertEqual(r.status_code, 200, nom)
