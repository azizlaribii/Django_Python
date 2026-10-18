from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("laboratoire", "0005_resultat_rejet_et_code_prelevement"),
    ]

    operations = [
        migrations.AddField(
            model_name="resultat",
            name="observation",
            field=models.TextField(blank=True, verbose_name="Observation"),
        ),
    ]
