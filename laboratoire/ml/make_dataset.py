import csv
from pathlib import Path

import numpy as np
import pandas as pd


OUTPUT_PATH = Path(__file__).with_name("analyses.csv")
ANALYSES = {
    "hemoglobine": (14.0, 1.8),
    "glycemie": (0.95, 0.20),
    "cholesterol": (1.80, 0.35),
}
RANDOM_SEED = 42


def generate_dataset():
    random = np.random.default_rng(RANDOM_SEED)
    rows = []
    for test_name, (mean, standard_deviation) in ANALYSES.items():
        normal_values = np.clip(
            random.normal(mean, standard_deviation, 300),
            np.finfo(float).eps,
            None,
        )
        rows.extend(
            {"test_name": test_name, "value": value, "label": 0}
            for value in normal_values
        )
        error_sources = random.choice(normal_values, size=30, replace=True)
        multipliers = random.choice([10, 100, 0.1, 0.01], size=30)
        rows.extend(
            {
                "test_name": test_name,
                "value": value * multiplier,
                "label": 1,
            }
            for value, multiplier in zip(error_sources, multipliers)
        )
    return pd.DataFrame(rows, columns=["test_name", "value", "label"])


def main():
    dataset = generate_dataset()
    dataset.to_csv(OUTPUT_PATH, index=False, quoting=csv.QUOTE_MINIMAL)
    print(f"Dataset généré : {OUTPUT_PATH} ({len(dataset)} lignes)")


if __name__ == "__main__":
    main()
