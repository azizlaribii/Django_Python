"""IA du module Rendez-vous : suggérer la spécialité médicale adaptée au motif saisi par le patient.

Besoin réel : un patient qui écrit « douleur dans la poitrine en montant les escaliers » ne sait pas
forcément qu'il doit consulter un cardiologue. Le modèle lit le motif et propose les spécialités les
plus probables, puis l'application affiche les médecins correspondants.

Modèle : classification de texte supervisée (scikit-learn)
    TF-IDF mots (1-2 grammes) + TF-IDF caractères (3-5 grammes, robuste aux fautes de frappe)
    → Régression logistique multinomiale (probabilités calibrées pour le top-3).

Données : motifs rédigés comme le ferait un patient (rendezvous/ia/donnees/motifs.csv), 12 spécialités.
L'évaluation se fait sur des motifs ENTIERS jamais vus à l'entraînement (pas sur des variantes
d'une phrase déjà apprise), pour ne pas surestimer les performances.
"""
import csv
import random
import threading
import time
import unicodedata
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent / "donnees"
FICHIER_DONNEES = DOSSIER / "motifs.csv"
FICHIER_LEXIQUE = DOSSIER / "lexique.csv"
FICHIER_TEST_INDEPENDANT = DOSSIER / "test_independant.csv"
FICHIER_METRIQUES = DOSSIER / "metriques.json"

SEUIL_CONFIANCE = 0.35  # en dessous, la suggestion est présentée comme incertaine
GRAINE = 42

PREFIXES = ["", "", "j'ai ", "bonjour ", "rdv pour ", "consultation pour ", "depuis quelques jours ",
            "je voudrais consulter pour ", "problème de "]
SUFFIXES = ["", "", " depuis 3 jours", " svp", " ça m'inquiète", " depuis hier", " urgent",
            " depuis longtemps"]


# --------------------------------------------------------------------------
# Données
# --------------------------------------------------------------------------
def charger_donnees(chemin=FICHIER_DONNEES):
    textes, etiquettes = [], []
    with open(chemin, encoding="utf-8") as f:
        for ligne in csv.DictReader(f, delimiter=";"):
            textes.append(ligne["motif"].strip())
            etiquettes.append(ligne["specialite"].strip())
    return textes, etiquettes


def charger_lexique(chemin=FICHIER_LEXIQUE):
    """Connaissances du domaine : vocabulaire médical (organes, symptômes, examens) par spécialité."""
    termes, etiquettes = [], []
    with open(chemin, encoding="utf-8") as f:
        for ligne in csv.DictReader(f, delimiter=";"):
            for terme in ligne["termes"].split(","):
                if terme.strip():
                    termes.append(terme.strip())
                    etiquettes.append(ligne["specialite"].strip())
    return termes, etiquettes


def augmenter(textes, etiquettes, n=4, graine=GRAINE):
    """Ajoute des variantes (formules de politesse, durée…) pour l'entraînement uniquement."""
    rng = random.Random(graine)
    x, y = list(textes), list(etiquettes)
    for texte, etiquette in zip(textes, etiquettes):
        for _ in range(n):
            x.append(f"{rng.choice(PREFIXES)}{texte}{rng.choice(SUFFIXES)}".strip())
            y.append(etiquette)
    return x, y


def normaliser(texte):
    """Minuscules, sans accents : « Échographie » et « echographie » deviennent identiques."""
    texte = unicodedata.normalize("NFKD", (texte or "").lower())
    return "".join(c for c in texte if not unicodedata.combining(c)).strip()


# --------------------------------------------------------------------------
# Modèle
# --------------------------------------------------------------------------
def construire_pipeline():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline

    return Pipeline([
        ("features", FeatureUnion([
            ("mots", TfidfVectorizer(preprocessor=normaliser, ngram_range=(1, 2), sublinear_tf=True)),
            ("caracteres", TfidfVectorizer(preprocessor=normaliser, analyzer="char_wb",
                                           ngram_range=(3, 5), sublinear_tf=True)),
        ])),
        ("classifieur", LogisticRegression(C=10, max_iter=3000, class_weight="balanced")),
    ])


