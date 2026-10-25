from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0009_laboratory_responsable_label"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("ADMIN", "Administrateur"),
                    ("DOCTEUR", "Médecin"),
                    ("LABORATOIRE", "Laborantin"),
                    ("PATIENT", "Patient"),
                ],
                default="PATIENT",
                max_length=20,
                verbose_name="Rôle utilisateur",
            ),
        ),
    ]
