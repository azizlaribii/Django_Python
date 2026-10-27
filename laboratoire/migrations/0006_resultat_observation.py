from django.db import migrations


class Migration(migrations.Migration):
    """Migration conservée vide volontairement.

    Le champ `Resultat.observation` est déjà créé par 0001_initial. L'ajouter une seconde fois
    passait sur SQLite (qui reconstruit la table) mais échouait sur PostgreSQL au déploiement :
    « column "observation" of relation "laboratoire_resultat" already exists ».
    Le fichier est gardé pour que les bases où cette migration est déjà appliquée restent cohérentes.
    """

    dependencies = [
        ("laboratoire", "0005_resultat_rejet_et_code_prelevement"),
    ]

    operations = []