def entrainer(textes, etiquettes, avec_lexique=True):
    """Entraîne sur les motifs (augmentés) + éventuellement le lexique médical."""
    x, y = augmenter(textes, etiquettes)
    if avec_lexique:
        termes, specialites = charger_lexique()
        x, y = x + termes, y + specialites
    return construire_pipeline().fit(x, y)


_modele = None
_verrou = threading.Lock()


def get_modele():
    """Modèle entraîné sur toutes les données, chargé une seule fois par processus (< 1 s)."""
    global _modele
    if _modele is None:
        with _verrou:
            if _modele is None:
                _modele = entrainer(*charger_donnees())
    return _modele


def suggerer(motif, k=3):
    """Renvoie les k spécialités les plus probables pour un motif.

    {"suggestions": [{"specialite", "probabilite"}...], "confiant": bool, "temps_ms": float}
    """
    motif = (motif or "").strip()
    if len(motif) < 3:
        raise ValueError("Décrivez votre motif en quelques mots (3 caractères minimum).")
    modele = get_modele()
    debut = time.perf_counter()
    probas = modele.predict_proba([motif[:500]])[0]
    temps_ms = (time.perf_counter() - debut) * 1000
    classes = modele.classes_
    ordre = probas.argsort()[::-1][:k]
    suggestions = [{"specialite": classes[i], "probabilite": round(float(probas[i]), 3)} for i in ordre]
    return {
        "suggestions": suggestions,
        "confiant": suggestions[0]["probabilite"] >= SEUIL_CONFIANCE,
        "temps_ms": round(temps_ms, 2),
    }


