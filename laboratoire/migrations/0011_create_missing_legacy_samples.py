from django.db import migrations


def create_missing_legacy_samples(apps, schema_editor):
    alias = schema_editor.connection.alias
    AnalyseDemandee = apps.get_model("laboratoire", "AnalyseDemandee")
    Prelevement = apps.get_model("laboratoire", "Prelevement")

    analyses_without_samples = {}
    analyses = AnalyseDemandee.objects.using(alias).filter(
        prelevement__isnull=True,
    ).select_related("demande", "type_analyse")
    for analyse in analyses.iterator():
        has_matching_sample = Prelevement.objects.using(alias).filter(
            demande_id=analyse.demande_id,
            type_prelevement=analyse.type_analyse.type_echantillon,
        ).exists()
        if not has_matching_sample:
            key = (analyse.demande_id, analyse.type_analyse.type_echantillon)
            analyses_without_samples.setdefault(key, []).append(analyse.pk)

    for (demande_id, sample_type), analyse_ids in analyses_without_samples.items():
        sample = Prelevement.objects.using(alias).create(
            demande_id=demande_id,
            type_prelevement=sample_type,
            statut="A_EFFECTUER",
        )
        AnalyseDemandee.objects.using(alias).filter(
            pk__in=analyse_ids,
        ).update(prelevement_id=sample.pk)


class Migration(migrations.Migration):
    dependencies = [
        ("laboratoire", "0010_backfill_unambiguous_samples"),
    ]

    operations = [
        migrations.RunPython(
            create_missing_legacy_samples,
            migrations.RunPython.noop,
        ),
    ]
