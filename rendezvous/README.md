# Module Rendez-vous (Ali)

## Fonctionnalités

| Rôle | Ce qu'il peut faire |
|---|---|
| Patient | Décrire son motif et recevoir une suggestion de spécialité (IA), réserver un créneau, déplacer ou annuler son rendez-vous (jusqu'à 2 h avant), consulter son calendrier |
| Médecin | Générer son planning, ajouter, modifier, bloquer ou supprimer des créneaux, confirmer, déplacer, annuler ou clôturer (honoré / absent) ses rendez-vous |
| Admin | Tout, pour tous les médecins |
| Laboratoire | Aucun accès |

**CRUD :** Créneau (create, read, update, delete) et RendezVous (create = réserver, read, update = déplacer ou modifier le motif, delete logique = annuler, avec l'historique conservé).

**Double réservation impossible :**
- une contrainte unique en base de données (`rdv_un_seul_actif_par_creneau`) ;
- un verrou transactionnel ;
- une vérification du chevauchement des rendez-vous d'un même patient.

## IA : suggestion de spécialité

- **Besoin :** le patient ne sait pas toujours quel spécialiste consulter. Il décrit son motif et l'application lui propose 3 spécialités, avec les médecins correspondants.
- **Modèle :** TF-IDF sur les mots (1-2 grammes) et sur les caractères (3-5 grammes, ce qui le rend tolérant aux fautes de frappe), puis une régression logistique (scikit-learn).
- **Données :** `ia/donnees/motifs.csv` (263 motifs, 12 spécialités) et `ia/donnees/lexique.csv` (454 termes médicaux).
- **Évaluation :** lancer `python manage.py evaluer_ia_rdv`. Les résultats s'affichent sur la page « Performance IA ».

| Mesure | Résultat |
|---|---|
| F1 macro, test indépendant (60 motifs jamais vus) | **0,78** |
| Bonne spécialité parmi les 3 proposées | **92 %** |
| Sans lexique (ablation) | 0,66 |
| Validation croisée 5 plis | 0,92 ± 0,02 |
| Référence naïve (classe majoritaire) | 0,02 |
| Temps de réponse | environ 2 ms (p95 environ 3 ms) |

- **Pourquoi pas Celery :** une prédiction prend environ 2 ms, l'appel reste donc synchrone sans bloquer l'utilisateur. Une file Celery/Redis ne se justifierait que pour un modèle lent, comme un LLM.
- **Gestion des erreurs :**
  - motif trop court : erreur 400 ;
  - modèle indisponible : erreur 503 avec un message clair ;
  - côté navigateur : indicateur de chargement, et `aria-live` pour les lecteurs d'écran.

## Commandes

```bash
python manage.py migrate
python manage.py seed_rendezvous        # créneaux et rendez-vous de démonstration
python manage.py evaluer_ia_rdv         # métriques de l'IA
python manage.py test rendezvous        # 51 tests
coverage run --source=rendezvous --omit="*/migrations/*,*/tests.py,*/management/*" manage.py test rendezvous
coverage html                           # rapport dans htmlcov/index.html (87 %)
```

## Accessibilité

- Les pages du module ont été auditées avec axe-core (WCAG 2.1 A/AA) : **0 violation**.
- Titres hiérarchisés, `nav` et `section` avec libellés, `caption` et `scope` dans les tableaux.
- Les emojis sont masqués aux lecteurs d'écran (`aria-hidden`).
- Focus clavier visible (3 px).
- Une réservation complète se fait au clavier seul (Tab, Entrée).
