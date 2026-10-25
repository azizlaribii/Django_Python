from django.db import migrations


def remove_legacy_laboratory_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=[
        "Biologiste responsable",
        "Préleveur",
        "Technicien de laboratoire",
    ]).delete()

    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    resultat_type = ContentType.objects.filter(
        app_label="laboratoire",
        model="resultat",
    ).first()
    if resultat_type:
        Permission.objects.filter(
            content_type=resultat_type,
            codename="valider_resultat",
        ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("laboratoire", "0008_alter_prelevement_options_alter_resultat_options_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(
            remove_legacy_laboratory_groups,
            migrations.RunPython.noop,
        ),
    ]
