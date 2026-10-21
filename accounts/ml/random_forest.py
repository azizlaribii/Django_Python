"""
Module Random Forest — MediConnect ML
Responsabilités :
1. Définition et génération d'une cohorte clinique SYNTHÉTIQUE (1 600 cas) pour démonstration pédagogique.
2. Découpage strict 80% entraînement / 20% test avant tout ajustement (garantie d'absence de fuite de données).
3. Entraînement du modèle RandomForestClassifier (Scikit-Learn).
4. Évaluation sur les 320 cas de test indépendants (métriques calculées sans valeur en dur).
   IMPORTANT : Ces métriques reflètent les performances sur données synthétiques et ne constituent
   en aucun cas une validation clinique réelle sur patients réels.
5. Validation rigoureuse du vecteur patient (exactement 12 variables, dans l'ordre attendu).
6. Inférence / prédiction probabiliste pour un patient donné.
"""

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, roc_auc_score, f1_score


# Description normalisée des 12 variables cliniques d'entrée
VARIABLES_CLINIQUES = [
    {"index": 0, "code": "age_norm", "label": "Âge normalisé (/100)"},
    {"index": 1, "code": "hta", "label": "Hypertension Artérielle (0 ou 1)"},
    {"index": 2, "code": "diabete", "label": "Diabète Type 1 ou 2 (0 ou 1)"},
    {"index": 3, "code": "dyslipidemie", "label": "Dyslipidémie (0 ou 1)"},
    {"index": 4, "code": "insuffisance_cardiaque", "label": "Insuffisance Cardiaque (0 ou 1)"},
    {"index": 5, "code": "insuffisance_renale", "label": "Insuffisance Rénale (0 ou 1)"},
    {"index": 6, "code": "asthme_bpco", "label": "Asthme / BPCO (0 ou 1)"},
    {"index": 7, "code": "allergie_severe", "label": "Terrain allergique sévère pénicilline/iode (0 ou 1)"},
    {"index": 8, "code": "nb_meds_norm", "label": "Polymédication (traitements actifs / 8)"},
    {"index": 9, "code": "examen_invasif", "label": "Examen invasif planifié (0 ou 1)"},
    {"index": 10, "code": "prep_echec", "label": "Échec avéré de préparation médicale (0 ou 1)"},
    {"index": 11, "code": "analyse_urgente", "label": "Bilan biologique urgent actif (0 ou 1)"},
]


def valider_vecteur_patient(vecteur):
    """
    Vérifie la conformité structurelle et numérique du vecteur patient :
    - Doit comporter exactement 12 variables.
    - Doit être convertible en tableau float unidimensionnel.
    - Ne doit contenir ni NaN ni valeurs infinies.
    Retourne un np.ndarray de forme (12,).
    Lève ValueError si le vecteur est invalide.
    """
    if vecteur is None:
        raise ValueError("Le vecteur patient ne peut pas être None.")

    try:
        arr = np.asarray(vecteur, dtype=np.float64)
    except (TypeError, ValueError) as err:
        raise ValueError(f"Le vecteur patient doit être convertible en nombres réels : {err}")

    if arr.ndim != 1 or arr.shape[0] != 12:
        raise ValueError(
            f"Vecteur patient invalide : exactement 12 variables attendues, reçu forme {arr.shape}."
        )

    if np.isnan(arr).any():
        raise ValueError("Le vecteur patient contient des valeurs NaN (données manquantes non imputées).")

    if np.isinf(arr).any():
        raise ValueError("Le vecteur patient contient des valeurs infinies.")

    return arr


