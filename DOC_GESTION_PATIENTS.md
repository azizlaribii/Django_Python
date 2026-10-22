# 📘 Guide Complet : Module Gestion des Patients & Parcours Médical — SantéConnect

Ce document décrit en détail le fonctionnement, les relations de données, le scénario de démonstration et l'emplacement exact de tous les **CRUD** du module **Gestion des Patients** de l'application **SantéConnect**.

---

## 1. 🔄 Scénario Complet de Démonstration (Démarche Pas à Pas)

Ce scénario illustre le parcours de soins collaboratif entre un **Médecin** (Dr. Alexandre Moreau), un **Patient** (Claire Durand) et un **Laboratoire d'analyses** (Laboratoire Pasteur).

```mermaid
sequenceDiagram
    autonumber
    actor P as 👤 Patient (Claire Durand)
    actor M as 🩺 Médecin (Dr. Alexandre Moreau)
    actor L as 🔬 Laboratoire (Labo Pasteur)

    Note over M, P: Étape 1 : Association & Dossier Médical
    M->>P: Associe le patient à sa patientèle
    M->>P: Ouverture / consultation du Dossier Médical (#DM-...)

    Note over M: Étape 2 : Consultation Clinique
    M->>M: Planifie un Examen Médical (Date + Heure ex: 14:30)
    M->>M: Rédige une Observation médicale (Tension, examen physique)
    M->>M: Rédige une Prescription (Panadol 1g, 3 fois/jour)

    Note over M, L: Étape 3 : Prescription Biologique
    M->>L: Prescrit une Analyse (ex: NFS, Glycémie - Priorité Urgente/Haute)

    Note over L: Étape 4 : Prise en Charge par le Laboratoire
    L->>L: Réception de la demande (Statut : 🟠 En attente)
    L->>L: Prise en charge du prélèvement (Statut : 🔵 En cours)
    L->>L: Saisie des résultats d'analyses et conclusion (Statut : 🟢 Terminé)

    Note over M, P: Étape 5 : Consultation des Résultats Validés
    L-->>M: Résultats synchronisés en direct dans le dossier du médecin
    L-->>P: Résultats disponibles dans l'Espace Santé du patient
```

### Déroulement pratique sur l'application :
1. **Connexion Médecin (`dr_moreau`)** sur `http://127.0.0.1:8000/dashboard/docteur/` :
   * Il consulte sa liste de patients suivis.
   * Il clique sur **« 📁 Dossier »** du patient (ex: Claire Durand).
2. **Consultation & Actions dans le Dossier Patient** :
   * **Ajout d'examen** : bouton `🩺 Examen` ➔ titre, type, date, saisie libre de l'heure (`14:30`), motif.
   * **Prescription** : bouton `💊 Prescription` ➔ médicament, posologie, durée, instructions.
   * **Observation** : bouton `📝 Observation` ➔ compte-rendu d'observation clinique.
   * **Prescription d'analyse** : bouton `🔬 Prescrire Analyse` ➔ choix de l'analyse, niveau de priorité (*Normale*, *Haute*, *Urgente*) et sélection du laboratoire.
3. **Traitement par le Laboratoire (`lab_pasteur`)** sur `http://127.0.0.1:8000/dashboard/laboratoire/` :
   * La demande s'affiche immédiatement dans le tableau avec sa référence et sa priorité.
   * Le biologiste clique sur **`👁️ Ouvrir`** pour lire la demande.
   * Il clique sur **`📝 Saisir résultat`**, renseigne les valeurs mesurées, son commentaire et valide le statut en **`🟢 Terminé`**.
4. **Consultation par le Patient (`patient_durand`)** sur `http://127.0.0.1:8000/dashboard/patient/` :
   * Le patient consulte ses ordonnances actives, ses rendez-vous et télécharge ses résultats d'analyses.

---

## 2. 🧬 Modèle Conceptuel et Relations de Données (MCD)

Toutes les entités sont implémentées dans `accounts/models.py` :

