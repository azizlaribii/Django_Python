import json
import urllib.error
import urllib.request

from django.conf import settings

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _appeler(model, prompt):
    corps = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }).encode("utf-8")
    req = urllib.request.Request(
        URL.format(model=model), data=corps, method="POST",
        headers={"Content-Type": "application/json",
                 "x-goog-api-key": settings.GOOGLE_API_KEY},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["candidates"][0]["content"]["parts"][0]["text"]


def suggerer_lignes(texte, tarifs):
    """tarifs : liste de dicts {id, code, libelle, prix}. Retourne [{tarif_id, quantite}]."""
    if not settings.GOOGLE_API_KEY:
        raise RuntimeError("Clé GEMINI_API_KEY absente du fichier .env")

    prompt = (
        "Catalogue de tarifs médicaux (JSON) :\n" + json.dumps(tarifs, ensure_ascii=False) +
        "\n\nTexte du médecin : " + texte +
        '\n\nRéponds UNIQUEMENT par un tableau JSON : '
        '[{"tarif_id": <id du catalogue>, "quantite": <entier>}]. '
        "N'utilise que des id présents dans le catalogue. "
        "Si rien ne correspond, réponds []."
    )

    derniere_erreur = None
    for model in (settings.GEMINI_MODEL, settings.GEMINI_FALLBACK_MODEL):
        try:
            brut = _appeler(model, prompt)
            break
        except (urllib.error.URLError, KeyError, IndexError, TimeoutError) as e:
            derniere_erreur = e
    else:
        raise RuntimeError(f"Service IA indisponible : {derniere_erreur}")

    brut = brut.replace("```json", "").replace("```", "").strip()
    donnees = json.loads(brut)
    valides = {t['id'] for t in tarifs}
    # On ne fait jamais confiance au modèle : id et quantité sont revalidés.
    return [{'tarif_id': d['tarif_id'], 'quantite': max(1, int(d.get('quantite', 1)))}
            for d in donnees if d.get('tarif_id') in valides]