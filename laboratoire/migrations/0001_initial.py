import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0002_dossiermedical_examenmedical_observationmedicale_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="DemandeAnalyse",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date_demande", models.DateTimeField(default=django.utils.timezone.now, verbose_name="Date de prescription")),
                ("priorite", models.CharField(choices=[("NORMALE", "Normale"), ("HAUTE", "Haute"), ("URGENTE", "Urgente")], default="NORMALE", max_length=10, verbose_name="Priorité")),
                ("statut", models.CharField(choices=[("EN_ATTENTE", "En attente"), ("EN_COURS", "En cours"), ("TERMINEE", "Terminée"), ("ANNULEE", "Annulée")], default="EN_ATTENTE", max_length=12, verbose_name="Statut")),
                ("commentaire", models.TextField(blank=True, verbose_name="Commentaire")),
                ("cree_par", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="demandes_analyses_creees", to=settings.AUTH_USER_MODEL, verbose_name="Créée par")),
                ("laboratoire", models.ForeignKey(blank=True, limit_choices_to={"role": "LABORATOIRE"}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="demandes_laboratoire", to=settings.AUTH_USER_MODEL, verbose_name="Laboratoire destinataire")),
                ("medecin", models.ForeignKey(limit_choices_to={"role": "DOCTEUR"}, on_delete=django.db.models.deletion.PROTECT, related_name="demandes_prescrites", to=settings.AUTH_USER_MODEL, verbose_name="Médecin prescripteur")),
                ("patient", models.ForeignKey(limit_choices_to={"role": "PATIENT"}, on_delete=django.db.models.deletion.PROTECT, related_name="demandes_analyses", to=settings.AUTH_USER_MODEL, verbose_name="Patient")),
            ],
            options={"verbose_name": "Demande d’analyse", "verbose_name_plural": "Demandes d’analyses", "ordering": ["-date_demande", "-pk"]},
        ),
        migrations.CreateModel(
            name="HistoriqueAction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("type_action", models.CharField(max_length=40, verbose_name="Action")),
                ("objet_concerne", models.CharField(max_length=80, verbose_name="Objet concerné")),
                ("objet_id", models.PositiveBigIntegerField(blank=True, null=True, verbose_name="Identifiant de l’objet")),
                ("date_action", models.DateTimeField(auto_now_add=True, verbose_name="Date de l’action")),
                ("details", models.JSONField(blank=True, default=dict, verbose_name="Détails")),
                ("utilisateur", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="actions_laboratoire", to=settings.AUTH_USER_MODEL, verbose_name="Utilisateur")),
            ],
            options={"verbose_name": "Action de laboratoire", "verbose_name_plural": "Historique des actions", "ordering": ["-date_action", "-pk"]},
        ),
        migrations.CreateModel(
            name="Prelevement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code_prelevement", models.CharField(max_length=40, unique=True, verbose_name="Code du prélèvement")),
                ("type_prelevement", models.CharField(choices=[("SANG", "Sang"), ("URINE", "Urine"), ("AUTRE", "Autre")], max_length=10, verbose_name="Type")),
                ("date_prelevement", models.DateTimeField(blank=True, null=True, verbose_name="Date du prélèvement")),
                ("date_reception", models.DateTimeField(blank=True, null=True, verbose_name="Date de réception")),
                ("statut", models.CharField(choices=[("A_EFFECTUER", "À effectuer"), ("PRELEVE", "Prélevé"), ("RECU", "Reçu au laboratoire"), ("REJETE", "Rejeté"), ("ANNULE", "Annulé")], default="A_EFFECTUER", max_length=12, verbose_name="Statut")),
                ("motif_rejet", models.TextField(blank=True, verbose_name="Motif du rejet")),
                ("remarque", models.TextField(blank=True, verbose_name="Remarque")),
                ("demande", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="prelevements", to="laboratoire.demandeanalyse", verbose_name="Demande")),
            ],
            options={"verbose_name": "Prélèvement", "verbose_name_plural": "Prélèvements", "ordering": ["-date_prelevement", "-pk"]},
        ),
        migrations.CreateModel(
            name="TypeAnalyse",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=30, unique=True, verbose_name="Code")),
                ("nom", models.CharField(max_length=150, verbose_name="Nom")),
                ("description", models.TextField(blank=True, verbose_name="Description")),
                ("unite", models.CharField(blank=True, max_length=30, verbose_name="Unité")),
                ("valeur_reference_min", models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True, verbose_name="Valeur de référence minimale")),
                ("valeur_reference_max", models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True, verbose_name="Valeur de référence maximale")),
                ("tarif", models.DecimalField(blank=True, decimal_places=2, max_digits=9, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name="Tarif")),
                ("actif", models.BooleanField(default=True, verbose_name="Actif")),
            ],
            options={"verbose_name": "Type d’analyse", "verbose_name_plural": "Types d’analyses", "ordering": ["nom"]},
        ),
        migrations.CreateModel(
            name="AnalyseDemandee",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("statut", models.CharField(choices=[("EN_ATTENTE", "En attente"), ("EN_COURS", "En cours"), ("TERMINEE", "Terminée"), ("ANNULEE", "Annulée")], default="EN_ATTENTE", max_length=12, verbose_name="Statut")),
                ("demande", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="analyses", to="laboratoire.demandeanalyse")),
                ("type_analyse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="demandes", to="laboratoire.typeanalyse")),
            ],
            options={"verbose_name": "Analyse demandée", "verbose_name_plural": "Analyses demandées", "ordering": ["type_analyse__nom"]},
        ),
        migrations.CreateModel(
            name="Resultat",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("valeur", models.CharField(max_length=255, verbose_name="Valeur")),
                ("unite", models.CharField(blank=True, max_length=30, verbose_name="Unité")),
                ("valeur_reference", models.CharField(blank=True, max_length=120, verbose_name="Valeurs de référence")),
                ("interpretation", models.CharField(blank=True, max_length=120, verbose_name="Interprétation")),
                ("observation", models.TextField(blank=True, verbose_name="Observation")),
                ("statut", models.CharField(choices=[("EN_SAISIE", "En saisie"), ("EN_ATTENTE_VALIDATION", "En attente de validation"), ("CORRIGE", "Correction à valider"), ("VALIDE", "Validé")], default="EN_SAISIE", max_length=24, verbose_name="Statut")),
                ("date_saisie", models.DateTimeField(auto_now_add=True, verbose_name="Date de saisie")),
                ("date_modification", models.DateTimeField(auto_now=True, verbose_name="Dernière modification")),
                ("date_validation", models.DateTimeField(blank=True, null=True, verbose_name="Date de validation")),
                ("analyse_demandee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="resultats", to="laboratoire.analysedemandee", verbose_name="Analyse demandée")),
                ("prelevement", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="resultats", to="laboratoire.prelevement", verbose_name="Prélèvement")),
                ("saisi_par", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="resultats_saisis", to=settings.AUTH_USER_MODEL, verbose_name="Saisi par")),
                ("valide_par", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="resultats_valides", to=settings.AUTH_USER_MODEL, verbose_name="Validé par")),
            ],
            options={"verbose_name": "Résultat", "verbose_name_plural": "Résultats", "ordering": ["-date_saisie"]},
        ),
        migrations.AddConstraint(
            model_name="analysedemandee",
            constraint=models.UniqueConstraint(fields=("demande", "type_analyse"), name="unique_type_analyse_par_demande"),
        ),
        migrations.AddConstraint(
            model_name="resultat",
            constraint=models.UniqueConstraint(fields=("analyse_demandee", "prelevement"), name="unique_resultat_analyse_prelevement"),
        ),
    ]
