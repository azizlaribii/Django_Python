from django.db import migrations


def backfill_unambiguous_samples(apps, schema_editor):
    alias = schema_editor.connection.alias
    AnalyseDemandee = apps.get_model("laboratoire", "AnalyseDemandee")
    Prelevement = apps.get_model("laboratoire", "Prelevement")
    Resultat = apps.get_model("laboratoire", "Resultat")

    analyses = AnalyseDemandee.objects.using(alias).filter(
        prelevement__isnull=True,
    ).select_related("demande", "type_analyse")
    for analyse in analyses.iterator():
        matching_ids = list(
            Prelevement.objects.using(alias).filter(
                demande_id=analyse.demande_id,
                type_prelevement=analyse.type_analyse.type_echantillon,
            ).values_list("pk", flat=True)[:2]
        )
        if len(matching_ids) == 1:
            AnalyseDemandee.objects.using(alias).filter(pk=analyse.pk).update(
                prelevement_id=matching_ids[0],
            )

    resultats = Resultat.objects.using(alias).filter(
        prelevement__isnull=True,
        analyse_demandee__prelevement__isnull=False,
    ).select_related("analyse_demandee")
    for resultat in resultats.iterator():
        Resultat.objects.using(alias).filter(pk=resultat.pk).update(
            prelevement_id=resultat.analyse_demandee.prelevement_id,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("laboratoire", "0009_remove_legacy_laboratory_groups"),
    ]

    operations = [
        migrations.RunPython(
            backfill_unambiguous_samples,
            migrations.RunPython.noop,
        ),
    ]
