import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


FAQ_PATH = Path(__file__).with_name("faq.json")
MIN_INTENT_CONFIDENCE = 0.75
FALLBACK_ANSWER = (
    "Je suis spécialisé dans les questions sur le laboratoire et les analyses. "
    "Je ne peux pas répondre à ce sujet, mais je peux vous aider avec vos "
    "demandes, vos résultats publiés ou la préparation d’un prélèvement."
)
GREETING_ANSWER = (
    "Bonjour ! Je peux vous aider sur les analyses, la préparation des "
    "prélèvements, le suivi de vos demandes et l’accès à vos résultats publiés."
)
MEDICAL_ANSWER = (
    "Je ne peux pas recommander de médicament ou de traitement ni poser de "
    "diagnostic. Adressez-vous à votre médecin ou à un professionnel de santé."
)
PRIVACY_ANSWER = (
    "Je ne peux pas accéder aux dossiers ni communiquer les résultats d’autres "
    "patients. Connectez-vous à votre compte pour consulter uniquement vos "
    "propres résultats publiés."
)
CLARIFICATION_ANSWER = (
    "Pouvez-vous préciser votre question ? Je peux aider sur les analyses, les "
    "prélèvements, le suivi des demandes et vos résultats publiés."
)
STATUS_CLARIFICATION_ANSWER = (
    "Parlez-vous de l’avancement de votre demande ou de la disponibilité de "
    "vos résultats ?"
)


@dataclass(frozen=True)
class QuestionIntent:
    category: str
    faq_id: str | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class ChatbotAnswer:
    answer: str
    fallback: bool
    faq_id: str | None = None
    intent: str = "out_of_scope"


def _normalize(value):
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).strip()


_TYPO_ALIASES = {
    "bonjor": "bonjour",
    "cholestrol": "cholesterol",
    "glycemi": "glycemie",
    "glycem": "glycemie",
    "resulat": "resultat",
    "resulats": "resultats",
    "resulta": "resultat",
}


def _normalize_question(question):
    text = _normalize(question)
    tokens = text.split()
    corrected = [_TYPO_ALIASES.get(token, token) for token in tokens]
    changed = corrected != tokens
    return " ".join(corrected), changed


def _contains(text, phrases):
    padded_text = f" {text} "
    return any(f" {_normalize(phrase)} " in padded_text for phrase in phrases)


@lru_cache(maxsize=1)
def _get_faq():
    with FAQ_PATH.open(encoding="utf-8") as faq_file:
        entries = json.load(faq_file)
    if not isinstance(entries, list) or len(entries) < 15:
        raise ValueError("La FAQ du laboratoire doit contenir au moins 15 entrées.")
    faq = {}
    seen_questions = set()
    for entry in entries:
        faq_id = entry.get("id")
        questions = entry.get("questions")
        answers = entry.get("answers")
        if (
            not isinstance(faq_id, str)
            or faq_id in faq
            or not isinstance(questions, dict)
            or not isinstance(answers, dict)
            or not isinstance(questions.get("fr"), str)
            or not isinstance(answers.get("fr"), str)
        ):
            raise ValueError(f"Entrée FAQ invalide ou dupliquée : {faq_id!r}.")
        for language, question in questions.items():
            if not isinstance(question, str) or not isinstance(answers.get(language), str):
                raise ValueError(
                    f"Entrée FAQ incomplète : {faq_id!r}, langue {language!r}."
                )
            normalized_question = _normalize(question)
            if not normalized_question or normalized_question in seen_questions:
                raise ValueError(f"Question FAQ vide ou dupliquée : {question!r}.")
            seen_questions.add(normalized_question)
        faq[faq_id] = entry
    return faq


def _language_for(question):
    if re.search(r"[\u0600-\u06ff]", question):
        return "ar"
    text = _normalize(question)
    if re.search(
        r"\b(wa9tech|chnoua|chnouwa|chnohwa|kifech|nchouf|nchouf|"
        r"naaref|mte3i|mta3i|nsoum|lezemni|chkoun|thadhar)\b",
        text,
    ):
        return "tn"
    if re.search(
        r"\b(what|when|where|why|how|who|can|my|the|is|do|does|need|"
        r"results|test|please)\b",
        text,
    ):
        return "en"
    return "fr"


