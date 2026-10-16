# 🏥 SantéConnect — Application Médicale Django

Application web Django complète pour la gestion des comptes et la collaboration entre **Docteurs**, **Laboratoires d'Analyses**, **Patients** et l'**Administrateur**.

---

## 🚀 Démarrage Rapide

1. **Activer l'environnement virtuel :**
   ```powershell
   .\venv\Scripts\activate
   ```

2. **Lancer le serveur Django :**
   ```powershell
   python manage.py runserver
   ```

3. **Accéder à l'application dans votre navigateur :**
   - 🌐 **Portail Web Principal :** [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
   - 🔐 **Page de Connexion :** [http://127.0.0.1:8000/login/](http://127.0.0.1:8000/login/)
   - 📝 **Inscription Multi-rôles :** [http://127.0.0.1:8000/register/](http://127.0.0.1:8000/register/)
   - ⚙️ **Console Django Admin :** [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

---

## 🔑 Identifiants des Comptes de Démonstration (Pré-configurés)

Sur la page de connexion, des **boutons en 1-clic** permettent de remplir automatiquement ces identifiants :

| Rôle | Nom d'utilisateur | Mot de passe | Rôle & Permissions |
| :--- | :--- | :--- | :--- |
| **👑 Administrateur** | `admin` | `admin123` | Superutilisateur & Accès Django Admin complet |
| **🩺 Docteur** | `dr_moreau` | `docteur123` | Médecin (Cardiologie & Médecine Générale) |
| **🔬 Laboratoire** | `labo_pasteur` | `labo123` | Biologiste (Laboratoire Pasteur) |
| **👤 Patient** | `patient_martin` | `patient123` | Dossier Patient (Groupe O+) |

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

### 4. 👤 Espace Patient (`/dashboard/patient/`)
- Espace santé personnel avec groupe sanguin, antécédents et contacts d'urgence.
- Consultation et téléchargement des comptes-rendus d'analyses et ordonnances.
- Rappel du prochain rendez-vous médical.

### 5. 🔐 Système d'Authentification & Inscription
- Inscription dynamique avec onglets de sélection du rôle (*Docteur*, *Laboratoire*, *Patient*).
- Formulaires adaptatifs affichant les champs requis selon le rôle sélectionné.
- Redirection intelligente après connexion vers le tableau de bord approprié.
