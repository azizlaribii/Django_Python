"""Évalue le modèle de suggestion de spécialité et enregistre les métriques.

Usage : python manage.py evaluer_ia_rdv
Écrit rendezvous/ia/donnees/metriques.json, affiché sur la page « Performance IA ».
"""
import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from rendezvous.ia.classifieur import FICHIER_METRIQUES, evaluer


class Command(BaseCommand):
    help = "Évalue l'IA de suggestion de spécialité (F1, matrice de confusion, latence)."

    def handle(self, *args, **opts):
        self.stdout.write("Évaluation en cours (hold-out, validation croisée 5 plis, test indépendant)…")
        m = evaluer()
        m["date_evaluation"] = timezone.now().isoformat(timespec="seconds")
        FICHIER_METRIQUES.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
        ind = m["test_independant"]
        self.stdout.write(f"  Motifs : {m['nb_motifs']} · Classes : {m['nb_classes']} · Lexique : {m['nb_termes_lexique']} termes")
        self.stdout.write(f"  Hold-out ({m['nb_test']} motifs) : F1 macro {m['f1_macro']:.2f} · top-3 {m['top3_accuracy']:.0%}")
        self.stdout.write(f"  Validation croisée : F1 {m['cv_f1_moyenne']:.2f} ± {m['cv_f1_ecart_type']:.2f}")
        self.stdout.write(f"  Test indépendant ({ind['nb']} motifs) : F1 macro {ind['f1_macro']:.2f} · "
                          f"accuracy {ind['accuracy']:.0%} · top-3 {ind['top3_accuracy']:.0%}")
        self.stdout.write(f"  Sans lexique : F1 {ind['f1_sans_lexique']:.2f} · Référence naïve : F1 {m['f1_reference_naive']:.2f}")
        self.stdout.write(f"  Latence : {m['latence_ms_moyenne']} ms en moyenne, {m['latence_ms_p95']} ms au 95e centile")
        self.stdout.write(self.style.SUCCESS(f"Métriques enregistrées dans {FICHIER_METRIQUES}"))
