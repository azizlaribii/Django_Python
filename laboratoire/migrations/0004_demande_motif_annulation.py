from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("laboratoire", "0003_catalogue_bilans_parametres"),
    ]

    operations = [
        migrations.AddField(
            model_name="demandeanalyse",
            name="motif_annulation",
            field=models.TextField(blank=True, verbose_name="Motif d’annulation"),
        ),
    ]
