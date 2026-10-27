import unicodedata
from functools import lru_cache
from pathlib import Path

import joblib


MODEL_PATH = Path(__file__).with_name("anomaly_models.joblib")


def normalize_test_name(test_name):
    normalized = unicodedata.normalize("NFKD", str(test_name))
    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).strip().casefold()


@lru_cache(maxsize=1)
def _load_models():
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(
            f"Modèles ML introuvables : {MODEL_PATH}. "
            "Générez le dataset puis entraînez les modèles."
        )
    models = joblib.load(MODEL_PATH)
    if not isinstance(models, dict):
        raise ValueError(f"Format de modèles invalide dans {MODEL_PATH}.")
    return {
        normalize_test_name(test_name): model
        for test_name, model in models.items()
    }


def check_value(test_name, value):
    model = _load_models().get(normalize_test_name(test_name))
    if model is None:
        return False
    return bool(model.predict([[float(value)]])[0] == -1)
