import django.core.validators
from django.db import migrations, models

import laboratoire.models


def supprimer_analyses_demo_inutilisees(apps, schema_editor):
    TypeAnalyse = apps.get_model("laboratoire", "TypeAnalyse")
    AnalyseDemandee = apps.get_model("laboratoire", "AnalyseDemandee")
    Resultat = apps.get_model("laboratoire", "Resultat")
    database = schema_editor.connection.alias

    for analyse_type in TypeAnalyse.objects.using(database).filter(
        code__in=["DEMO-GLY", "DEMO-NFS"],
    ):
        demo_links = AnalyseDemandee.objects.using(database).filter(
            type_analyse_id=analyse_type.pk,
            demande__commentaire__startswith="DEMO_LABO:",
        )
        for link in demo_links.iterator():
            if not Resultat.objects.using(database).filter(
                analyse_demandee_id=link.pk,
            ).exists():
                link.delete(using=database)

        if AnalyseDemandee.objects.using(database).filter(
            type_analyse_id=analyse_type.pk,
        ).exists():
            analyse_type.actif = False
            analyse_type.save(using=database, update_fields=["actif"])
        else:
            analyse_type.delete(using=database)


class Migration(migrations.Migration):
    dependencies = [
        ("laboratoire", "0002_resultat_validation_permission"),
    ]

    operations = [
        migrations.AddField(
            model_name="typeanalyse",
            name="seuil_critique_bas",
            field=models.DecimalField(
                blank=True, decimal_places=3, max_digits=12, null=True,
                verbose_name="Seuil critique bas",
            ),
        ),
        migrations.AddField(
            model_name="typeanalyse",
            name="seuil_critique_haut",
            field=models.DecimalField(
                blank=True, decimal_places=3, max_digits=12, null=True,
                verbose_name="Seuil critique haut",
            ),
        ),
        migrations.CreateModel(
            name="BilanPredefini",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("nom", models.CharField(max_length=150, unique=True, verbose_name="Nom du bilan")),
                ("description", models.TextField(blank=True, verbose_name="Description")),
                ("actif", models.BooleanField(default=True, verbose_name="Actif")),
                (
                    "analyses",
                    models.ManyToManyField(
                        blank=True, related_name="bilans",
                        to="laboratoire.typeanalyse", verbose_name="Analyses",
                    ),
                ),
            ],
            options={
                "verbose_name": "Bilan prédéfini",
                "verbose_name_plural": "Bilans prédéfinis",
                "ordering": ["nom"],
            },
        ),
        migrations.CreateModel(
            name="ParametresLaboratoire",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False,
                    ),
                ),
                ("nom", models.CharField(blank=True, max_length=150, verbose_name="Nom du laboratoire")),
                ("adresse", models.CharField(blank=True, max_length=255, verbose_name="Adresse")),
                ("telephone", models.CharField(blank=True, max_length=30, verbose_name="Téléphone")),
                (
                    "logo",
                    models.FileField(
                        blank=True, upload_to="laboratoire/logos/",
                        validators=[django.core.validators.FileExtensionValidator(
                            ["png", "jpg", "jpeg", "webp"],
                        )],
                        verbose_name="Logo",
                    ),
                ),
                ("entete_compte_rendu", models.TextField(blank=True, verbose_name="En-tête du compte rendu PDF")),
                ("signature_compte_rendu", models.TextField(blank=True, verbose_name="Signature du compte rendu PDF")),
                (
                    "motifs_rejet",
                    models.JSONField(
                        blank=True,
                        default=laboratoire.models.motifs_rejet_par_defaut,
                        verbose_name="Motifs de rejet d’échantillon",
                    ),
                ),
                (
                    "delai_alerte_urgente_minutes",
                    models.PositiveIntegerField(
                        default=60,
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="Délai d’alerte pour une demande urgente (minutes)",
                    ),
                ),
            ],
            options={
                "verbose_name": "Paramètres du laboratoire",
                "verbose_name_plural": "Paramètres du laboratoire",
            },
        ),
        migrations.RunPython(
            supprimer_analyses_demo_inutilisees,
            migrations.RunPython.noop,
        ),
    ]