def generer_dataset_clinique_synthetique(n_samples=1600, random_state=42):
    """
    Génère un jeu de données clinique SYNTHÉTIQUE calibré pour la démonstration académique.
    
    Avertissement méthodologique :
    Ce dataset est simulé par distribution statistique et ne provient pas d'essais cliniques réels.
    
    X : Matrice (n_samples, 12 variables)
    y : Cible binaire (1 = Risque de complication clinique / décompensation, 0 = Évolution stable)
    """
    rng = np.random.RandomState(random_state)

    ages = rng.randint(18, 90, size=n_samples) / 100.0
    hta = rng.binomial(1, 0.35, size=n_samples)
    diabete = rng.binomial(1, 0.22, size=n_samples)
    dyslip = rng.binomial(1, 0.28, size=n_samples)
    ic = rng.binomial(1, 0.12, size=n_samples)
    ir = rng.binomial(1, 0.10, size=n_samples)
    asthme = rng.binomial(1, 0.15, size=n_samples)
    allergie = rng.binomial(1, 0.18, size=n_samples)
    nb_meds = rng.poisson(lam=2.5, size=n_samples).clip(0, 8) / 8.0
    examen_inv = rng.binomial(1, 0.25, size=n_samples)
    prep_echec = rng.binomial(1, 0.08, size=n_samples)
    analyse_urg = rng.binomial(1, 0.14, size=n_samples)

    X = np.column_stack([
        ages, hta, diabete, dyslip, ic, ir, asthme,
        allergie, nb_meds, examen_inv, prep_echec, analyse_urg
    ])

    # Modélisation physiopathologique du risque (logit)
    logit = (
        -3.2
        + 1.8 * (ages > 0.65)
        + 1.3 * hta
        + 1.6 * diabete
        + 2.2 * ic
        + 2.0 * ir
        + 1.1 * asthme
        + 1.4 * allergie
        + 1.8 * nb_meds
        + 1.2 * examen_inv
        + 1.9 * prep_echec
        + 1.7 * analyse_urg
    )
    probabilites = 1.0 / (1.0 + np.exp(-logit))
    y = rng.binomial(1, probabilites)

    return X, y


class ModeleRandomForestGestionnaire:
    """
    Singleton maintenant en mémoire le RandomForestClassifier entraîné
    et ses métriques d'évaluation sur jeu de test indépendant.
    """
    _instance = None

    def __init__(self):
        # 1. Génération de la cohorte synthétique
        X, y = generer_dataset_clinique_synthetique(n_samples=1600, random_state=42)

        # 2. Découpage strict avant apprentissage : 80% train / 20% test (stratifié)
        # Aucune information du jeu de test n'est utilisée pour ajuster le modèle (pas de fuite de données).
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.20, random_state=42, stratify=y
        )

        # 3. Entraînement du modèle Scikit-Learn
        self.modele = RandomForestClassifier(
            n_estimators=100,
            max_depth=6,
            min_samples_leaf=3,
            random_state=42
        )
        self.modele.fit(X_train, y_train)

        # 4. Évaluation sur les 320 cas de test indépendants
        y_pred = self.modele.predict(X_test)
        y_proba = self.modele.predict_proba(X_test)[:, 1]

        # 5. Métriques réelles calculées par Scikit-Learn
        self.metrics = {
            'accuracy': round(float(accuracy_score(y_test, y_pred)) * 100, 1),
            'roc_auc': round(float(roc_auc_score(y_test, y_proba)) * 100, 1),
            'f1_score': round(float(f1_score(y_test, y_pred)) * 100, 1),
            'n_train': int(len(X_train)),
            'n_test': int(len(X_test)),
            'algorithme': 'RandomForestClassifier (Scikit-Learn)',
            'nature_dataset': 'Synthétique (1 600 profils simulés pour démonstration)',
            'avertissement_clinique': 'Métriques mesurées sur cohorte synthétique de test : ne constitue pas une validation clinique réelle sur patients réels.',
            'cible': 'Complication clinique ou décompensation iatrogène',
        }

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def predire_risque_complications(vecteur_patient):
    """
    Prédit la probabilité de complication à partir du vecteur patient (12 variables).
    Valide préalablement l'intégrité du vecteur.
    """
    vecteur_valide = valider_vecteur_patient(vecteur_patient)
    gestionnaire = ModeleRandomForestGestionnaire.get_instance()
    modele = gestionnaire.modele

    proba = modele.predict_proba([vecteur_valide])[0][1]
    classe = int(modele.predict([vecteur_valide])[0])
    pourcentage = round(float(proba) * 100, 1)

    return {
        'score_proba': pourcentage,
        'prediction_classe': classe,
        'nature': "Probabilité estimée par le modèle Random Forest (entraîné sur dataset synthétique)",
        'interpretation': "Estimation issue d'un modèle d'ensemble à 100 arbres décisionnels.",
    }


def obtenir_performances_modele():
    """
    Retourne les métriques calculées sur le jeu de test indépendant (320 cas synthétiques).
    """
    gestionnaire = ModeleRandomForestGestionnaire.get_instance()
    return gestionnaire.metrics
