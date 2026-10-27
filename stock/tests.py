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


# ==========================================================================
# Accessibilité (WCAG 2.1 AA) : vérifications automatiques du HTML produit
# ==========================================================================
from html.parser import HTMLParser


class _Audit(HTMLParser):
    """Relève les éléments utiles à l'audit d'accessibilité."""
    def __init__(self):
        super().__init__()
        self.headings, self.th, self.tables, self.captions = [], [], 0, 0
        self.labels_for, self.fields, self.roles, self.meters = set(), [], [], []
        self.imgs_sans_alt, self.buttons_sans_nom, self._btn = 0, 0, None
        self.skip_link = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.headings.append(int(tag[1]))
        elif tag == "th":
            self.th.append(a.get("scope"))
        elif tag == "table":
            self.tables += 1
        elif tag == "caption":
            self.captions += 1
        elif tag == "label" and a.get("for"):
            self.labels_for.add(a["for"])
        elif tag in ("input", "select", "textarea") and a.get("type") not in ("hidden", "submit"):
            self.fields.append(a)
        elif tag == "img" and "alt" not in a:
            self.imgs_sans_alt += 1
        elif tag == "meter":
            self.meters.append(a)
        elif tag == "a" and a.get("class") == "skip-link":
            self.skip_link = True
        if a.get("role"):
            self.roles.append(a["role"])


def audit(html):
    p = _Audit()
    p.feed(html)
    return p


def rapport_contraste(fg, bg):
    def lum(h):
        h = h.lstrip("#")
        c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    l1, l2 = sorted((lum(fg), lum(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


class AccessibiliteTests(TestCase):
    def setUp(self):
        self.labo = make_user("labo_a11y", User.Role.LABORATOIRE)
        self.p = Produit.objects.create(nom="Seringues", quantite=2, seuil_alerte=5)
        Produit.objects.create(nom="Masques", quantite=0, seuil_alerte=5)
        enregistrer_mouvement(produit=self.p, type_mouvement=Type.ENTREE, quantite=1, motif=Motif.ACHAT, utilisateur=self.labo)
        self.client.login(username="labo_a11y", password="pass12345")

    def pages(self):
        return [reverse("stock:dashboard"), reverse("stock:produit_list"), reverse("stock:mouvement_list"),
                reverse("stock:categorie_list"), reverse("stock:produit_detail", args=[self.p.pk]),
                reverse("stock:produit_create"), reverse("stock:mouvement_create", args=[self.p.pk, "sortie"])]

    def test_hierarchie_des_titres_sans_saut(self):
        for url in self.pages():
            h = audit(self.client.get(url).content.decode()).headings
            self.assertEqual(h[0], 1, f"{url} doit commencer par un h1 ({h})")
            self.assertEqual(h.count(1), 1, f"{url} : un seul h1 attendu ({h})")
            for prev, cur in zip(h, h[1:]):
                self.assertLessEqual(cur, prev + 1, f"{url} : saut de niveau de titre {prev}->{cur}")

    def test_tableaux_avec_legende_et_entetes_scopes(self):
        for url in self.pages():
            a = audit(self.client.get(url).content.decode())
            self.assertEqual(a.tables, a.captions, f"{url} : chaque tableau doit avoir une <caption>")
            self.assertTrue(all(s in ("col", "row") for s in a.th), f"{url} : <th> sans scope")

    def test_chaque_champ_a_un_label(self):
        for url in (reverse("stock:produit_create"), reverse("stock:mouvement_create", args=[self.p.pk, "entree"]),
                    reverse("stock:produit_list"), reverse("stock:mouvement_list")):
            a = audit(self.client.get(url).content.decode())
            for f in a.fields:
                self.assertTrue(f.get("id") in a.labels_for or f.get("aria-label"), f"{url} : champ sans label {f}")

    def test_lien_d_evitement_present(self):
        for url in self.pages():
            self.assertTrue(audit(self.client.get(url).content.decode()).skip_link, url)

    def test_alertes_annoncees_aux_lecteurs_d_ecran_et_lecture_vocale(self):
        r = self.client.get(reverse("stock:dashboard"))
        self.assertContains(r, 'role="alert"')
        self.assertContains(r, "1 produit en rupture")
        self.assertContains(r, 'id="btn-lire-alertes"')
        self.assertIn("Masques", r.context["lecture"])

    def test_jauge_de_stock_accessible(self):
        a = audit(self.client.get(reverse("stock:produit_detail", args=[self.p.pk])).content.decode())
        self.assertEqual(len(a.meters), 1)
        self.assertTrue(a.meters[0].get("aria-label") and a.meters[0].get("aria-valuetext"))

    def test_statut_jamais_indique_par_la_couleur_seule(self):
        r = self.client.get(reverse("stock:produit_list"))
        self.assertContains(r, "Rupture")
        self.assertContains(r, "Stock faible")

    def test_erreurs_de_formulaire_annoncees_et_champs_invalides(self):
        r = self.client.post(reverse("stock:mouvement_create", args=[self.p.pk, "sortie"]), {"quantite": 99, "motif": "UTILISATION"})
        html = r.content.decode()
        self.assertIn('id="error-summary"', html)
        self.assertIn('role="alert"', html)
        r = self.client.post(reverse("stock:produit_create"), {"nom": "", "unite": "UNITE", "seuil_alerte": 1})
        html = r.content.decode()
        self.assertIn('aria-invalid="true"', html)
        self.assertIn("id_nom_error", html)

    def test_validation_cote_client_coherente_avec_le_serveur(self):
        html = self.client.get(reverse("stock:mouvement_create", args=[self.p.pk, "sortie"])).content.decode()
        self.assertIn('max="3"', html)           # stock actuel = 2 + 1
        self.assertNotIn("novalidate", html)
        html = self.client.get(reverse("stock:produit_create")).content.decode()
        self.assertIn(f'min="{timezone.localdate().isoformat()}"', html)

    def test_contrastes_wcag_aa(self):
        """Couples texte/fond du module (ratio minimal 4,5:1 pour du texte normal)."""
        couples = {
            "pastille danger": ("#b91c1c", "#fee2e2"), "pastille attention": ("#92400e", "#fef3c7"),
            "pastille ok": ("#047857", "#d1fae5"), "pastille lecture seule": ("#475569", "#f1f5f9"),
            "texte atténué sur ligne rouge": ("#475569", "#fef2f2"), "pastille info": ("#0369a1", "#e0f2fe"),
            "texte atténué": ("#64748b", "#ffffff"), "texte principal": ("#0f172a", "#ffffff"),
            "lien d'évitement": ("#ffffff", "#0f172a"), "contraste élevé": ("#ffffff", "#000000"),
        }
        for nom, (fg, bg) in couples.items():
            self.assertGreaterEqual(rapport_contraste(fg, bg), 4.5, f"{nom} : {rapport_contraste(fg, bg):.2f}:1")