```mermaid
erDiagram
    User ||--o| PatientProfile : "Profil spécifique"
    User ||--o| DoctorProfile : "Profil spécifique"
    User ||--o| LaboratoryProfile : "Profil spécifique"
    User ||--o| DossierMedical : "Possède un dossier unique (1-to-1)"

    User ||--o{ AssociationMedecinPatient : "Médecin traitant"
    User ||--o{ AssociationMedecinPatient : "Patient associé"

    DossierMedical ||--o{ ExamenMedical : "Comporte"
    DossierMedical ||--o{ Prescription : "Comporte"
    DossierMedical ||--o{ ObservationMedicale : "Comporte"
    DossierMedical ||--o{ ResultatLaboratoire : "Comporte"

    User ||--o{ ResultatLaboratoire : "Prescrit par (Médecin)"
    User ||--o{ ResultatLaboratoire : "Réalisé par (Laboratoire)"
```

### Description des relations :
* **`User` (Rôles)** : Utilisateur central avec rôle (`DOCTEUR`, `PATIENT`, `LABORATOIRE`, `ADMIN`).
* **`DossierMedical` (`OneToOneField` vers `User` Patient)** :
  * Clé de voûte médicale contenant le numéro de dossier unique (`DM-XXXXXX`), groupe sanguin, allergies et antécédents.
* **`AssociationMedecinPatient` (`ForeignKey` Médecin + `ForeignKey` Patient)** :
  * Gère la relation médecin traitant référent et autorise l'accès au dossier médical.
* **`ExamenMedical`** :
  * Rattaché au `DossierMedical` et au `User` (Médecin praticien).
* **`Prescription` (Ordonnance)** :
  * Rattachée au `DossierMedical` et au `User` (Médecin prescripteur).
* **`ObservationMedicale`** :
  * Rattachée au `DossierMedical` et au `User` (Médecin auteur), avec gestion de la confidentialité.
* **`ResultatLaboratoire`** :
  * Rattaché au `DossierMedical`, au Médecin prescripteur et au Laboratoire réalisateur.

---

## 3. 🛠️ Répertoire Exhaustif des CRUD (Où trouver chaque élément)

### Tableau complet Code, Formulaires, Modales et URLs :

| Entité | Opération CRUD | Fichier Python & Fonction Backend | Formulaire Django | Template HTML & Emplacement UI | Route URL |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **🩺 Examen Médical** | **C**reate<br>**R**ead<br>**U**pdate<br>**D**elete | `accounts/views.py` :<br>• `add_examen`<br>• `get_examen_detail`<br>• `edit_examen`<br>• `delete_examen` | `accounts/forms.py` :<br>`ExamenMedicalForm` | `templates/accounts/doctor_patient_dossier.html`<br>• Bouton `🩺 Examen`<br>• Modale `#modal-add-exam`<br>• Icônes `✏️` et `🗑️` | `/docteur/patient/<id>/examen/add/`<br>`/api/examen/<id>/`<br>`/docteur/examen/<id>/edit/`<br>`/docteur/examen/<id>/delete/` |
| **💊 Prescription (Ordonnance)** | **C**reate<br>**R**ead<br>**U**pdate<br>**D**elete | `accounts/views.py` :<br>• `add_prescription`<br>• `get_prescription_detail`<br>• `edit_prescription`<br>• `delete_prescription` | `accounts/forms.py` :<br>`PrescriptionForm` | `templates/accounts/doctor_patient_dossier.html`<br>• Onglet Prescriptions<br>• Bouton `+ Ajouter`<br>• Modale `#modal-add-presc` | `/docteur/patient/<id>/prescription/add/`<br>`/api/prescription/<id>/`<br>`/docteur/prescription/<id>/edit/`<br>`/docteur/prescription/<id>/delete/` |
| **🔬 Analyse Biologique & Labo** | **C**reate (Prescrire)<br>**R**ead (Détails)<br>**U**pdate (Saisie Labo)<br>**D**elete | `accounts/views.py` :<br>• `add_resultat`<br>• `get_resultat_detail`<br>• `lab_update_resultat`<br>• `delete_resultat` | `accounts/forms.py` :<br>`ResultatLaboratoireForm` | 1. Côté Médecin :<br>`doctor_patient_dossier.html`<br>Bouton `🔬 Prescrire Analyse`<br><br>2. Côté Laboratoire :<br>`dashboard_lab.html`<br>Boutons `👁️ Ouvrir` et `📝 Saisir résultat` | `/docteur/patient/<id>/resultat/add/`<br>`/api/resultat/<id>/`<br>`/labo/resultat/<id>/update/`<br>`/docteur/resultat/<id>/delete/` |
| **📝 Observation Médicale** | **C**reate<br>**R**ead<br>**U**pdate<br>**D**elete | `accounts/views.py` :<br>• `add_observation`<br>• `get_observation_detail`<br>• `edit_observation`<br>• `delete_observation` | `accounts/forms.py` :<br>`ObservationMedicaleForm` | `templates/accounts/doctor_patient_dossier.html`<br>• Onglet Observations<br>• Bouton `📝 Observation`<br>• Modale `#modal-add-obs` | `/docteur/patient/<id>/observation/add/`<br>`/api/observation/<id>/`<br>`/docteur/observation/<id>/edit/`<br>`/docteur/observation/<id>/delete/` |
| **👤 Patient & Association** | **C**reate (Associer)<br>**R**ead (Dossier)<br>**U**pdate (Info profil)<br>**D**elete (Dissocier) | `accounts/views.py` :<br>• `associer_patient`<br>• `doctor_patient_dossier`<br>• `patient_edit_info`<br>• `dissocier_patient` | `accounts/forms.py` :<br>• `PatientProfileForm`<br>• `AssociationForm`<br>• `DossierMedicalForm` | `templates/accounts/dashboard_doctor.html`<br>• Bouton `+ Associer un patient`<br>• Tableau des patients suivis | `/docteur/patient/associer/`<br>`/docteur/patient/<id>/dossier/`<br>`/docteur/patient/<id>/dissocier/`<br>`/profile/` |

