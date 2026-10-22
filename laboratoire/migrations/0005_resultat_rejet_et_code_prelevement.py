import laboratoire.models
from django.db import migrations, models


def create_responsable_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.using(schema_editor.connection.alias).get_or_create(
        name="Biologiste responsable",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("laboratoire", "0004_demande_motif_annulation"),
    ]

    operations = [
        migrations.AddField(
            model_name="resultat",
            name="commentaire_rejet",
            field=models.TextField(blank=True, verbose_name="Commentaire de rejet"),
        ),
        migrations.AlterField(
            model_name="resultat",
            name="statut",
            field=models.CharField(
                choices=[
                    ("EN_SAISIE", "En saisie"),
                    ("EN_ATTENTE_VALIDATION", "En attente de validation"),
                    ("CORRIGE", "Correction à valider"),
                    ("REJETE", "Rejeté — à corriger"),
                    ("VALIDE", "Validé"),
                ],
                default="EN_SAISIE",
                max_length=24,
                verbose_name="Statut",
            ),
        ),
        migrations.AlterField(
            model_name="prelevement",
            name="statut",
            field=models.CharField(
                choices=[
                    ("A_EFFECTUER", "À prélever"),
                    ("PRELEVE", "Prélevé"),
                    ("RECU", "Reçu au laboratoire"),
                    ("REJETE", "Rejeté"),
                    ("ANNULE", "Annulé"),
                ],
                default="A_EFFECTUER",
                max_length=12,
                verbose_name="Statut",
            ),
        ),
        migrations.AlterField(
            model_name="prelevement",
            name="code_prelevement",
            field=models.CharField(
                default=laboratoire.models.generer_code_prelevement,
                max_length=40,
                unique=True,
                verbose_name="Code du prélèvement",
            ),
        ),
        migrations.RunPython(create_responsable_group, migrations.RunPython.noop),
    ]