# --------------------------------------------------------------------------
# Évaluation (utilisée par la commande `python manage.py evaluer_ia_rdv`)
# --------------------------------------------------------------------------
def evaluer(taille_test=0.25, n_plis=5, n_mesures_latence=300):
    import numpy as np
    from sklearn.dummy import DummyClassifier
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
    from sklearn.model_selection import StratifiedKFold, train_test_split

    textes, etiquettes = charger_donnees()
    classes = sorted(set(etiquettes))

    # 1. Hold-out : 25 % des motifs mis de côté AVANT toute augmentation (aucune fuite).
    x_tr, x_te, y_tr, y_te = train_test_split(
        textes, etiquettes, test_size=taille_test, stratify=etiquettes, random_state=GRAINE
    )
    debut = time.perf_counter()
    modele = entrainer(x_tr, y_tr)
    temps_entrainement = time.perf_counter() - debut
    y_pred = modele.predict(x_te)
    probas = modele.predict_proba(x_te)
    top3 = np.mean([
        y in modele.classes_[p.argsort()[::-1][:3]] for y, p in zip(y_te, probas)
    ])
    rapport = classification_report(y_te, y_pred, labels=classes, output_dict=True, zero_division=0)

    # 2. Référence naïve : toujours prédire la classe la plus fréquente.
    reference = DummyClassifier(strategy="most_frequent").fit(x_tr, y_tr)
    f1_reference = f1_score(y_te, reference.predict(x_te), average="macro", zero_division=0)
    # Ablation : même modèle sans le lexique médical, pour mesurer son apport.
    sans_lexique = entrainer(x_tr, y_tr, avec_lexique=False)
    f1_sans_lexique = f1_score(y_te, sans_lexique.predict(x_te), average="macro", zero_division=0)

    # 3. Validation croisée à 5 plis (sur les motifs d'origine, augmentation dans chaque pli).
    scores_cv = []
    x_arr, y_arr = np.array(textes, dtype=object), np.array(etiquettes)
    for i_tr, i_te in StratifiedKFold(n_splits=n_plis, shuffle=True, random_state=GRAINE).split(x_arr, y_arr):
        m = entrainer(list(x_arr[i_tr]), list(y_arr[i_tr]))
        scores_cv.append(f1_score(y_arr[i_te], m.predict(list(x_arr[i_te])), average="macro"))

    # 4. Latence d'une prédiction unitaire (cas réel : un patient = un motif).
    durees = []
    for motif in (x_te * (n_mesures_latence // len(x_te) + 1))[:n_mesures_latence]:
        t = time.perf_counter()
        modele.predict_proba([motif])
        durees.append((time.perf_counter() - t) * 1000)

    erreurs = [
        {"motif": m, "attendu": a, "predit": str(p)}
        for m, a, p in zip(x_te, y_te, y_pred) if a != p
    ]

    # 5. Test indépendant : 60 phrases rédigées APRÈS la mise au point du modèle et du lexique,
    #    jamais utilisées pour régler quoi que ce soit. C'est le chiffre le plus honnête.
    x_ind, y_ind = charger_donnees(FICHIER_TEST_INDEPENDANT)
    modele_final = entrainer(textes, etiquettes)
    y_ind_pred = modele_final.predict(x_ind)
    probas_ind = modele_final.predict_proba(x_ind)
    top3_ind = np.mean([
        y in modele_final.classes_[p.argsort()[::-1][:3]] for y, p in zip(y_ind, probas_ind)
    ])
    independant = {
        "nb": len(x_ind),
        "accuracy": round(accuracy_score(y_ind, y_ind_pred), 4),
        "f1_macro": round(f1_score(y_ind, y_ind_pred, average="macro", zero_division=0), 4),
        "top3_accuracy": round(float(top3_ind), 4),
        "f1_sans_lexique": round(f1_score(
            y_ind, entrainer(textes, etiquettes, avec_lexique=False).predict(x_ind),
            average="macro", zero_division=0), 4),
        "matrice_confusion": confusion_matrix(y_ind, y_ind_pred, labels=classes).tolist(),
        "erreurs": [
            {"motif": m, "attendu": a, "predit": str(p)}
            for m, a, p in zip(x_ind, y_ind, y_ind_pred) if a != p
        ],
    }
    return {
        "nb_motifs": len(textes),
        "nb_classes": len(classes),
        "nb_entrainement": len(x_tr),
        "nb_entrainement_augmente": len(x_tr) * 5,
        "nb_test": len(x_te),
        "accuracy": round(accuracy_score(y_te, y_pred), 4),
        "f1_macro": round(rapport["macro avg"]["f1-score"], 4),
        "precision_macro": round(rapport["macro avg"]["precision"], 4),
        "rappel_macro": round(rapport["macro avg"]["recall"], 4),
        "top3_accuracy": round(float(top3), 4),
        "f1_reference_naive": round(f1_reference, 4),
        "f1_sans_lexique": round(f1_sans_lexique, 4),
        "nb_termes_lexique": len(charger_lexique()[0]),
        "cv_f1_moyenne": round(float(np.mean(scores_cv)), 4),
        "cv_f1_ecart_type": round(float(np.std(scores_cv)), 4),
        "cv_plis": [round(float(s), 4) for s in scores_cv],
        "par_classe": [
            {"specialite": c, "precision": round(rapport[c]["precision"], 3),
             "rappel": round(rapport[c]["recall"], 3), "f1": round(rapport[c]["f1-score"], 3),
             "support": int(rapport[c]["support"])}
            for c in classes
        ],
        "classes": classes,
        "matrice_confusion": confusion_matrix(y_te, y_pred, labels=classes).tolist(),
        "erreurs": erreurs,
        "test_independant": independant,
        "latence_ms_moyenne": round(float(np.mean(durees)), 2),
        "latence_ms_p95": round(float(np.percentile(durees, 95)), 2),
        "temps_entrainement_s": round(temps_entrainement, 2),
    }