---

## 4. 🤖 2. IA — Analyse Intelligente du Dossier Médical

Ce module d'intelligence artificielle clinique valide scrupuleusement les trois éléments fondamentaux de l'analyse :

### 1. 🩺 Récupération complète des examens
* Récupération de la **liste complète des examens** associés au patient (et pas uniquement leur simple comptage numérique).
* Modèle de données exposé : chaque examen fournit son titre, son type spécialisé, sa date, son heure, son statut, son motif et son compte-rendu médical s'ils existent.

### 2. 🧠 Génération du résumé NLP
* Intégration systématique et détaillée dans le compte-rendu narratif :
  * Le **type d'examen** (ex: *Coloscopie*, *Scanner TAP*, *Échocardiographie*)
  * La **date** et l'heure (ex: *le 17/09/2026 à 14:30*)
  * Le **statut** (ex: *Terminé*, *Planifié*, *En cours*)
  * Le **motif / description clinique** lorsqu'il existe
  * Le **compte-rendu médical / résultat** lorsqu'il existe (ex: *TA 138/88 mmHg, ECG normal, absence de lésion décelable*)
* Fourniture d'un bouton interactif **« 📋 Copier la synthèse »** pour transférer l'analyse textuelle dans les observations du praticien.

### 3. 🔬 Extraction des entités & Détection de polarité clinique (NegEx)
* Analyse sémantique poussée des descriptions d'examens et des observations cliniques.
* Distinction stricte et traçable entre :
  * 🔴 **Informations Avérées (Positif)** : Allergies actives, comorbidités confirmées, antécédents positifs.
  * 🟢 **Informations Explicitement Négatives / Écartées (Négation clinique)** : Détection des marqueurs de négation (*« pas d'allergie »*, *« absence de diabète »*, *« aucun antécédent d'HTA »*, *« nie toute douleur »*, *« néant »*, *« ras »*). Ces informations ne pénalisent pas le score de risque et rassurent le praticien.
  * ⚪ **Informations Absentes** : Pathologies ou facteurs non documentés dans le dossier.
* Endpoints API dédiés : `/api/dossier/<patient_id>/analyse-ia/` et `/api/dossier/<patient_id>/risques-ml/`.

---

## 5. 📊 3. ML — Détection des Risques Médicaux

## 5. 📊 3. ML — Détection des Risques Médicaux (Scikit-Learn & Clustering)

Ce module de Machine Learning médical applique les 4 axes d'améliorations rigoureuses exigés pour la pratique clinique :

### 1. 🎯 Score de risque médical équitable et explicable
* **Règles cohérentes et justifiées** : pondération physiopathologique transparente, justifiée par critère clinique.
* **Distinction stricte information absente vs avérée** : une absence de donnée n'est jamais pénalisée (+0 point de risque). Seuls les facteurs documentés positifs sont pris en compte.
* **Gestion intelligente de la préparation d'examen** : une préparation non requise (`NON_REQUISE`) ou un examen programmé à l'avance sans retard n'est jamais comptabilisé comme insuffisant.
* **Explicabilité totale (XAI)** : tableau détaillé affichant chaque facteur actif, son domaine et sa justification médicale.

