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
| **🔬 Laborantin** | `labo_pasteur` | `labo123` | Gérer les demandes, prélèvements et résultats, puis les vérifier et les valider |
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

Si le projet n'a pas d'environnement virtuel `venv`, ignorez la première commande et utilisez le Python configuré sur votre machine. `seed_laboratory_demo` prépare les comptes de démonstration, l’association médecin-patient, deux analyses et deux demandes (une pour tester l’annulation et une pour suivre tout le parcours). La commande peut être relancée sans créer de doublons. Elle supprime l’ancien compte `bio_pasteur` s’il n’a aucune trace liée; si des résultats, demandes, actions d’historique ou autres données sont associés, elle le désactive afin de préserver la traçabilité. Les autres données médicales ne sont pas supprimées. Si vous avez déjà terminé ou annulé la demande de démonstration, créez une nouvelle prescription dans l’interface pour recommencer le parcours sans effacer l’historique.

Ouvrez [http://127.0.0.1:8000/login/](http://127.0.0.1:8000/login/), puis testez les rôles séparément. Le module détaillé se trouve à [http://127.0.0.1:8000/laboratoire/](http://127.0.0.1:8000/laboratoire/).

### Comptes de test

| Acteur | Identifiant | Mot de passe | Ce qu’il peut vérifier dans le module |
|---|---|---|---|
| Médecin | `dr_moreau` | `docteur123` | Créer, modifier et annuler ses propres prescriptions encore en attente |
| Laborantin | `labo_pasteur` | `labo123` | Consulter les demandes de son équipe, gérer les prélèvements, saisir/corriger et valider les résultats |
| Administrateur | `admin` | `admin123` | Consulter les demandes, gérer le catalogue, lire l’historique ; pas de validation médicale |
| Patient | `patient_martin` | `patient123` | Consulter les résultats validés du module et les résultats publiés de son dossier médical |

### Parcours pas à pas — test manuel

Après le seed, les demandes affichées dans **Analyses** portent le commentaire `DEMO_LABO` et sont attribuées à `labo_pasteur` (la commande réattribue ces seules demandes de démonstration si nécessaire). Vous pouvez aussi créer une demande via l’interface pour vérifier le Create.

1. **Laboratoire — lire le catalogue et les demandes**
   Connectez-vous avec `labo_pasteur` / `labo123`, ouvrez **Analyses**, puis consultez la demande `DEMO_LABO: parcours complet`. Testez les filtres de statut, de date et de nom patient. Ouvrez **Catalogue** : les codes `DEMO-GLY` et `DEMO-NFS` sont déjà créés.

2. **Laboratoire — Create/Read/Update du catalogue**
   Dans le catalogue, ajoutez par exemple `TEST-CHO`, `Cholestérol total`, unité `g/L`, références `1` à `2`. Vérifiez qu’il apparaît, ouvrez **Modifier**, changez une valeur, puis désactivez-le en décochant **Actif**. Il reste consultable et n’est plus proposé pour une nouvelle prescription.

3. **Médecin — Create/Read/Update de la demande**
   Déconnectez-vous, puis connectez-vous avec `dr_moreau` / `docteur123`. Dans **Analyses**, ouvrez `DEMO_LABO: parcours complet`. Vérifiez patient, laboratoire, priorité et analyses. Modifiez la demande encore en attente (par exemple le commentaire), enregistrez, puis vérifiez les changements.

4. **Médecin — annulation logique**
   Revenez à la liste et ouvrez `DEMO_LABO: à annuler par le médecin`. Cliquez sur **Annuler la demande** et confirmez. Le statut devient **Annulée** ; la demande n’est pas effacée.

5. **Laboratoire — Create/Read/Update d’un prélèvement**
   Reconnectez-vous au compte `labo_pasteur`. Ouvrez la demande `parcours complet`, puis ajoutez un prélèvement :
   - code : `DEMO-TUBE-01` (choisissez un code inédit si vous recommencez le scénario)
   - type : `SANG`
   - statut : `RECU` (le résultat ne peut être saisi qu’après réception)
   - date de réception : date et heure actuelles

   Enregistrez, vérifiez les informations puis utilisez **Modifier** pour changer une remarque. Un prélèvement marqué **Rejeté** doit obligatoirement avoir un motif.

6. **Laboratoire — Create/Read/Update d’un résultat**
   Sous l’analyse **Glycémie (démo)**, choisissez **Saisir pour DEMO-TUBE-01** et saisissez `1.3`, unité `g/L`, avec une observation facultative. Le résultat apparaît en attente de validation et la valeur est signalée hors de la plage de référence. Essayez **Corriger** pour vérifier l’Update et l’enregistrement de l’ancienne/nouvelle valeur dans l’historique.

7. **Laborantin — validation et nouvelle validation après correction**
   Restez connecté avec `labo_pasteur` / `labo123`. Validez le résultat saisi et vérifiez son statut, le nom du validateur et l’heure. Une correction d’un résultat validé repasse à **Correction à valider** et exige une nouvelle validation. Seuls les comptes du rôle Laboratoire peuvent valider ; l’administrateur technique ne le peut pas.

8. **Tous les acteurs — vérifier les autorisations**
   - Depuis le médecin, la demande du deuxième médecin n’est pas visible ; un patient non associé ne doit pas être proposé dans le formulaire de prescription.
   - Depuis le patient, ouvrez `/laboratoire/` : l’accès est refusé/redirigé.
   - Depuis l’administrateur, ouvrez **Analyses** et **Catalogue**. L’administration peut consulter et gérer le catalogue, mais ne peut pas approuver un résultat.
   - Un compte Laboratoire peut aussi valider les résultats de l’ancien tableau de bord laboratoire.
   - Depuis le patient, ouvrez **Mes résultats**. Seuls les résultats validés du compte connecté sont affichés ; les résultats en attente restent privés.

9. **Laboratoire — vérifier l’audit et la conservation**
   Ouvrez **Historique**. Les créations/modifications de types, demandes, prélèvements et résultats ainsi que les changements de statut sont présentés avec leur date, leur auteur et les valeurs avant/après. Il n’y a pas de suppression physique des données médicales depuis ce parcours.

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

### 3. 🔬 Espace Laboratoire (`/dashboard/laboratoire/`)
- File d'attente des prélèvements biologiques et degré d'urgence (*Normale*, *Haute*, *Urgente*).
- Indicateurs de suivi des examens (biochimie, hématologie, sérologie, PCR).
- Gestion du profil : numéro d'agrément, biologiste responsable, examens pris en charge.
- Module détaillé accessible depuis **Analyses** (`/laboratoire/`) : demandes prescrites, catalogue, prélèvements, résultats et historique des actions.
- Les médecins créent les demandes, le laboratoire saisit les résultats et seuls les comptes Laboratoire peuvent les valider. L’administrateur technique peut consulter mais ne valide pas les résultats.
- Une correction d’un résultat déjà validé est conservée dans l’historique et soumise à une nouvelle validation. Les demandes sont annulées logiquement et les types d’analyses peuvent être désactivés plutôt que supprimés.

### 4. 👤 Espace Patient (`/dashboard/patient/`)
- Espace santé personnel avec groupe sanguin, antécédents et contacts d'urgence.
- Consultation et téléchargement des comptes-rendus d'analyses et ordonnances.
- Rappel du prochain rendez-vous médical.

### 5. 🔐 Système d'Authentification & Inscription
- Inscription dynamique avec onglets de sélection du rôle (*Docteur*, *Laboratoire*, *Patient*).
- Formulaires adaptatifs affichant les champs requis selon le rôle sélectionné.
- Redirection intelligente après connexion vers le tableau de bord approprié.
