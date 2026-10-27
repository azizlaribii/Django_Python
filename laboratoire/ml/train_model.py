from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split

from .make_dataset import OUTPUT_PATH, generate_dataset


MODEL_PATH = Path(__file__).with_name("anomaly_models.joblib")
METRICS_PATH = Path(__file__).with_name("metrics.txt")
RANDOM_SEED = 42


def train_models(dataset=None):
    dataset = dataset if dataset is not None else pd.read_csv(OUTPUT_PATH)
    models = {}
    report_lines = []

    for test_name, analysis_data in dataset.groupby("test_name"):
        train_data, test_data = train_test_split(
            analysis_data,
            test_size=0.25,
            random_state=RANDOM_SEED,
            stratify=analysis_data["label"],
        )
        normal_training_values = train_data.loc[
            train_data["label"] == 0, "value"
        ].to_numpy().reshape(-1, 1)
        model = IsolationForest(
            contamination=0.005,
            random_state=RANDOM_SEED,
        )
        model.fit(normal_training_values)
        actual = test_data["label"].to_numpy()
        test_values = test_data["value"].to_numpy().reshape(-1, 1)
        predicted = (model.predict(test_values) == -1).astype(int)

        models[test_name] = model
        report_lines.extend([
            f"Analyse : {test_name}",
            "Matrice de confusion (lignes=réel, colonnes=prédit) :",
            str(confusion_matrix(actual, predicted, labels=[0, 1])),
            f"Precision : {precision_score(actual, predicted, zero_division=0):.4f}",
            f"Recall : {recall_score(actual, predicted, zero_division=0):.4f}",
            f"F1 : {f1_score(actual, predicted, zero_division=0):.4f}",
            "",
        ])

    joblib.dump(models, MODEL_PATH)
    METRICS_PATH.write_text("\n".join(report_lines), encoding="utf-8")
    return models


def main():
    if not OUTPUT_PATH.exists():
        raise FileNotFoundError(
            f"Dataset introuvable : {OUTPUT_PATH}. "
            "Exécutez python -m laboratoire.ml.make_dataset d’abord."
        )
    train_models()
    print(f"Modèles sauvegardés : {MODEL_PATH}")
    print(f"Métriques sauvegardées : {METRICS_PATH}")
    print(METRICS_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
