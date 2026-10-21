"""
Package Machine Learning Médical — MediConnect
Architecture modulaire :
- random_forest.py : Modèle Random Forest Scikit-Learn (entraînement, test, prédiction, métriques réelles)
- risk_score.py : Score de risque explicable basé sur des règles cliniques validées
- similarity.py : Comparaison avec des profils cliniques de référence par Similarité Cosinus
"""

from .random_forest import predire_risque_complications, obtenir_performances_modele
from .risk_score import calculer_score_risque_clinique, extraire_vecteur_clinique
from .similarity import trouver_profil_similaire

def evaluer_patient_ml(patient, dossier, ia_data):
    """
    Orchestre l'ensemble des modules ML pour un patient :
    1. Extraction des variables cliniques et calcul du score de risque explicable (risk_score.py)
    2. Inférence Random Forest et récupération des métriques réelles de test (random_forest.py)
    3. Calcul mathématique de la similarité cosinus avec les profils types (similarity.py)
    """
    # 1. Score de risque et complétude
    resultat_risque = calculer_score_risque_clinique(patient, dossier, ia_data)
    vecteur_patient = resultat_risque['vecteur_clinique']

    # 2. Prédiction Machine Learning (Random Forest)
    if resultat_risque['donnees_insuffisantes']:
        prediction_rf = {
            'score_proba': None,
            'prediction_classe': None,
            'message': "Inférence suspendue en raison de données insuffisantes."
        }
    else:
        prediction_rf = predire_risque_complications(vecteur_patient)

    performances_rf = obtenir_performances_modele()

    # 3. Similarité Cosinus avec cohortes types
    examens_patient = ia_data.get('examens_complets', [])
    similarite_result = trouver_profil_similaire(vecteur_patient, examens_patient)

    return {
        # Données de complétude
        'donnees_insuffisantes': resultat_risque['donnees_insuffisantes'],
        'taux_completude': resultat_risque['taux_completude'],
        'donnees_manquantes': resultat_risque['donnees_manquantes'],
        'donnees_manquantes_texte': resultat_risque['donnees_manquantes_texte'],

        # 1. Score de risque explicable
        'score_global': resultat_risque['score_global'],
        'score_display': resultat_risque['score_display'],
        'niveau_risque': resultat_risque['niveau_risque'],
        'badge_classe': resultat_risque['badge_classe'],
        'couleur': resultat_risque['couleur'],
        'icone': resultat_risque['icone'],
        'recommandation_prioritaire': resultat_risque['recommandation_prioritaire'],
        'facteurs_explicatifs': resultat_risque['facteurs_explicatifs'],
        'sous_scores': resultat_risque['sous_scores'],

        # 2. Random Forest
        'random_forest_prediction': prediction_rf,
        'metrics_modele': performances_rf,

        # 3. Similarité Cosinus
        'meilleure_cohorte': similarite_result['meilleur_profil'],
        'cohortes_scorees': similarite_result['tous_profils'],

        # Alertes spécifiques
        'alertes_examens_specifiques': resultat_risque['alertes_specifiques'],
        'alertes_predictives': resultat_risque['alertes_specifiques'],
    }