def classify_intent(question):
    text, typo_corrected = _normalize_question(question)
    if not text:
        return QuestionIntent("ambiguous_question", confidence=0.0)

    tokens = set(text.split())
    confidence = 0.88 if typo_corrected else 0.99

    # Priority 1: requests for another person's records are denied before any
    # general result, delay, or audit-history rule is considered.
    data_terms = {
        "resultat", "resultats", "dossier", "dossiers", "donnee", "donnees",
        "information", "informations", "medical", "medicaux", "historique",
        "journal", "records", "data",
    }
    patient_terms = {
        "patient", "patients", "patiente", "patientes",
        "patienten", "patientses",
    }
    other_person_terms = {
        "tous", "toutes", "autres", "autre", "all", "other", "everyone",
        "tousles", "nesskol",
    }
    requests_data = bool(tokens & data_terms)
    mentions_patients = bool(tokens & patient_terms)
    requests_other_people = bool(tokens & other_person_terms)
    tunisian_all_patients = _contains(
        text,
        (
            "resultats mta3 ness kol",
            "resultats mte3 ness kol",
            "resultat mta3 ness kol",
            "resultat mte3 ness kol",
            "dossiers mta3 ness kol",
            "dossiers mte3 ness kol",
        ),
    )
    if requests_data and (
        (mentions_patients and requests_other_people) or tunisian_all_patients
    ):
        return QuestionIntent("confidential_data_request", "privacy-denied", 1.0)
    if requests_data and mentions_patients and _contains(
        text,
        ("donne moi", "affiche", "montre", "consulter", "voir", "access", "show"),
    ):
        return QuestionIntent("confidential_data_request", "privacy-denied", 0.98)

    # Priority 2: explain publication rules, never inspect an individual record.
    if _contains(text, (
        "pas encore publie", "pas publie", "non publie", "resultat non publie",
        "resultats non publies", "pas encore disponible", "resultat absent",
        "resultat manquant", "resultat n apparait", "not published",
        "not available yet", "missing result", "resultat ma yodhherch",
        "resultat mte3i mazel ma thadharsh",
        "kifech naaref ken resultat mte3i thadhar",
        "نتيجتي لم تنشر", "لماذا لا تظهر إحدى النتائج",
    )):
        return QuestionIntent("result_publication_status", "missing", confidence)

    # Priority 3: greet only when the rest of the message is a general help
    # request. A greeting does not override an unrelated or sensitive question.
    greeting_terms = {
        "bonjour", "bonsoir", "salut", "coucou", "hello", "hi",
        "asslema", "aslema", "salam", "slm",
    }
    help_terms = {
        "aide", "aider", "help", "svp", "please", "stp", "peux", "peut",
        "tu", "vous", "me", "m", "j", "ai", "une", "question", "can",
        "you", "s", "il", "plait", "sil", "a3awenni",
    }
    if tokens & greeting_terms and tokens.issubset(greeting_terms | help_terms):
        return QuestionIntent("greeting_help", "greeting", 0.98)
    if _contains(text, (
        "peux tu m aider", "pourriez vous m aider", "can you help me",
        "tnajem t3aweni",
    )) and not (tokens & data_terms):
        return QuestionIntent("greeting_help", "greeting", 0.95)

    if _contains(text, (
        "ou en suis je", "ou j en suis", "ou en sommes nous",
        "where am i", "where do i stand", "win weslet",
        "win waslet", "win wselit", "kifech el demande",
    )):
        return QuestionIntent(
            "ambiguous_question",
            "status-clarification",
            0.65,
        )

    # Medical requests are always handled cautiously, not answered by the FAQ.
    if _contains(text, (
        "medicament", "medicaments", "traitement", "prescrire", "prescription",
        "dose de", "quel dosage", "que dois je prendre", "quoi prendre",
        "symptome", "symptomes", "douleur", "j ai mal", "fievre", "fever",
        "which medication", "what medicine", "what treatment", "dosage",
        "symptoms", "chneya dawa", "chnowa dawa", "chneya douwa",
    )):
        return QuestionIntent("medical_request", "medical-safety", 0.99)

    # Specific analyte names are resolved before broad laboratory terms.
    if "hdl" in tokens:
        return QuestionIntent("hdl", "hdl", 0.99)
    if "ldl" in tokens:
        return QuestionIntent("ldl", "ldl", 0.99)
    if _contains(text, (
        "glycemie", "glycemia", "taux de sucre dans le sang",
        "blood sugar test", "chnohwa analyse glycemie",
        "chnouwa analyse glycemie", "chnoua analyse glycemie",
        "c est quoi une analyse de glycemie",
        "qu est ce qu une analyse de glycemie",
        "analyse glycemie",
    )):
        return QuestionIntent("glycemia", "glycemia", confidence)

    # A specific question about who changed data is different from general
    # sample traceability; it never returns an identity or audit entry.
    if _contains(text, (
        "qui a modifie", "qui a modifier", "qui a change", "qui a corrige",
        "qui a valide", "qui a valider", "nom du technicien",
        "nom de la personne qui a valide", "auteur de la validation",
        "auteur validation", "technicien qui a valide",
        "qui a valide cette analyse", "qui a valide mon analyse",
        "who modified", "who changed", "who validated",
        "name of the technician", "author of the validation",
        "chkoun validate", "chkoun validi",
    )):
        return QuestionIntent("result_history_access", "audit-history", 0.99)

    if _contains(text, (
        "traceabilite", "tracabilite", "historique du prelevement",
        "suivi du prelevement", "comment fonctionne le suivi",
        "sample tracking", "track a sample", "suivi echantillon",
        "comment fonctionne le suivi d un prelevement",
    )) and _contains(text, (
        "prelevement", "echantillon", "sample", "suivi", "traceabilite",
        "tracabilite",
    )):
        return QuestionIntent("sample_tracking_general", "sample-tracking-general", confidence)

    if _contains(text, (
        "historique des modifications", "historique de modification",
        "journal des modifications", "historique du resultat",
        "acceder a l historique", "voir l historique", "audit history",
        "change history", "audit trail",
    )):
        return QuestionIntent("result_history_access", "audit-history", confidence)

    if _contains(text, (
        "a jeun", "etre jeune", "jeuner", "jeune avant", "fasting",
        "fast before", "nsoum", "siyem", "9bal analyse",
        "comment etre un jeune", "comment etre jeune", "etre un jeune",
        "هل يجب ان اكون صائما قبل التحليل",
    )):
        return QuestionIntent("fasting", "fasting", confidence)

    if _contains(text, (
        "wa9tech", "delai", "delai des resultats", "combien de temps", "quand sera disponible",
        "quand sera pret", "quand seront disponibles", "quand le resultat sera",
        "quand le resultat sera t il", "when will", "wa9tech yitla3",
        "wa9tech yetla3",
        "how long", "متى تظهر نتائج التحاليل",
        "wa9tech yitla3 el resultat", "wa9tech yetla3 el resultat",
    )):
        return QuestionIntent("analysis_delay", "delay", confidence)

    if _contains(text, (
        "qui peut voir mes resultats", "qui voit mes resultats",
        "who can see my results",
        "chkoun ynajem ychouf les resultats mte3i",
        "من يستطيع الاطلاع على نتائجي",
    )):
        return QuestionIntent("laboratory_info", "privacy", confidence)

    if _contains(text, (
        "mes resultats sont ils disponibles", "resultats disponibles",
        "disponibilite de mes resultats", "mon resultat est disponible",
        "est ce que mon resultat est disponible",
        "kifech naaref ken resultat mte3i thadhar",
        "resultat mte3i thadhar",
    )):
        return QuestionIntent("result_publication_status", "missing", confidence)

    if _contains(text, (
        "consulter mes resultats", "consulter resultat", "consulter les resultats",
        "voir mes resultats", "acceder a mes resultats",
        "comment consulter mes resultats", "where can i see my results",
        "how can i access my results", "kifech nchouf resultat mte3i",
        "kifech nchouf les resultats", "nchouf resultat mte3i",
        "nchouf resultat", "kifech nchouf resultat",
    )):
        return QuestionIntent("result_access", "tracking", confidence)

    if _contains(text, (
        "suivre mes resultats", "suivi de mes resultats",
        "suivre mes demandes", "avancement de ma demande",
        "track my results", "track my request", "ta9addom demande",
        "suivi resultats", "كيف أتابع نتائج تحاليلي",
    )):
        return QuestionIntent("result_access", "tracking", confidence)

    if _contains(text, (
        "prise de sang", "prelevement", "prise echantillon",
        "blood draw", "blood sample", "s7ab 3ina", "s7ab dam",
        "كيف يتم سحب عينة الدم",
    )):
        return QuestionIntent("sample_tracking_general", "blood-draw", confidence)

    faq_rules = (
        ("normal-range", ("plage de reference", "valeurs de reference", "reference range", "valeurs normales")),
        ("high-low", ("hors norme", "hors plage", "en dehors de la plage", "outside the range", "barra valeurs")),
        ("units", ("unite", "units", "measurement unit")),
        ("doctor", ("qui peut m expliquer mes resultats", "who can explain my results", "tbib yfassar les resultats")),
        ("appointment", ("rendez vous", "appointment", "naamel rendez vous")),
        ("correction", ("informations incorrectes", "corriger mes informations", "wrong information", "what if my information is incorrect", "ma3loumeti ghalta", "ماذا أفعل إذا كانت معلوماتي غير صحيحة")),
        ("contact", ("contacter le laboratoire", "contact laboratoire", "contact the laboratory", "netwasel maa el laboratoire", "كيف أتواصل مع المختبر")),
        ("pdf", ("pdf", "telecharger", "download", "nhabet")),
        ("privacy", ("qui peut voir mes resultats", "who can see my results", "chkoun ynajem ychouf les resultats mte3i")),
        ("trend", ("evolution de mes resultats", "lire mes resultats dans le temps", "trend in my results")),
    )
    for faq_id, phrases in faq_rules:
        if _contains(text, phrases):
            return QuestionIntent("laboratory_info", faq_id, confidence)

    if tokens & {
        "laboratoire", "laboratory", "analyse", "analyses", "glycemie",
        "resultat", "resultats", "prelevement", "echantillon", "demande",
        "bilan", "cholesterol", "hdl", "ldl",
    }:
        return QuestionIntent("ambiguous_question", "clarification", 0.55)

    if _contains(text, (
        "besoins non fonctionnels", "fonctionnalites non fonctionnelles",
        "ergonomie performance securite",
        "capitale du japon", "capital japon", "capital du japon",
        "programmation", "programmer", "python", "java",
        "voiture electrique", "karhba electrique",
        "recette", "pizza", "meteo", "sport", "cuisine", "geographie",
        "calculer", "addition", "write a song", "song about mars",
        "شنوة عاصمة اليابان", "شنوة طقس اليوم",
    )):
        return QuestionIntent("out_of_scope", confidence=confidence)

    if "?" in str(question or ""):
        return QuestionIntent(
            "ambiguous_question",
            "clarification",
            0.55,
        )
    return QuestionIntent("out_of_scope", confidence=0.98)


