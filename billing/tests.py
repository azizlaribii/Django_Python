from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from .models import Tarif, Facture, LigneFacture, Paiement

User = get_user_model()


def make_user(username, role, verified=False):
    return User.objects.create_user(username=username, password='pass12345',
                                    role=role, is_verified=verified)


class BaseCase(TestCase):
    def setUp(self):
        self.admin = make_user('admin1', 'ADMIN')
        self.doc = make_user('doc1', 'DOCTEUR', verified=True)
        self.doc_nv = make_user('doc2', 'DOCTEUR', verified=False)
        self.pat1 = make_user('pat1', 'PATIENT')
        self.pat2 = make_user('pat2', 'PATIENT')
        self.labo = make_user('labo1', 'LABORATOIRE')
        self.tarif = Tarif.objects.create(code='CONS', libelle='Consultation',
                                          categorie='CONSULTATION', prix=Decimal('50.000'))
        self.facture = Facture.objects.create(patient=self.pat1, medecin=self.doc)
        LigneFacture.objects.create(facture=self.facture, tarif=self.tarif,
                                    description='Consultation', quantite=2,
                                    prix_unitaire=Decimal('50.000'))

    def login(self, user):
        self.client.login(username=user.username, password='pass12345')


# ───────── Tests unitaires (modèles et logique métier) ─────────
class ModelTests(BaseCase):
    def test_numero_genere(self):
        self.assertTrue(self.facture.numero.startswith('FAC-'))

    def test_numeros_uniques_et_croissants(self):
        f2 = Facture.objects.create(patient=self.pat1)
        self.assertNotEqual(self.facture.numero, f2.numero)

    def test_total_ligne(self):
        self.assertEqual(self.facture.lignes.first().total, Decimal('100.000'))

    def test_totaux_avec_remise_et_tva(self):
        self.facture.remise = Decimal('10.000')
        self.facture.tva = Decimal('19.00')
        self.facture.save()
        # (100 - 10) = 90 ; TVA 17.100 ; TTC 107.100
        self.assertEqual(self.facture.total_ttc, Decimal('107.100'))

    def test_statut_automatique(self):
        Paiement.objects.create(facture=self.facture, montant=Decimal('40.000'))
        self.facture.refresh_from_db()
        self.assertEqual(self.facture.statut, 'PARTIELLE')
        self.assertEqual(self.facture.reste_a_payer(), Decimal('60.000'))
        Paiement.objects.create(facture=self.facture, montant=self.facture.reste_a_payer())
        self.facture.refresh_from_db()
        self.assertEqual(self.facture.statut, 'PAYEE')

    def test_facture_annulee_garde_son_statut(self):
        self.facture.statut = 'ANNULEE'
        self.facture.save()
        self.facture.mettre_a_jour_statut()
        self.facture.refresh_from_db()
        self.assertEqual(self.facture.statut, 'ANNULEE')


# ───────── Tests d'intégration : permissions ─────────
class PermissionTests(BaseCase):
    def test_anonyme_redirige(self):
        self.assertEqual(self.client.get(reverse('facture_list')).status_code, 302)

    def test_admin_voit_tout(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse('facture_list')).status_code, 200)

    def test_patient_voit_la_sienne(self):
        self.login(self.pat1)
        r = self.client.get(reverse('facture_detail', args=[self.facture.pk]))
        self.assertEqual(r.status_code, 200)

    def test_patient_autre_404(self):
        self.login(self.pat2)
        r = self.client.get(reverse('facture_detail', args=[self.facture.pk]))
        self.assertEqual(r.status_code, 404)

    def test_docteur_non_certifie_403(self):
        self.login(self.doc_nv)
        self.assertEqual(self.client.get(reverse('facture_list')).status_code, 403)

    def test_labo_403(self):
        self.login(self.labo)
        self.assertEqual(self.client.get(reverse('facture_list')).status_code, 403)

    def test_patient_ne_cree_pas(self):
        self.login(self.pat1)
        self.assertEqual(self.client.get(reverse('facture_create')).status_code, 403)

    def test_tarifs_admin_seulement(self):
        self.login(self.doc)
        self.assertEqual(self.client.get(reverse('tarif_list')).status_code, 403)
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse('tarif_list')).status_code, 200)

    def test_pdf_autre_patient_404(self):
        self.login(self.pat2)
        r = self.client.get(reverse('facture_pdf', args=[self.facture.pk]))
        self.assertEqual(r.status_code, 404)

    def test_historique_autre_patient_404(self):
        self.login(self.pat2)
        r = self.client.get(reverse('patient_historique', args=[self.pat1.pk]))
        self.assertEqual(r.status_code, 404)

    def test_docteur_ne_voit_pas_facture_d_un_autre_medecin(self):
        autre = make_user('doc3', 'DOCTEUR', verified=True)
        self.login(autre)
        r = self.client.get(reverse('facture_detail', args=[self.facture.pk]))
        self.assertEqual(r.status_code, 404)


