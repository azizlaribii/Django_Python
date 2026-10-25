# Generated migration for creating laboratory permission groups

from django.db import migrations


def create_laboratory_groups(apps, schema_editor):
    """
    Crée les groupes Django nécessaires pour le module laboratoire.
    
    Groupes créés :
    - Biologiste responsable : Peut valider les résultats d'analyses
    - Préleveur : Peut effectuer les prélèvements
    - Technicien de laboratoire : Peut saisir les résultats
    
    Note : Les groupes "Équipe Laboratoire X" sont créés dynamiquement
    par les administrateurs selon les besoins organisationnels.
    """
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    
    # Récupérer la permission personnalisée valider_resultat
    try:
        resultat_ct = ContentType.objects.get(app_label='laboratoire', model='resultat')
        valider_perm = Permission.objects.get(
            codename='valider_resultat',
            content_type=resultat_ct,
        )
    except (ContentType.DoesNotExist, Permission.DoesNotExist):
        valider_perm = None
    
    # Groupe Biologiste responsable
    biologiste_group, created = Group.objects.get_or_create(
        name='Biologiste responsable'
    )
    if created and valider_perm:
        biologiste_group.permissions.add(valider_perm)
    
    # Groupe Préleveur (aucune permission spéciale, accès via les vues)
    Group.objects.get_or_create(name='Préleveur')
    
    # Groupe Technicien de laboratoire (aucune permission spéciale, accès via les vues)
    Group.objects.get_or_create(name='Technicien de laboratoire')


def reverse_groups(apps, schema_editor):
    """Supprime les groupes créés par cette migration."""
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(
        name__in=[
            'Biologiste responsable',
            'Préleveur',
            'Technicien de laboratoire',
        ]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('laboratoire', '0006_resultat_observation'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(create_laboratory_groups, reverse_groups),
    ]
