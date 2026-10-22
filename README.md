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

### Comptes de test

| Acteur | Identifiant | Mot de passe | Ce qu’il peut vérifier dans le module |
|---|---|---|---|
| Médecin | `dr_moreau` | `docteur123` | Créer, modifier et annuler ses propres prescriptions encore en attente |
| Laborantin | `labo_pasteur` | `labo123` | Consulter les demandes de son équipe, gérer les prélèvements, saisir/corriger et valider les résultats |
| Administrateur | `admin` | `admin123` | Gérer le catalogue, les bilans et les paramètres du laboratoire ; pas de validation médicale |
| Patient | `patient_martin` | `patient123` | Consulter les résultats validés du module et les résultats publiés de son dossier médical |

Le compte `labo_pasteur` est un opérateur. Pour lui donner aussi les responsabilités biologiques, connectez-vous à Django Admin, ouvrez **Authentification et autorisation > Groupes**, puis ajoutez-le au groupe **Biologiste responsable**. Seuls les membres de ce groupe peuvent valider ou rejeter un résultat, valider une correction et télécharger le compte rendu PDF signé pour les demandes de leur équipe. La migration crée le groupe automatiquement, mais n’y affecte aucun compte.

### Parcours pas à pas — test manuel

Après le seed, les demandes affichées dans **Analyses** portent le commentaire `DEMO_LABO` et sont attribuées à `labo_pasteur` (la commande réattribue ces seules demandes de démonstration si nécessaire). Le catalogue est administré uniquement par le rôle **Administrateur**. Créez d’abord les types d’analyse nécessaires avant de prescrire une nouvelle demande.

1. **Administrateur — configurer le laboratoire**
   Connectez-vous avec `admin` / `admin123`, puis utilisez les raccourcis du tableau de bord pour ouvrir le **Catalogue des analyses**, les **Bilans prédéfinis** et les **Paramètres du laboratoire**. Ajoutez une analyse (par exemple `TEST-GLY`) avec unité, références, seuils critiques et tarif. Créez un bilan (par exemple lipidique) et sélectionnez les analyses qui le composent. Renseignez les coordonnées, l’en-tête/signature PDF, les motifs de rejet et le délai d’alerte urgente.

2. **Administrateur — modifier et désactiver**
   Dans le catalogue ou la liste des bilans, ouvrez **Modifier**, changez des champs, puis désactivez l’élément en décochant **Actif**. Il reste consultable, mais n’est plus proposé pour une nouvelle prescription ou un nouveau bilan. Les comptes Laboratoire n’ont pas accès à ces écrans de configuration.

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
   Sous l’analyse active de votre prescription, choisissez **Saisir pour DEMO-TUBE-01** et saisissez une valeur, avec une observation facultative. Le résultat apparaît en attente de validation; les résultats dépassant une référence sont signalés et les seuils critiques configurés sont clairement marqués. Essayez **Corriger** pour vérifier l’Update et l’enregistrement de l’ancienne/nouvelle valeur dans l’historique.

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