# ───────── Tests d'intégration : workflow ─────────
class WorkflowTests(BaseCase):
    def test_creation_facture_par_docteur(self):
        self.login(self.doc)
        data = {
            'patient': self.pat2.pk, 'remise': '0', 'tva': '19',
            'lignes-TOTAL_FORMS': '1', 'lignes-INITIAL_FORMS': '0',
            'lignes-MIN_NUM_FORMS': '1', 'lignes-MAX_NUM_FORMS': '1000',
            'lignes-0-tarif': self.tarif.pk, 'lignes-0-description': 'Consultation',
            'lignes-0-reference': '', 'lignes-0-quantite': '1',
            'lignes-0-prix_unitaire': '50.000',
        }
        self.client.post(reverse('facture_create'), data)
        nouvelle = Facture.objects.get(patient=self.pat2)
        self.assertEqual(nouvelle.medecin, self.doc)
        self.assertEqual(nouvelle.lignes.count(), 1)

    def test_remise_negative_refusee(self):
        self.login(self.admin)
        data = {
            'patient': self.pat2.pk, 'medecin': self.doc.pk, 'remise': '-5', 'tva': '0',
            'lignes-TOTAL_FORMS': '1', 'lignes-INITIAL_FORMS': '0',
            'lignes-MIN_NUM_FORMS': '1', 'lignes-MAX_NUM_FORMS': '1000',
            'lignes-0-tarif': self.tarif.pk, 'lignes-0-description': 'X',
            'lignes-0-reference': '', 'lignes-0-quantite': '1',
            'lignes-0-prix_unitaire': '10',
        }
        r = self.client.post(reverse('facture_create'), data)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Facture.objects.filter(patient=self.pat2).exists())

    def test_paiement_partiel_puis_total(self):
        self.login(self.doc)
        url = reverse('paiement_create', args=[self.facture.pk])
        self.client.post(url, {'montant': '40', 'mode': 'ESPECES'})
        self.facture.refresh_from_db()
        self.assertEqual(self.facture.statut, 'PARTIELLE')
        self.client.post(url, {'montant': '60', 'mode': 'CARTE'})
        self.facture.refresh_from_db()
        self.assertEqual(self.facture.statut, 'PAYEE')

    def test_paiement_depasse_refuse(self):
        self.login(self.doc)
        r = self.client.post(reverse('paiement_create', args=[self.facture.pk]),
                             {'montant': '999999', 'mode': 'ESPECES'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.facture.paiements.count(), 0)

    def test_facture_avec_paiement_non_modifiable(self):
        Paiement.objects.create(facture=self.facture, montant=Decimal('10.000'))
        self.login(self.doc)
        r = self.client.get(reverse('facture_update', args=[self.facture.pk]))
        self.assertRedirects(r, reverse('facture_detail', args=[self.facture.pk]))

    def test_annulation_en_post_seulement(self):
        self.login(self.admin)
        url = reverse('facture_cancel', args=[self.facture.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.facture.refresh_from_db()
        self.assertEqual(self.facture.statut, 'ANNULEE')

    def test_pdf_ok(self):
        self.login(self.pat1)
        r = self.client.get(reverse('facture_pdf', args=[self.facture.pk]))
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_historique_patient(self):
        self.login(self.pat1)
        r = self.client.get(reverse('mon_historique'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['total_facture'], Decimal('100.000'))