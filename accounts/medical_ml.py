"""
Module de Machine Learning Médical — MediConnect (Façade de compatibilité)

Ce fichier redirige de manière transparente vers le package modulaire `accounts.ml` :
- accounts/ml/random_forest.py : Modèle Random Forest Scikit-Learn (entraînement, test, prédiction, métriques réelles)
- accounts/ml/risk_score.py : Score de risque explicable basé sur des règles cliniques validées
- accounts/ml/similarity.py : Comparaison avec des profils cliniques de référence par Similarité Cosinus
"""

from .ml import evaluer_patient_ml


def evaluer_risques_machine_learning(patient, dossier, ia_data):
    """
    Point d'entrée principal du module de Machine Learning médical.
    Délègue l'exécution à l'orchestrateur modulaire `evaluer_patient_ml`.
    """
    return evaluer_patient_ml(patient, dossier, ia_data)
