# Accessibilité du module Stocks médicaux

Cas d'usage ciblé : un personnel soignant ou de laboratoire consulte le stock dans une réserve peu éclairée,
avec des gants, parfois avec une déficience visuelle ou motrice. L'accessibilité est donc pensée autour des **alertes** et de la **saisie**.

## Fonctionnalités liées au sujet
| Besoin | Réalisation | Critère WCAG |
|---|---|---|
| Alerte critique perçue sans la vue | Bandeau `role="alert"` + bouton « Lire les alertes à voix haute » (Web Speech API, fr-FR) | 4.1.3, 1.1.1 |
| Statut jamais indiqué par la couleur seule | Chaque statut = icône + texte (« Rupture », « Périmé »…) | 1.4.1 |
| Niveau de stock compréhensible | Jauge `<meter>` avec `aria-label` et `aria-valuetext` | 1.1.1, 4.1.2 |
| Lecture en faible luminosité / basse vision | Barre « Confort de lecture » : texte ×1,18 / ×1,36, mode contraste élevé, mémorisé (localStorage) | 1.4.3, 1.4.4, 1.4.6 |
| Saisie fiable des quantités | `max` = stock disponible, `min` = date du jour, `inputmode="numeric"` ; validation navigateur active | 3.3.1, 3.3.2 |
| Erreurs de formulaire | Résumé `role="alert"` avec liens vers les champs, `aria-invalid`, `aria-describedby` | 3.3.1, 3.3.3 |
| Navigation clavier | Lien d'évitement, `:focus-visible` épais, `aria-current` sur la navigation, boutons d'action nommés par produit | 2.4.1, 2.4.7, 2.4.4 |
| Structure | Un seul `h1`, aucun saut de niveau, `<caption>` et `scope` sur tous les tableaux, `<nav>` pour la pagination | 1.3.1, 2.4.6 |
| Mouvement | `prefers-reduced-motion` respecté | 2.3.3 |

## Preuves automatisées
`python manage.py test stock.tests.AccessibiliteTests` vérifie titres, légendes, labels, lien d'évitement, alertes, jauge,
erreurs, validation client et **ratios de contraste ≥ 4,5:1**.

## Audit à montrer au jury (manuel)
1. Chrome → F12 → onglet **Lighthouse** → catégorie *Accessibility* → analyser `/stock/`, `/stock/produits/`, `/stock/produits/nouveau/`. Garder les captures.
2. Extension **axe DevTools** : « Scan all of my page ».
3. Test clavier : Tab / Maj+Tab / Entrée sur le tableau de bord, la liste, un formulaire (sans souris).
4. Lecteur d'écran (NVDA, gratuit) : ouvrir `/stock/` et vérifier l'annonce de l'alerte.
