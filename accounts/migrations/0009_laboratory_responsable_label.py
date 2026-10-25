from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0008_order_examens_by_date_creation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="laboratoryprofile",
            name="responsable",
            field=models.CharField(
                blank=True,
                max_length=120,
                verbose_name="Responsable du laboratoire",
            ),
        ),
    ]
