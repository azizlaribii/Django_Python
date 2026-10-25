# 🏥 SantéConnect — Application Médicale Django

Application web Django complète pour la gestion des comptes et la collaboration entre **Docteurs**, **Laboratoires d'Analyses**, **Patients** et l'**Administrateur**.

---

## 🚀 Démarrage Rapide

1. **Activer l'environnement virtuel :**
   ```powershell
   .\venv\Scripts\activate
   ```

2. **Appliquer les migrations :**
   ```powershell
   python manage.py migrate
   ```

3. **Lancer le serveur Django :**
   ```powershell
   python manage.py runserver
   ```

4. **Accéder à l'application dans votre navigateur :**
   - 🌐 **Portail Web Principal :** [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
   - 🔐 **Page de Connexion :** [http://127.0.0.1:8000/login/](http://127.0.0.1:8000/login/)
   - 📝 **Inscription Multi-rôles :** [http://127.0.0.1:8000/register/](http://127.0.0.1:8000/register/)
   - ⚙️ **Console Django Admin :** [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

---

## 🔑 Identifiants des Comptes de Démonstration (Pré-configurés)

Créez ou réinitialisez les comptes de démonstration avec `python manage.py seed_demo_data` :

| Rôle | Nom d'utilisateur | Mot de passe | Rôle & Permissions |
| :--- | :--- | :--- | :--- |
| **👑 Administrateur** | `admin` | `admin123` | Superutilisateur & Accès Django Admin complet |
| **🩺 Docteur** | `dr_moreau` | `docteur123` | Médecin (Cardiologie & Médecine Générale) |
| **🔬 Laborantin** | `labo_pasteur` | `labo123` | Gérer les demandes, prélèvements et saisir/corriger les résultats non validés |
| **👤 Patient** | `patient_martin` | `patient123` | Dossier Patient (Groupe O+) |

---

## 🧪 Lancer et tester le module Laboratoire

Dans PowerShell, depuis le dossier du projet :

```powershell
.\venv\Scripts\Activate.ps1
python manage.py migrate
python manage.py seed_laboratory_demo
python manage.py runserver
```

Si le projet n'a pas d'environnement virtuel `venv`, ignorez la première commande et utilisez le Python configuré sur votre machine. `seed_laboratory_demo` prépare les comptes de démonstration, l’association médecin-patient et deux demandes (une pour tester l’annulation et une pour suivre le parcours). La commande peut être relancée sans créer de doublons. Elle ne crée plus les anciennes analyses de démonstration `DEMO-GLY` et `DEMO-NFS`; la migration du module supprime ces entrées lorsqu’elles ne sont pas utilisées, ou les désactive si elles sont liées à un historique clinique à préserver. Elle supprime l’ancien compte `bio_pasteur` s’il n’a aucune trace liée; si des données sont associées, elle le désactive. Si vous avez déjà terminé ou annulé la demande de démonstration, créez une nouvelle prescription dans l’interface pour recommencer le parcours sans effacer l’historique.

Ouvrez [http://127.0.0.1:8000/login/](http://127.0.0.1:8000/login/), puis testez les rôles séparément. Le module détaillé se trouve à [http://127.0.0.1:8000/laboratoire/](http://127.0.0.1:8000/laboratoire/).

### SmartResult IA (optionnel)

Le médecin compare les résultats publiés avec leur historique ; l’IA génère ensuite un seul résumé descriptif de cette comparaison, que le médecin relit et approuve. Les graphiques d’évolution ont été retirés de cette page. Les anciens brouillons produits par règles sont masqués et ne peuvent pas être approuvés comme des résumés IA ; un bouton **Générer le résumé IA maintenant** les remplace après une génération réussie. Les résultats dont l’unité ou les références sont incohérentes restent inclus dans le résumé comme non comparables ; leurs données ne sont pas présentées comme une comparaison valide et elles ne bloquent pas les autres résultats. Sans clé API, la comparaison reste accessible, mais aucun résumé local n’est créé. **Postman et Django n’utilisent pas les mêmes variables d’environnement** : le fait que la requête Postman fonctionne ne configure pas le serveur. Pour activer Gemini, copiez `.env.example` vers `.env` à la racine du projet, remplacez le placeholder de `GOOGLE_API_KEY` par une clé privée, puis définissez `GEMINI_MODEL=gemini-3.8-flash` et `GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite`. Si le modèle principal répond HTTP 503 (indisponibilité temporaire), Django essaie une fois le modèle de repli ; les autres erreurs ne déclenchent pas de repli. `config/settings.py` charge ces valeurs avec `python-dotenv` ; les variables Windows déjà définies restent prioritaires. `.env` est ignoré par Git. Ne partagez jamais la clé. Redémarrez Django après modification du fichier.

Le code appelle l’endpoint Interactions `https://generativelanguage.googleapis.com/v1beta/interactions` avec l’en-tête `x-goog-api-key` et les champs `model`, `input`, `system_instruction` et `store: false`. Le modèle Gemini par défaut est `gemini-3.8-flash`. Si les clés Gemini et Anthropic sont toutes deux définies, Gemini est prioritaire ; Anthropic reste utilisé si seule sa clé est définie. Le résumé reste un brouillon soumis à la relecture et à l’approbation du médecin. Le système exige une formulation descriptive sans diagnostic ni recommandation et rejette certaines formulations détectées ; cette vérification automatique ne remplace pas la relecture médicale.

Le résumé généré utilise les valeurs publiées, références et comparaisons calculées avec les résultats antérieurs. Seules ces données descriptives pseudonymisées sont transmises au fournisseur ; aucune identité du patient n’est envoyée. Le service écrit dans la console Django le fournisseur, le modèle, la durée, le statut HTTP ou le code d’échec, ainsi que la longueur du texte de sortie. Il ne journalise ni clé, ni identité, ni résultats, ni contenu de réponse. Le compte rendu garde la source **Généré par IA**. Si la clé manque, si le fournisseur échoue ou si sa réponse est rejetée, un message d’erreur s’affiche et aucun brouillon de remplacement par règles n’est enregistré.

La page du compte rendu compare aussi les résultats validés aux résultats antérieurs du même patient et de la même analyse prescrits par le même médecin. Une comparaison n’est faite que si les unités sont identiques après normalisation de la casse et des espaces ; aucune conversion d’unité n’est supposée. La variation est calculée en pourcentage par rapport à la valeur précédente ; **stable** signifie une variation absolue inférieure ou égale à 5 %, sinon la tendance est affichée comme **en hausse** ou **en baisse**. Ce seuil est descriptif, pas clinique. Une valeur antérieure nulle, une unité incompatible, une valeur numérique invalide ou des références incohérentes rendent la tendance insuffisante.

Le médecin ne rédige pas le résumé dans l’application : il consulte la comparaison structurée et approuve le brouillon IA. Un résumé déjà approuvé ne peut pas être remplacé depuis l’interface.

Pour tester le même contrat dans Postman, créez une requête `POST` vers `https://generativelanguage.googleapis.com/v1beta/interactions`, ajoutez les en-têtes `Content-Type: application/json` et `x-goog-api-key: {{GEMINI_API_KEY}}`, puis sélectionnez **Body > raw > JSON** :

```json
{
  "model": "gemini-3.8-flash",
  "input": "[{\"analyse\":\"CRP\",\"valeur\":\"4\",\"unite\":\"mg/L\",\"reference\":\"0 à 5 mg/L\",\"statut\":\"normal\",\"valeur_precedente\":\"2\",\"unite_precedente\":\"mg/L\",\"evolution\":\"en hausse · +100.00%\"},{\"analyse\":\"Glycémie\",\"valeur\":\"0.95\",\"unite\":\"g/L\",\"reference\":\"0.70 à 1.10 g/L\",\"statut\":\"normal\",\"valeur_precedente\":\"0.90\",\"unite_precedente\":\"g/L\",\"evolution\":\"en hausse · +5.56%\"}]",
  "system_instruction": "Rédige en français un résumé clair et concis avec une courte introduction et une liste à puces, une puce par analyse. Recopie exactement les valeurs, unités, références et évolutions fournies. Ne calcule, ne convertis et n’invente rien. Reste descriptif, sans diagnostic, explication des causes, conseil, recommandation ni suggestion de traitement. Termine par : « Résumé généré par IA, à vérifier et approuver par le médecin. »",
  "store": false
}
```

Dans Postman, définissez `GEMINI_API_KEY` dans un environnement local privé, pas dans une collection partagée. Consultez la réponse dans l’onglet **Pretty > JSON** ; les étapes `thought`, les signatures et les statistiques de jetons font partie de la réponse technique, tandis que le résumé lisible se trouve dans `steps` sous un élément `model_output` puis `content[].text`. La réponse doit contenir `"status": "completed"`. Ce statut confirme que l’API a répondu, pas que les données sont médicalement validées. Pour vérifier le parcours Django, utilisez ensuite un compte médecin, comparez les résultats publiés à leur historique, générez le résumé IA, puis vérifiez qu’il apparaît comme brouillon **Généré par IA** avant approbation.

### Comptes de test

| Acteur | Identifiant | Mot de passe | Ce qu’il peut vérifier dans le module |
|---|---|---|---|
| Médecin | `dr_moreau` | `docteur123` | Créer, modifier et annuler ses propres prescriptions encore en attente |
| Laborantin | `labo_pasteur` | `labo123` | Consulter les demandes de son équipe, gérer les prélèvements, saisir/corriger et valider les résultats |
| Administrateur | `admin` | `admin123` | Gérer le catalogue, les bilans et les paramètres du laboratoire ; pas de validation médicale |
| Patient | `patient_martin` | `patient123` | Consulter les résultats validés du module et les résultats publiés de son dossier médical |

Le compte `labo_pasteur` est un opérateur. Pour lui donner aussi les responsabilités biologiques, connectez-vous à Django Admin, ouvrez **Authentification et autorisation > Groupes**, puis ajoutez-le au groupe **Biologiste responsable**. Seuls les membres de ce groupe peuvent valider ou rejeter un résultat, valider une correction et télécharger le compte rendu PDF signé pour les demandes de leur équipe. La migration crée le groupe automatiquement, mais n’y affecte aucun compte.

### Contrôles de saisie des formulaires laboratoire

Les limites et règles métier sont contrôlées côté serveur ; les attributs HTML aident aussi à corriger les saisies avant l’envoi. Les formulaires vérifient notamment les champs obligatoires et leurs longueurs, les valeurs numériques et unités des résultats, les références et seuils cohérents, la précision d’un type d’échantillon « Autre », les motifs de rejet proposés, ainsi que l’ordre et le format des dates des filtres. Pour vérifier ces contrôles, essayez une date de fin antérieure à la date de début, un résultat numérique mal formé, une unité différente de celle du catalogue ou un motif d’annulation trop court ; le formulaire doit afficher une erreur et ne pas enregistrer la saisie invalide.

### Parcours pas à pas — test manuel

Après le seed, les demandes affichées dans **Analyses** portent le commentaire `DEMO_LABO` et sont attribuées à `labo_pasteur` (la commande réattribue ces seules demandes de démonstration si nécessaire). Le catalogue est administré uniquement par le rôle **Administrateur**. Créez d’abord les types d’analyse nécessaires avant de prescrire une nouvelle demande.

1. **Administrateur — configurer le laboratoire**
   Connectez-vous avec `admin` / `admin123`, puis ouvrez le **Catalogue des analyses** ou les **Bilans prédéfinis**. Les formulaires d’ajout et de modification s’ouvrent dans une fenêtre modale et affichent les erreurs de validation sans perdre les champs saisis. Les références et seuils sont numériques, et le tarif ne peut pas être négatif. Une analyse comprend son code unique, son nom, sa catégorie d’échantillon, son unité, ses références, ses seuils critiques, son tarif et son état actif. Un bilan comprend un nom unique, une description et au moins une analyse active. Les actions sont inscrites dans l’historique.

2. **Administrateur — modifier et désactiver**
   Dans le catalogue ou la liste des bilans, ouvrez **Modifier** pour mettre à jour les champs. **Archiver** demande une confirmation, puis retire l’élément de la liste active sans supprimer les références ni l’historique. Utilisez **Voir les analyses archivées** ou **Voir les bilans archivés** pour les réactiver. Les analyses désactivées ne peuvent pas être ajoutées à de nouveaux bilans. Les comptes Laboratoire n’ont pas accès à ces écrans de configuration.

3. **Médecin — Create/Read/Update de la demande**
   Déconnectez-vous, puis connectez-vous avec `dr_moreau` / `docteur123`. Dans **Analyses**, créez une prescription avec l’analyse active créée par l’administrateur ou sélectionnez le bilan prédéfini. Modifiez la demande encore en attente (par exemple le commentaire), enregistrez, puis vérifiez les changements.

4. **Médecin — annulation logique**
   Revenez à la liste et ouvrez `DEMO_LABO: à annuler par le médecin`. Cliquez sur **Annuler la demande** et confirmez. Le statut devient **Annulée** ; la demande n’est pas effacée.

5. **Laboratoire — Create/Read/Update d’un prélèvement**
   Reconnectez-vous au compte `labo_pasteur`. Ouvrez la demande créée à l’étape médecin, puis ajoutez un prélèvement :
   - code : `DEMO-TUBE-01` (choisissez un code inédit si vous recommencez le scénario)
   - type : `SANG`
   - statut : `RECU` (le résultat ne peut être saisi qu’après réception)
   - date de réception : date et heure actuelles

   Enregistrez, vérifiez les informations puis utilisez **Modifier** pour changer une remarque. Un prélèvement marqué **Rejeté** doit obligatoirement avoir un motif.

6. **Laboratoire — Create/Read/Update d’un résultat**
   Sous l’analyse active de votre prescription, choisissez **Saisir pour DEMO-TUBE-01** et saisissez une valeur, avec une observation facultative. Les nombres mal formés et les unités différentes de celles du catalogue sont signalés avant publication ; les résultats qualitatifs restent acceptés. Le résultat apparaît en attente de validation ; les résultats dépassant une référence sont signalés et les seuils critiques configurés sont clairement marqués. Essayez **Corriger** pour vérifier l’Update et l’enregistrement de l’ancienne/nouvelle valeur dans l’historique.

7. **Biologiste responsable — validation, rejet et nouvelle validation**
   Ajoutez d’abord `labo_pasteur` au groupe **Biologiste responsable** depuis Django Admin. Dans **File de validation**, validez ou rejetez les résultats avec un commentaire obligatoire. Une correction d’un résultat validé repasse à **Correction à valider** et exige une nouvelle validation. L’opérateur peut corriger et renvoyer un résultat rejeté, mais ne peut pas valider, rejeter ni modifier un résultat déjà validé.

8. **Tous les acteurs — vérifier les autorisations**
   - Depuis le médecin, la demande du deuxième médecin n’est pas visible ; un patient non associé ne doit pas être proposé dans le formulaire de prescription.
   - Depuis le patient, ouvrez `/laboratoire/` : l’accès est refusé/redirigé.
   - Depuis l’administrateur, ouvrez **Catalogue**, **Bilans prédéfinis** et **Paramètres du laboratoire**. L’administration peut les gérer, mais ne peut pas approuver un résultat. Les demandes urgentes non terminées sont marquées en retard après le délai configuré.
   - Seuls les membres du groupe **Biologiste responsable** peuvent valider ou rejeter des résultats. L’opérateur gère les prélèvements et la saisie/correction des résultats non validés.
   - Depuis le patient, ouvrez **Mes résultats**. Seuls les résultats validés du compte connecté sont affichés ; les résultats en attente restent privés.

9. **Laboratoire — vérifier l’audit et la conservation**
   Ouvrez **Historique**. Les créations/modifications de types, bilans, paramètres, demandes, prélèvements et résultats ainsi que les changements de statut sont présentés avec leur date, leur auteur et les valeurs avant/après. Il n’y a pas de suppression physique des données médicales depuis ce parcours.

> Les comptes et mots de passe ci-dessus sont uniquement des identifiants de démonstration locale, à ne pas utiliser en production.

### Tests automatisés

Avec l’environnement virtuel activé, exécutez :

```powershell
python manage.py test laboratoire
```

Cette suite vérifie les prescriptions et les rôles, l’affichage de la file laboratoire, la confidentialité patient, le rejet d’un prélèvement sans motif, les valeurs hors référence, les permissions de validation, la correction avec revalidation et la traçabilité. Pour vérifier l’ensemble du projet, lancez `python manage.py test`.

Pour mesurer uniquement la couverture du code applicatif du module Laboratoire, installez l’outil de développement et lancez :

```powershell
py -3.14 -m pip install -r requirements-dev.txt
py -3.14 -m coverage run --rcfile=.coveragerc manage.py test laboratoire.tests
py -3.14 -m coverage report --rcfile=.coveragerc
py -3.14 -m coverage html --rcfile=.coveragerc
```

Le rapport texte affiche le pourcentage global et le détail des lignes manquantes. Le rapport HTML détaillé est créé dans `htmlcov/laboratoire/index.html`. La configuration active la couverture des branches, mesure seulement le paquet `laboratoire` et exclut ses tests et migrations ; les fichiers de rapport restent ignorés par Git. Le pourcentage doit être relevé après exécution, car il dépend des chemins réellement couverts par les tests.

Mesure effectuée le 25/10/2026 : **64,3 % de couverture globale** (49 tests exécutés). Ce taux inclut la couverture des branches et peut évoluer avec les tests ou le code.

> La configuration de base actuelle utilise SQLite (`db.sqlite3`). MySQL n’est pas activé par ces commandes.

---

## 🌟 Fonctionnalités Réalisées

### 1. 🛡️ Espace Administrateur
- **Hub d'Administration Web dédié (`/dashboard/admin-hub/`) :**
  - Vue d'ensemble statistique (KPIs : Total, Docteurs, Laboratoires, Patients, En attente de validation).
  - Tableau de bord de gestion avec recherche instantanée et filtres par rôle.
  - Actions rapides en un clic : **Certification / Validation d'agrément**, **Activation / Suspension** d'un compte.
- **Console Django Admin personnalisée (`/admin/`) :**
  - Badges de rôles colorés et filtres avancés.
  - Formulaires spécifiques intégrés (*Inlines*) pour chaque profil.
  - Menus dédiés par rôle : `🩺 Docteurs`, `🔬 Laboratoires`, `👤 Patients`.

### 2. 🩺 Espace Docteur (`/dashboard/docteur/`)
- Tableau de bord des consultations du jour.
- Indicateurs clés (patients suivis, consultations, analyses prescrites).
- Suivi en temps réel des analyses transmises aux laboratoires.
- Gestion du profil : spécialité, numéro d'ordre, cabinet, horaires.

### 2 bis. 📊 Supervision et rapports laboratoire (administrateur uniquement)
- Supervision de toutes les demandes avec filtres par période, statut, priorité, patient, médecin et laboratoire.
- Signalement des demandes ouvertes non attribuées, des urgences au-delà du délai configuré, des prélèvements rejetés et des résultats en attente de validation.
- Réaffectation/déblocage d’une demande ouverte et annulation administrative avec motif conservé dans la demande et l’historique.
- Rapports filtrables par période : demandes par jour, délais moyens de traitement, analyses les plus prescrites, taux de rejet, statuts et chiffre d’affaires théorique calculé sur les tarifs.
- Exports CSV et Excel (.xlsx). Le chiffre d’affaires du rapport est estimé d’après les tarifs actuels du catalogue, et ne remplace pas les montants facturés/encaissés.

### 3. 🔬 Espace Laboratoire (`/dashboard/laboratoire/`)
- File d'attente des prélèvements biologiques et degré d'urgence (*Normale*, *Haute*, *Urgente*).
- Indicateurs de suivi des examens (biochimie, hématologie, sérologie, PCR).
- Gestion du profil : numéro d'agrément, biologiste responsable, examens pris en charge.
- Module détaillé accessible depuis **Analyses** (`/laboratoire/`) : demandes prescrites, catalogue, prélèvements, résultats et historique des actions.
- Configuration réservée au rôle Administrateur : catalogue (références, seuils critiques, tarifs), bilans prédéfinis, identité/logo du laboratoire, éléments de compte rendu PDF, motifs de rejet et délai d’alerte des demandes urgentes.
- Les demandes urgentes encore ouvertes dépassant le délai configuré sont signalées dans la file de demandes.
- Les médecins créent les demandes, le laboratoire saisit les résultats et seuls les comptes Laboratoire peuvent les valider. L’administrateur technique peut consulter mais ne valide pas les résultats.
- Une correction d’un résultat déjà validé est conservée dans l’historique et soumise à une nouvelle validation. Les demandes sont annulées logiquement et les types d’analyses peuvent être désactivés plutôt que supprimés.
### Espace médecin — analyses de laboratoire
- Depuis le tableau de bord médecin, ouvrez **Mes demandes laboratoire** pour prescrire ou suivre vos demandes, modifier/annuler une demande encore en attente et consulter ses résultats.
- Chaque patient associé dispose d’un historique des résultats validés ; choisissez une analyse pour comparer ses valeurs numériques dans le temps. Les valeurs hors référence sont mises en évidence.
- **Alertes laboratoire** regroupe les nouveaux résultats validés, les valeurs potentiellement critiques et les échantillons rejetés concernant vos prescriptions.
- Le compte rendu PDF d’une demande est téléchargeable par son médecin prescripteur et par le biologiste responsable de l’équipe dès qu’au moins un résultat est validé. Il reprend les paramètres d’en-tête et de signature PDF configurés par l’administration ainsi que l’identité de chaque biologiste validateur.

### Espace patient — dossier laboratoire
- Depuis le tableau de bord patient, **Mon dossier laboratoire** affiche l’avancement de ses demandes et ses résultats validés.
- L’historique peut être filtré par période et type d’analyse ; une sélection d’analyse permet de visualiser l’évolution des résultats numériques. Les validations reçues dans les sept derniers jours sont signalées sur le dossier laboratoire.
- Le patient peut télécharger le compte rendu PDF des seules demandes lui appartenant et ayant au moins un résultat validé. Les résultats en attente et les données d’autres patients ne sont jamais inclus.

### 4. 👤 Espace Patient (`/dashboard/patient/`)
- Espace santé personnel avec groupe sanguin, antécédents et contacts d'urgence.
- Consultation et téléchargement des comptes-rendus d'analyses et ordonnances.
- Rappel du prochain rendez-vous médical.

### 5. 🔐 Système d'Authentification & Inscription
- Inscription dynamique avec onglets de sélection du rôle (*Docteur*, *Laboratoire*, *Patient*).
- Formulaires adaptatifs affichant les champs requis selon le rôle sélectionné.
- Redirection intelligente après connexion vers le tableau de bord approprié.
