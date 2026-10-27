import logging
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.db.models import Q

from decimal import Decimal, InvalidOperation, localcontext

from .models import AnalyseDemandee, Resultat


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResumeGeneration:
    texte: str
    source: str
    avertissement: str = ""
    fournisseur: str = ""
    modele: str = ""


class ResumeAPIError(Exception):
    def __init__(self, message="erreur API non détaillée", *, code="api_error", status_code=None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


CHAMPS_RESUME_API = (
    "analyse",
    "valeur",
    "unite",
    "reference",
    "statut",
    "valeur_precedente",
    "unite_precedente",
    "evolution",
)

CONSIGNE_RESUME = (
    "Rédige en français un résumé descriptif, clair et concis des résultats "
    "de laboratoire et de leur comparaison avec l’historique, en utilisant "
    "uniquement les données JSON fournies. Présente une courte introduction "
    "puis une liste à puces, avec une puce par analyse. Pour chaque analyse, "
    "recopie exactement la valeur actuelle et son unité, puis indique la position "
    "par rapport aux références uniquement si le statut fourni est déterminé. "
    "Si une valeur précédente et une évolution sont fournies, rapporte-les sans "
    "les recalculer ; sinon indique qu’aucune comparaison précédente n’est "
    "disponible. N’invente, ne corrige et ne convertis aucune valeur, unité, "
    "référence ou évolution. N’explique pas les causes et ne qualifie pas la "
    "gravité. Ne donne aucun diagnostic, conseil, recommandation, suggestion "
    "d’examen ou de traitement. N’ajoute ni données ni titre générique. Termine "
    "par : « Résumé généré par IA, à vérifier et approuver par le médecin. »"
)

FORMULATIONS_INTERDITES = (
    "recommand",
    "conseil",
    "diagnostic",
    "suspicion",
    "traitement",
    "consulter",
    "contactez",
    "refaire",
    "repeter",
    "surveiller",
    "inquiet",
    "preoccup",
    "il faut",
    "vous devez",
    "vous devriez",
    "devriez",
)


def _decimal(value):
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite() or len(number.as_tuple().digits) > 40:
        return None
    if number != 0 and abs(number.adjusted()) > 100:
        return None
    return number


def _normaliser_unite(value):
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = normalized.replace("μ", "µ")
    return re.sub(r"\s+", "", normalized).casefold()


def _unites_compatibles(first, second):
    return _normaliser_unite(first) == _normaliser_unite(second)


def statut_valeur(resultat):
    valeur = _decimal(resultat.valeur)
    if valeur is None:
        return "non déterminé"

    analyse = resultat.analyse_demandee.type_analyse
    unite_resultat = resultat.unite or analyse.unite
    if analyse.unite and not _unites_compatibles(unite_resultat, analyse.unite):
        return "non déterminé"
    if not _reference_coherente(analyse):
        return "non déterminé"
    minimum = analyse.valeur_reference_min
    maximum = analyse.valeur_reference_max
    if minimum is None and maximum is None:
        return "non déterminé"
    if minimum is not None and valeur < minimum:
        return "bas"
    if maximum is not None and valeur > maximum:
        return "élevé"
    return "normal"


def _reference(analyse):
    minimum = analyse.valeur_reference_min
    maximum = analyse.valeur_reference_max
    unite = analyse.unite
    if (
        (minimum is not None and _decimal(minimum) is None)
        or (maximum is not None and _decimal(maximum) is None)
        or (
            minimum is not None and maximum is not None
            and minimum > maximum
        )
    ):
        return "Incohérentes (à vérifier)"
    if minimum is not None and maximum is not None:
        plage = f"{minimum} à {maximum}"
    elif minimum is not None:
        plage = f"≥ {minimum}"
    elif maximum is not None:
        plage = f"≤ {maximum}"
    else:
        return "Non renseignées"
    return f"{plage} {unite}".strip()


def _date_resultat(resultat):
    return resultat.date_validation or resultat.date_saisie


def _reference_coherente(analyse):
    for field in (
        analyse.valeur_reference_min,
        analyse.valeur_reference_max,
        analyse.seuil_critique_bas,
        analyse.seuil_critique_haut,
    ):
        if field is not None and _decimal(field) is None:
            return False
    if (
        analyse.valeur_reference_min is not None
        and analyse.valeur_reference_max is not None
        and analyse.valeur_reference_min > analyse.valeur_reference_max
    ):
        return False
    if (
        analyse.seuil_critique_bas is not None
        and analyse.seuil_critique_haut is not None
        and analyse.seuil_critique_bas > analyse.seuil_critique_haut
    ):
        return False
    return True


def preparer_donnees(demande):
    lignes = []
    analyses = (
        demande.analyses.select_related("type_analyse")
        .prefetch_related("resultats")
        .exclude(statut=AnalyseDemandee.Statut.ANNULEE)
    )
    for analyse in analyses:
        resultat = analyse.resultats.filter(
            statut=Resultat.Statut.VALIDE,
        ).first()
        if resultat is None:
            continue

        type_analyse = analyse.type_analyse
        unite_actuelle = resultat.unite or type_analyse.unite
        unite_coherente = (
            not type_analyse.unite
            or _unites_compatibles(unite_actuelle, type_analyse.unite)
        )
        references_coherentes = _reference_coherente(type_analyse)
        reference = (
            _reference(type_analyse)
            if unite_coherente
            else "Non comparable : unité du résultat différente de l’unité configurée"
        )
        date_actuelle = _date_resultat(resultat)
        precedents = Resultat.objects.filter(
            analyse_demandee__demande__patient_id=demande.patient_id,
            analyse_demandee__demande__medecin_id=demande.medecin_id,
            analyse_demandee__type_analyse_id=analyse.type_analyse_id,
            statut=Resultat.Statut.VALIDE,
        ).filter(
            Q(date_validation__lt=date_actuelle)
            | Q(date_validation__isnull=True, date_saisie__lt=date_actuelle)
        ).exclude(
            analyse_demandee__demande_id=demande.pk,
        ).select_related(
            "analyse_demandee__type_analyse",
        )
        historique = []
        precedent = None
        historique_coherente = True
        for candidate in precedents:
            candidate_unit = (
                candidate.unite
                or candidate.analyse_demandee.type_analyse.unite
            )
            candidate_date = _date_resultat(candidate)
            if (
                not _unites_compatibles(unite_actuelle, candidate_unit)
                or candidate_date is None
            ):
                continue
            historique.append({
                "valeur": candidate.valeur,
                "unite": candidate_unit,
                "date": candidate_date,
                "numeric_value": _decimal(candidate.valeur),
            })
            if (
                _decimal(candidate.valeur) is None
                and any(char.isdigit() for char in candidate.valeur)
            ):
                historique_coherente = False
        historique.sort(key=lambda point: point["date"])
        compatible_candidates = [
            candidate for candidate in precedents
            if _unites_compatibles(
                unite_actuelle,
                candidate.unite
                or candidate.analyse_demandee.type_analyse.unite,
            )
            and _date_resultat(candidate) is not None
        ]
        compatible_candidates.sort(key=_date_resultat, reverse=True)
        precedent = compatible_candidates[0] if compatible_candidates else None
        current_numeric = _decimal(resultat.valeur)
        if current_numeric is not None:
            historique.append({
                "valeur": resultat.valeur,
                "unite": unite_actuelle,
                "date": date_actuelle,
                "numeric_value": current_numeric,
            })
        historique = historique[-20:]
        variation = None
        tendance = "insuffisante"
        if precedent is not None:
            previous_numeric = _decimal(precedent.valeur)
            if (
                current_numeric is not None
                and previous_numeric is not None
                and previous_numeric != 0
                and unite_coherente
                and references_coherentes
            ):
                with localcontext() as context:
                    context.prec = 250
                    variation = (
                        (current_numeric - previous_numeric)
                        / abs(previous_numeric)
                        * Decimal("100")
                    ).quantize(Decimal("0.01"))
                tendance = (
                    "stable"
                    if abs(variation) <= Decimal("5")
                    else "en hausse"
                    if variation > 0
                    else "en baisse"
                )
        if not unite_coherente or not references_coherentes:
            tendance = "insuffisante"
            variation = None
        if precedent is None:
            variation_text = "Aucun résultat précédent comparable"
        elif variation is not None:
            sign = "+" if variation > 0 else ""
            variation_text = f"{tendance} · {sign}{variation}%"
        elif current_numeric is None or _decimal(precedent.valeur) is None:
            variation_text = (
                "Données insuffisantes pour calculer une variation numérique"
            )
        elif _decimal(precedent.valeur) == 0:
            variation_text = "Données insuffisantes : valeur précédente nulle"
        else:
            variation_text = "Données incohérentes : comparaison non interprétée"
        has_unparsed_numeric = (
            current_numeric is None and any(char.isdigit() for char in resultat.valeur)
        )
        lignes.append({
            "analyse": type_analyse.nom,
            "valeur": resultat.valeur,
            "unite": unite_actuelle,
            "reference": reference,
            "statut": statut_valeur(resultat),
            "valeur_precedente": precedent.valeur if precedent else "",
            "unite_precedente": (
                precedent.unite or precedent.analyse_demandee.type_analyse.unite
                if precedent else ""
            ),
            "date_precedente": _date_resultat(precedent) if precedent else None,
            "date_actuelle": date_actuelle,
            "evolution": variation_text,
            "variation_pct": str(variation) if variation is not None else None,
            "tendance": tendance,
            "historique": historique,
            "donnee_coherente": (
                unite_coherente and references_coherentes
                and not has_unparsed_numeric and historique_coherente
            ),
        })
    return lignes


def _donnees_pseudonymisees(lignes):
    if not lignes:
        raise ResumeAPIError(
            "Aucun résultat publié n’est disponible pour créer le résumé.",
            code="no_results",
        )
    rows = []
    for ligne in lignes:
        donnees_coherentes = ligne.get("donnee_coherente", True)
        row = {}
        for field in CHAMPS_RESUME_API:
            value = str(ligne.get(field, "") or "").strip()
            if len(value) > 255:
                raise ResumeAPIError(
                    "Une donnée dépasse la longueur autorisée.",
                    code="invalid_data",
                )
            row[field] = value
        if not donnees_coherentes:
            row["reference"] = "Non comparable : données à vérifier"
            row["statut"] = "non déterminé"
            row["valeur_precedente"] = ""
            row["unite_precedente"] = ""
            row["evolution"] = "Comparaison non calculée : données à vérifier"
        if not row["analyse"] or not row["valeur"]:
            raise ResumeAPIError(
                "Un résultat ne contient pas les données minimales attendues.",
                code="invalid_data",
            )
        rows.append(row)
    return rows


def _message_erreur_http(status_code):
    if status_code in (401, 403):
        return "authentification ou accès refusé"
    if status_code == 404:
        return "endpoint ou modèle introuvable"
    if status_code == 429:
        return "quota ou limite de requêtes dépassé"
    if status_code >= 500:
        return "service fournisseur indisponible"
    return "requête fournisseur refusée"


def _est_erreur_delai(error):
    if isinstance(error, TimeoutError):
        return True
    return isinstance(error, URLError) and isinstance(
        error.reason,
        TimeoutError,
    )


def _poster_json(request):
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise ResumeAPIError(
            _message_erreur_http(error.code),
            code="http_error",
            status_code=error.code,
        ) from error
    except (TimeoutError, URLError, OSError) as error:
        code = "timeout" if _est_erreur_delai(error) else "network_error"
        message = (
            "Le fournisseur IA n’a pas répondu dans le délai imparti. "
            "Aucun résumé n’a été enregistré ; réessayez dans quelques instants."
            if code == "timeout"
            else "erreur de connexion réseau"
        )
        raise ResumeAPIError(message, code=code) from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResumeAPIError(
            "réponse JSON invalide",
            code="invalid_response",
        ) from error


def _appeler_gemini(lignes, model=None):
    api_key = getattr(settings, "GOOGLE_API_KEY", "").strip() or getattr(settings, "GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ResumeAPIError("Clé Gemini non configurée.")

    model = model or getattr(settings, "GEMINI_MODEL", "").strip() or "gemini-3.8-flash"
    payload = {
        "model": model,
        "input": json.dumps(_donnees_pseudonymisees(lignes), ensure_ascii=False),
        "system_instruction": CONSIGNE_RESUME,
        "store": False,
    }
    request = Request(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    body = _poster_json(request)

    try:
        if body.get("status") != "completed":
            raise ResumeAPIError(
                "interaction non terminée",
                code="incomplete_response",
            )
        text = "\n".join(
            part["text"]
            for step in body["steps"]
            if step.get("type") == "model_output"
            for part in step.get("content", [])
            if part.get("type") == "text" and part.get("text")
        ).strip()
    except (KeyError, AttributeError, TypeError) as error:
        raise ResumeAPIError(
            "structure de réponse invalide",
            code="invalid_response",
        ) from error
    if not text:
        raise ResumeAPIError("réponse sans texte", code="empty_response")
    return text


def _appeler_anthropic(lignes):
    payload = {
        "model": settings.IA_MODELE,
        "max_tokens": 700,
        "system": CONSIGNE_RESUME,
        "messages": [{
            "role": "user",
            "content": json.dumps(
                _donnees_pseudonymisees(lignes),
                ensure_ascii=False,
            ),
        }],
    }
    request = Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": settings.ANTHROPIC_API_KEY,
        },
        method="POST",
    )
    body = _poster_json(request)

    try:
        text = "\n".join(
            block["text"]
            for block in body["content"]
            if block.get("type") == "text" and block.get("text")
        ).strip()
    except (KeyError, TypeError) as error:
        raise ResumeAPIError(
            "structure de réponse invalide",
            code="invalid_response",
        ) from error
    if not text:
        raise ResumeAPIError("réponse sans texte", code="empty_response")
    return text


def _contient_formulation_interdite(texte):
    normalized = unicodedata.normalize("NFKD", texte)
    normalized = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return any(term in normalized for term in FORMULATIONS_INTERDITES)


def generer_resume(lignes):
    google_key = getattr(settings, "GOOGLE_API_KEY", "").strip() or getattr(settings, "GEMINI_API_KEY", "").strip()
    anthropic_key = getattr(settings, "ANTHROPIC_API_KEY", "").strip()
    if not google_key and not anthropic_key:
        raise ResumeAPIError(
            "Aucun fournisseur IA n’est configuré. Configurez GOOGLE_API_KEY "
            "ou ANTHROPIC_API_KEY pour générer le résumé.",
            code="missing_api_key",
        )

    provider = "Gemini" if google_key else "Anthropic"
    model = (
        getattr(settings, "GEMINI_MODEL", "").strip() or "gemini-3.8-flash"
        if google_key
        else getattr(settings, "IA_MODELE", "").strip() or "claude-sonnet-4-5"
    )
    started = time.monotonic()
    try:
        if google_key:
            fallback_model = (
                getattr(settings, "GEMINI_FALLBACK_MODEL", "").strip()
                or "gemini-3.5-flash-lite"
            )
            try:
                texte = _appeler_gemini(lignes, model=model)
            except ResumeAPIError as primary_error:
                if (
                    (
                        primary_error.status_code != 503
                        and primary_error.code != "timeout"
                    )
                    or not fallback_model
                    or fallback_model == model
                ):
                    raise
                logger.warning(
                    "Modèle Gemini indisponible: modèle=%s cause=%s repli=%s",
                    model,
                    (
                        f"http_status={primary_error.status_code}"
                        if primary_error.status_code
                        else primary_error.code
                    ),
                    fallback_model,
                )
                model = fallback_model
                texte = _appeler_gemini(lignes, model=model)
        else:
            texte = _appeler_anthropic(lignes)
    except ResumeAPIError as error:
        duration_ms = round((time.monotonic() - started) * 1000)
        logger.warning(
            "Résumé IA en échec: fournisseur=%s modèle=%s "
            "code=%s http_status=%s durée_ms=%s",
            provider,
            model,
            error.code,
            error.status_code or "-",
            duration_ms,
        )
        raise
    if _contient_formulation_interdite(texte):
        duration_ms = round((time.monotonic() - started) * 1000)
        logger.warning(
            "Réponse IA écartée par le filtre de contenu: "
            "fournisseur=%s modèle=%s code=content_guard durée_ms=%s",
            provider,
            model,
            duration_ms,
        )
        raise ResumeAPIError(
            "La réponse IA a été écartée car elle pouvait contenir un conseil "
            "ou une interprétation médicale. Aucun résumé n’a été enregistré.",
            code="content_guard",
        )
    duration_ms = round((time.monotonic() - started) * 1000)
    logger.info(
        "Résumé généré par fournisseur IA: fournisseur=%s modèle=%s "
        "durée_ms=%s caractères_sortie=%s",
        provider,
        model,
        duration_ms,
        len(texte),
    )
    return ResumeGeneration(texte, "ia", fournisseur=provider, modele=model)
