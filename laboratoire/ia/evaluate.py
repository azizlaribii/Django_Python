import time
from pathlib import Path

from .chatbot import answer_question


EVALUATION_CASES = [
    ("Dois-je être à jeun ?", "fasting"),
    ("هل يجب أن أكون صائما قبل التحليل؟", "fasting"),
    ("Do I need to fast before my test?", "fasting"),
    ("lezemni nsoum 9bal analyse?", "fasting"),
    ("Quel est le délai des résultats ?", "delay"),
    ("متى تظهر نتائج التحاليل؟", "delay"),
    ("When will my results be ready?", "delay"),
    ("wa9tech ykounou les resultats?", "delay"),
    ("Que veut dire LDL ?", "ldl"),
    ("Comment télécharger mon PDF ?", "pdf"),
    ("Comment lire l’évolution de mes résultats ?", "trend"),
    ("Qui peut m’expliquer mes résultats ?", "doctor"),
    ("Pourquoi un résultat n’apparaît-il pas ?", "missing"),
    ("Qui peut voir mes résultats ?", "privacy"),
    ("Dois-je prendre rendez-vous ?", "appointment"),
    ("كيف يتم سحب عينة الدم؟", "blood-draw"),
    ("What is a reference range?", "normal-range"),
    ("chnaamel ken ma3loumeti ghalta?", "correction"),
    ("كيف أتواصل مع المختبر؟", "contact"),
    ("Why are the measurement units different?", "units"),
    ("My result is outside the range, what should I do?", "high-low"),
    ("What if my information is incorrect?", "correction"),
    ("Write me a poem about the sea.", None),
    ("Who won the football match?", None),
    ("Can you recommend a movie?", None),
]
METRICS_PATH = Path(__file__).with_name("metrics_chatbot.txt")


def evaluate():
    correct = 0
    elapsed_ms = []
    for question, expected_faq_id in EVALUATION_CASES:
        started = time.perf_counter()
        answer = answer_question(question)
        elapsed_ms.append((time.perf_counter() - started) * 1000)
        if expected_faq_id is None:
            correct += answer.fallback
        else:
            correct += answer.faq_id == expected_faq_id

    accuracy = correct / len(EVALUATION_CASES) * 100
    average_ms = sum(elapsed_ms) / len(elapsed_ms)
    report = (
        f"Questions évaluées : {len(EVALUATION_CASES)}\n"
        f"Questions hors sujet : 3\n"
        f"Réponses correctes : {correct}/{len(EVALUATION_CASES)}\n"
        f"Taux de bonnes réponses : {accuracy:.2f}%\n"
        f"Temps moyen : {average_ms:.2f} ms\n"
    )
    METRICS_PATH.write_text(report, encoding="utf-8")
    return report


if __name__ == "__main__":
    print(evaluate(), end="")
