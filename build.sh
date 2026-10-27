#!/usr/bin/env bash
# Script de build exécuté par Render à chaque déploiement.
set -o errexit

pip install -r requirements.txt

# Convertir (collecter + compresser) les fichiers statiques
python manage.py collectstatic --no-input

# Appliquer toutes les migrations de base de données en suspens
python manage.py migrate

# Créer le super-utilisateur à partir des variables DJANGO_SUPERUSER_* (ignoré s'il existe déjà)
python manage.py createsuperuser --noinput || true

# Données de démonstration (comptes, créneaux…) si CHARGER_DONNEES_DEMO=1 dans Render
if [ "${CHARGER_DONNEES_DEMO:-0}" = "1" ]; then
  python manage.py seed_demo_data
  python manage.py seed_rendezvous
fi
