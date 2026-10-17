from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("laboratoire", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="resultat",
            options={
                "ordering": ["-date_saisie"],
                "permissions": [
                    ("valider_resultat", "Peut valider les résultats d’analyses"),
                ],
                "verbose_name": "Résultat",
                "verbose_name_plural": "Résultats",
            },
        ),
    ]