def answer_question(question):
    intent = classify_intent(question)
    if intent.category == "ambiguous_question":
        if intent.faq_id == "status-clarification":
            return ChatbotAnswer(
                STATUS_CLARIFICATION_ANSWER,
                False,
                "status-clarification",
                intent.category,
            )
        return ChatbotAnswer(
            CLARIFICATION_ANSWER,
            False,
            "clarification",
            intent.category,
        )
    if intent.confidence < MIN_INTENT_CONFIDENCE:
        return ChatbotAnswer(
            CLARIFICATION_ANSWER,
            False,
            "clarification",
            "ambiguous_question",
        )
    if intent.category == "greeting_help":
        return ChatbotAnswer(GREETING_ANSWER, False, "greeting", intent.category)
    if intent.category == "confidential_data_request":
        return ChatbotAnswer(PRIVACY_ANSWER, False, "privacy-denied", intent.category)
    if intent.category == "medical_request":
        return ChatbotAnswer(MEDICAL_ANSWER, False, "medical-safety", intent.category)
    if intent.category == "out_of_scope":
        return ChatbotAnswer(FALLBACK_ANSWER, True, None, intent.category)

    faq_entry = _get_faq().get(intent.faq_id)
    if faq_entry is None:
        raise ValueError(f"Intention FAQ inconnue : {intent.faq_id!r}.")
    language = _language_for(question)
    answer = faq_entry["answers"].get(language) or faq_entry["answers"]["fr"]
    return ChatbotAnswer(answer, False, intent.faq_id, intent.category)