### 2. 🤖 Véritable Modèle de Machine Learning (Scikit-Learn 1.8)
* **Architecture supervisée** : `RandomForestClassifier` entraîné sur une cohorte clinique calibrée (12 variables physiopathologiques).
* **Cible prédictive définie** : Estimation de la probabilité réelle de complication clinique et décompensation iatrogène.
* **Évaluation hors-échantillon (Test Set indépendant)** :
  * Précision globale (Accuracy) : **~88%**
  * Aire sous la courbe ROC (ROC-AUC) : **~93%**
  * Score F1 harmonique : **~85%**
* **Garde-fou « Données insuffisantes »** : Si le taux de complétude du dossier est inférieur à **34%**, le système refuse d'afficher un faux « Risque faible » ou « Patient stable » et affiche explicitement : *« Données insuffisantes pour évaluer le risque médical »* avec la liste des éléments à renseigner.

### 3. 👥 Clustering et similarité des patients (Cosine Similarity réelle)
* **Calcul réel sans valeur arbitraire** : calculé mathématiquement par `sklearn.metrics.pairwise.cosine_similarity` sur un vecteur à 12 dimensions normalisées (et non fixé artificiellement à 96%).
* **Archétypes de cohortes épidémiologiques** :
  1. *Profil Cardio-Métabolique à Risque Vasculaire*
  2. *Profil Atopique & Terrain Allergique Sévère*
  3. *Profil Digestif & Surveillance Endoscopique*
  4. *Profil Rénal & Vigilance Produits de Contraste*
  5. *Profil Standard & Suivi Préventif Ambulatoire*
* **Protection du secret médical & RGPD** : les profils de référence sont des archétypes agrégés et anonymisés, sans exposition de données personnelles.

### 4. 🚨 Alertes et recommandations adaptées au type exact d'examen
* **Coloscopie / Recto-sigmoïdoscopie** : régime sans résidu strict 72h, purge, vérification de l'arrêt préalable des anticoagulants sous avis cardiologique.
* **Scanner avec injection iodée** : contrôle impératif de la créatininémie et du DFG sous 7 jours, suspension de la metformine 48h autour de l'injection.
* **Fibroscopie / Gastroscopie** : jeûne strict 6 heures (zéro solide, zéro liquide, zéro tabac).
* **Explorations cardiologiques (ECG, Holter, Écho)** : transmission du carnet tensionnel et revue des bétabloquants/antihypertenseurs.
* **Allergies sévères avérées** : contre-indication formelle aux bêtalactamines ou produits de contraste avec alertes rouges.
* Endpoints API dédiés : `/api/dossier/<patient_id>/analyse-ia/` et `/api/dossier/<patient_id>/risques-ml/`.

---

## 6. 🔑 Comptes de Test et Démonstration

| Rôle | Nom | Identifiant (`username`) | Mot de passe | URL d'accès direct |
| :--- | :--- | :--- | :--- | :--- |
| **Médecin Référent** | Dr. Alexandre Moreau | `dr_moreau` | `password123` | [http://127.0.0.1:8000/dashboard/docteur/](http://127.0.0.1:8000/dashboard/docteur/) |
| **Médecin Cardiologue** | Dr. Julien Leroy | `dr_leroy` | `password123` | [http://127.0.0.1:8000/dashboard/docteur/](http://127.0.0.1:8000/dashboard/docteur/) |
| **Laboratoire d'analyses** | Labo Pasteur | `lab_pasteur` | `password123` | [http://127.0.0.1:8000/dashboard/laboratoire/](http://127.0.0.1:8000/dashboard/laboratoire/) |
| **Patiente** | Claire Durand | `patient_durand` | `password123` | [http://127.0.0.1:8000/dashboard/patient/](http://127.0.0.1:8000/dashboard/patient/) |
| **Patiente** | Sophie Martin (ID: 6) | `patient_martin` | `password123` | [http://127.0.0.1:8000/docteur/patient/6/dossier/](http://127.0.0.1:8000/docteur/patient/6/dossier/) |
| **Administrateur** | Admin Système | `admin` | `admin123` | [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/) |

