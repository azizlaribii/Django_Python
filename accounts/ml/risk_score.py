"""
Module Risk Score — MediConnect ML
Responsabilités :
1. Extraction du vecteur clinique à 12 variables réelles à partir du dossier patient.
   - AUCUNE valeur par défaut silencieuse : l'âge n'est jamais fixé arbitrairement à 40 ans si absent.
   - Distinction rigoureuse entre information confirmée négative (écartée) et information non renseignée.
2. Évaluation de la complétude des variables réellement indispensables au calcul :
   - Âge / date de naissance
   - Antécédents médicaux documentés (ou mention d'absence d'antécédents)
   - Terrain allergique
   - Observations cliniques / constantes
3. Suspension immédiate du score et de la prédiction si les données requises sont insuffisantes.
4. Calcul d'un Score de Risque Indicatif (0 à 100) par barème de règles heuristiques explicables :
   - Les pondérations sont explicitement présentées comme des règles indicatives de démonstration,
     et non comme une probabilité médicale scientifiquement validée.
5. Gestion intelligente de la préparation : un statut 'A_FAIRE' (À préparer) n'est jamais pénalisé.
"""

import numpy as np
from .similarity import classifier_examen_reel
from .random_forest import valider_vecteur_patient


def extraire_vecteur_clinique(patient, dossier, ia_data):
    """
    Construit le vecteur des 12 caractéristiques cliniques normalisées
    à partir des données réelles du patient :
    - Si l'âge est absent, il vaut 0.0 (et n'est JAMAIS arbitrairement inventé à 40 ans).
    - Les négations cliniques confirmées et les données non mentionnées valent 0.
    - Seules les pathologies et facteurs confirmés positifs valent 1.
    """
    # 0. Âge normalisé (aucun remplacement par défaut si absent)
    age = ia_data.get('age')
    if age is not None and age > 0:
        age_norm = min(1.0, max(0.0, age / 100.0))
    else:
        # Donnée absente : pas d'imputation silencieuse
        age_norm = 0.0

    # 1 à 6. Pathologies confirmées positives uniquement
    maladies_ids = {m['id'] for m in ia_data.get('maladies_chroniques_positives', [])}
    hta_flag = 1.0 if 'HTA' in maladies_ids else 0.0
    diabete_flag = 1.0 if ('DIABETE_1' in maladies_ids or 'DIABETE_2' in maladies_ids) else 0.0
    dyslip_flag = 1.0 if 'DYSLIPIDEMIE' in maladies_ids else 0.0
    ic_flag = 1.0 if 'INSUFFISANCE_CARDIAQUE' in maladies_ids else 0.0
    ir_flag = 1.0 if 'INSUFFISANCE_RENALE' in maladies_ids else 0.0
    asthme_flag = 1.0 if 'ASTHME_BPCO' in maladies_ids else 0.0

    # 7. Allergies sévères confirmées positives
    allergies_ids = {a['id'] for a in ia_data.get('allergies_positives', [])}
    allergie_severe_flag = 1.0 if ('ALLERGIE_PENICILLINE' in allergies_ids or 'ALLERGIE_CONTRASTE' in allergies_ids) else 0.0

    # 8. Nombre de traitements actifs normalisé (nb / 8)
    nb_traitements = len(ia_data.get('traitements_actifs', []))
    nb_meds_norm = min(8, nb_traitements) / 8.0

    # 9. Examen invasif réel (après réconciliation du titre et du type d'examen)
    examens = ia_data.get('examens_complets', [])
    examen_invasif_flag = 0.0
    prep_echec_flag = 0.0

    for ex in examens:
        titre = ex.get('titre', '')
        type_code = ex.get('type_code', '')
        type_reel = classifier_examen_reel(titre, type_code)

        if type_reel in ['COLOSCOPIE', 'FOGD', 'CORONAROGRAPHIE']:
            examen_invasif_flag = 1.0

        # Statut de préparation : seuls les échecs confirmés comptent
        # Un examen 'A_FAIRE' ou 'EN_COURS' n'est JAMAIS un échec
        statut_prep = str(ex.get('statut_preparation') or '').upper()
        if statut_prep in ['INSUFFISANTE', 'ECHEC', 'NON_VALIDE']:
            prep_echec_flag = 1.0

    # 11. Analyses biologiques urgentes confirmées
    analyses_urgentes_count = dossier.resultats_labo.filter(priorite='URGENTE').count()
    analyse_urgente_flag = 1.0 if analyses_urgentes_count > 0 else 0.0

    vecteur = np.array([
        age_norm,
        hta_flag,
        diabete_flag,
        dyslip_flag,
        ic_flag,
        ir_flag,
        asthme_flag,
        allergie_severe_flag,
        nb_meds_norm,
        examen_invasif_flag,
        prep_echec_flag,
        analyse_urgente_flag
    ], dtype=np.float64)

    return valider_vecteur_patient(vecteur)


def verifier_completude_dossier(patient, dossier, ia_data=None):
    """
    Contrôle la complétude des variables RÉELLEMENT NÉCESSAIRES au modèle ML et au score :
    1. Âge ou date de naissance (indispensable à l'inférence démographique).
    2. Antécédents médicaux (au moins une pathologie documentée ou mention explicite d'absence d'antécédent).
    3. Terrain allergique (allergies documentées ou mention explicite d'absence d'allergie).
    4. Observations cliniques ou constantes (au moins une consultation, note ou constante).
    5. Prescriptions ou examens (traitement ou acte planifié).

    Si une variable indispensable manque (ex : âge absent), les données sont jugées insuffisantes.
    """
    pp = getattr(patient, 'patient_profile', None)
    donnees_manquantes = []
    criteres_renseignes = 0
    total_criteres = 5

    # 1. Âge / date de naissance
    age = (ia_data.get('age') if ia_data else None) or (getattr(pp, 'age', None) if pp else None)
    date_naiss = getattr(pp, 'date_naissance', None) if pp else None
    if (age is not None and age > 0) or date_naiss:
        criteres_renseignes += 1
    else:
        donnees_manquantes.append('âge / date de naissance (variable démographique requise)')

    # 2. Antécédents médicaux
    has_antecedents = False
    if pp and getattr(pp, 'antecedents', None) and pp.antecedents.strip():
        has_antecedents = True
    if dossier.antecedents_familiaux and dossier.antecedents_familiaux.strip():
        has_antecedents = True
    if ia_data and (ia_data.get('maladies_chroniques_positives') or ia_data.get('maladies_chroniques_negatives')):
        has_antecedents = True

    if has_antecedents:
        criteres_renseignes += 1
    else:
        donnees_manquantes.append('antécédents médicaux (aucune pathologie confirmée ni écartée)')

    # 3. Terrain allergique
    has_allergies = False
    if dossier.allergies and dossier.allergies.strip():
        has_allergies = True
    if ia_data and (ia_data.get('allergies_positives') or ia_data.get('allergies_negatives')):
        has_allergies = True

    if has_allergies:
        criteres_renseignes += 1
    else:
        donnees_manquantes.append('terrain allergique (allergies non renseignées)')

    # 4. Observations cliniques ou constantes
    if dossier.observations.exists():
        criteres_renseignes += 1
    else:
        donnees_manquantes.append('observations cliniques ou constantes médicales')

    # 5. Prescriptions ou examens programmés
    if dossier.prescriptions.exists() or dossier.examens.exists() or dossier.resultats_labo.exists():
        criteres_renseignes += 1
    else:
        donnees_manquantes.append('prescriptions thérapeutiques ou examens')

    taux = int((criteres_renseignes / total_criteres) * 100)

    # Condition stricte de données insuffisantes :
    # Si l'âge manque OU si moins de 3 critères sur 5 sont renseignés (< 60%)
    age_absent = ('âge / date de naissance (variable démographique requise)' in donnees_manquantes)
    donnees_insuffisantes = (age_absent or criteres_renseignes < 3)

    return {
        'taux_completude': taux,
        'criteres_renseignes': criteres_renseignes,
        'total_criteres': total_criteres,
        'donnees_insuffisantes': donnees_insuffisantes,
        'donnees_manquantes': donnees_manquantes,
        'donnees_manquantes_texte': ", ".join(donnees_manquantes) if donnees_manquantes else "Toutes les variables requises sont renseignées.",
    }


def calculer_score_risque_clinique(patient, dossier, ia_data):
    """
    Calcule le Score de Risque Indicatif (0 à 100) par agrégation de règles heuristiques.
    Avertissement :
    Ce score repose sur des pondérations indicatives de démonstration clinique.
    Il ne constitue pas une probabilité médicale validée par des essais cliniques.
    """
    completude = verifier_completude_dossier(patient, dossier, ia_data)
    vecteur = extraire_vecteur_clinique(patient, dossier, ia_data)

    if completude['donnees_insuffisantes']:
        return {
            'donnees_insuffisantes': True,
            'taux_completude': completude['taux_completude'],
            'donnees_manquantes': completude['donnees_manquantes'],
            'donnees_manquantes_texte': completude['donnees_manquantes_texte'],
            'score_global': 0,
            'score_display': "Non calculé",
            'niveau_risque': 'DONNEES_INSUFFISANTES',
            'badge_classe': 'secondary',
            'couleur': '#64748b',
            'icone': '⚠️',
            'recommandation_prioritaire': "L’évaluation du score est suspendue car des informations indispensables (notamment démographiques ou cliniques) sont absentes.",
            'facteurs_explicatifs': [],
            'nature_score': "Score suspendu (données insuffisantes)",
            'sous_scores': {'cardiovasculaire': 0, 'metabolique': 0, 'iatrogene': 0, 'allergique_iatrogene': 0, 'actes': 0, 'examens_interventions': 0},
            'vecteur_clinique': vecteur,
            'alertes_specifiques': [],
        }

    # Calcul indicatif par barème de règles explicables
    score_brut = 0
    facteurs = []

    age_reel = ia_data.get('age') or int(vecteur[0] * 100)
    if age_reel >= 75:
        score_brut += 20
        facteurs.append({
            "facteur": "Âge très avancé (≥ 75 ans)",
            "domaine": "Gériatrie",
            "points": 20,
            "type_regle": "Pondération indicative",
            "justification": f"Patient âgé de {age_reel} ans : vulnérabilité physiologique accrue",
        })
    elif age_reel >= 60:
        score_brut += 15
        facteurs.append({
            "facteur": "Âge mûr (≥ 60 ans)",
            "domaine": "Démographie",
            "points": 15,
            "type_regle": "Pondération indicative",
            "justification": f"Patient âgé de {age_reel} ans : vigilance cardiovasculaire",
        })

    if vecteur[1] > 0:
        score_brut += 15
        facteurs.append({
            "facteur": "Hypertension Artérielle",
            "domaine": "Cardiovasculaire",
            "points": 15,
            "type_regle": "Pondération indicative",
            "justification": "HTA documentée active dans le dossier",
        })

    if vecteur[2] > 0:
        score_brut += 20
        facteurs.append({
            "facteur": "Diabète documenté",
            "domaine": "Métabolique",
            "points": 20,
            "type_regle": "Pondération indicative",
            "justification": "Facteur métabolique de risque vasculaire associé",
        })

    if vecteur[3] > 0:
        score_brut += 10
        facteurs.append({
            "facteur": "Dyslipidémie",
            "domaine": "Métabolique",
            "points": 10,
            "type_regle": "Pondération indicative",
            "justification": "Anomalie lipidique documentée",
        })

    if vecteur[4] > 0:
        score_brut += 25
        facteurs.append({
            "facteur": "Insuffisance Cardiaque",
            "domaine": "Cardiovasculaire",
            "points": 25,
            "type_regle": "Pondération indicative",
            "justification": "Défaillance de la fonction myocardique",
        })

    if vecteur[5] > 0:
        score_brut += 20
        facteurs.append({
            "facteur": "Insuffisance Rénale",
            "domaine": "Néphrologie",
            "points": 20,
            "type_regle": "Pondération indicative",
            "justification": "Vulnérabilité de filtration rénale",
        })

    if vecteur[6] > 0:
        score_brut += 10
        facteurs.append({
            "facteur": "Asthme / BPCO",
            "domaine": "Respiratoire",
            "points": 10,
            "type_regle": "Pondération indicative",
            "justification": "Terrain d'hyperréactivité bronchique",
        })

    if vecteur[7] > 0:
        score_brut += 15
        facteurs.append({
            "facteur": "Allergie Sévère Avérée",
            "domaine": "Allergologie",
            "points": 15,
            "type_regle": "Pondération indicative",
            "justification": "Antécédent critique (pénicilline ou produit iodé)",
        })

    nb_meds = len(ia_data.get('traitements_actifs', []))
    if nb_meds >= 4:
        score_brut += 15
        facteurs.append({
            "facteur": "Polymédication Majeure (≥ 4 molécules)",
            "domaine": "Pharmacologie",
            "points": 15,
            "type_regle": "Pondération indicative",
            "justification": f"{nb_meds} traitements simultanés : risque d'interactions",
        })
    elif nb_meds >= 2:
        score_brut += 8
        facteurs.append({
            "facteur": "Polymédication Modérée (2-3 molécules)",
            "domaine": "Pharmacologie",
            "points": 8,
            "type_regle": "Pondération indicative",
            "justification": f"{nb_meds} traitements en cours",
        })

    if vecteur[9] > 0:
        score_brut += 15
        facteurs.append({
            "facteur": "Geste Invasif Planifié",
            "domaine": "Explorations",
            "points": 15,
            "type_regle": "Pondération indicative",
            "justification": "Endoscopie ou acte sous sédation programmé",
        })

    if vecteur[10] > 0:
        score_brut += 20
        facteurs.append({
            "facteur": "Échec de Préparation Médicale",
            "domaine": "Préparation",
            "points": 20,
            "type_regle": "Pondération indicative",
            "justification": "Consignes préalables signalées comme non respectées",
        })

    if vecteur[11] > 0:
        score_brut += 15
        facteurs.append({
            "facteur": "Analyse Biologique Urgente",
            "domaine": "Biologie",
            "points": 15,
            "type_regle": "Pondération indicative",
            "justification": "Prescription biologique en mode d'urgence active",
        })

    score_final = min(100, score_brut)

    # Niveaux indicatifs de risque
    if score_final >= 60:
        niveau = 'ÉLEVÉ'
        badge = 'danger'
        couleur = '#dc2626'
        icone = '🔴'
        recom = "Surveillance clinique rapprochée : plusieurs facteurs de comorbidité cumulés."
    elif score_final >= 30:
        niveau = 'MODÉRÉ'
        badge = 'warning'
        couleur = '#d97706'
        icone = '🟡'
        recom = "Vigilance intermédiaire : suivi périodique et vérification des protocoles pré-examens."
    else:
        niveau = 'FAIBLE'
        badge = 'success'
        couleur = '#16a34a'
        icone = '🟢'
        recom = "Profil clinique stable d'après les données disponibles."

    # Sous-scores indicatifs
    val_iatrogene = min(100, int((vecteur[7] * 50 + (nb_meds >= 4) * 50)))
    val_actes = min(100, int((vecteur[9] * 50 + vecteur[10] * 50)))
    sous_scores = {
        'cardiovasculaire': min(100, int((vecteur[1] * 35 + vecteur[4] * 50 + (vecteur[0] > 0.6) * 15))),
        'metabolique': min(100, int((vecteur[2] * 60 + vecteur[3] * 40))),
        'iatrogene': val_iatrogene,
        'allergique_iatrogene': val_iatrogene,
        'actes': val_actes,
        'examens_interventions': val_actes,
    }

    # Alertes spécifiques aux examens réels
    alertes = _generer_alertes_examens(ia_data.get('examens_complets', []), vecteur)

    return {
        'donnees_insuffisantes': False,
        'taux_completude': completude['taux_completude'],
        'donnees_manquantes': completude['donnees_manquantes'],
        'donnees_manquantes_texte': completude['donnees_manquantes_texte'],
        'score_global': score_final,
        'score_display': f"{score_final} / 100",
        'nature_score': "Score de risque indicatif (barème de règles heuristiques explicables, non validé cliniquement)",
        'niveau_risque': niveau,
        'badge_classe': badge,
        'couleur': couleur,
        'icone': icone,
        'recommandation_prioritaire': recom,
        'facteurs_explicatifs': facteurs,
        'sous_scores': sous_scores,
        'vecteur_clinique': vecteur,
        'alertes_specifiques': alertes,
    }


def _generer_alertes_examens(examens_patient, vecteur):
    """
    Génère les alertes protocolaires médicales adaptées à l'examen réel :
    - FOGD : jeûne strict de 6h (pas de consigne colique).
    - Coloscopie : régime sans résidu et purge (uniquement pour les vraies coloscopies).
    - Un bilan sanguin n'est jamais confondu avec un acte endoscopique.
    """
    alertes = []
    for ex in examens_patient:
        titre = ex.get('titre', '')
        type_code = ex.get('type_code', '')
        type_reel = classifier_examen_reel(titre, type_code)
        statut_prep = str(ex.get('statut_preparation') or '').upper()

        if type_reel == 'FOGD':
            if statut_prep in ['INSUFFISANTE', 'ECHEC', 'NON_VALIDE']:
                detail = "⚠️ Consignes de jeûne non respectées signalées : risque d'inhalation bronchique."
                badge = 'danger'
            elif statut_prep in ['VALIDEE']:
                detail = "✓ Consignes de jeûne validées (patient à jeun)."
                badge = 'success'
            else:
                detail = "Consigne obligatoire : Jeûne strict de 6 heures minimum (ni boire, ni manger, ni fumer)."
                badge = 'info'

            alertes.append({
                'type': 'FOGD',
                'examen_titre': titre,
                'titre': f"Protocole Endoscopie Haute (FOGD) — {titre}",
                'recommandation': f"Jeûne strict 6h minimum. Retrait des prothèses dentaires. {detail}",
                'badge': badge,
                'message': detail,
            })

        elif type_reel == 'COLOSCOPIE':
            if statut_prep in ['INSUFFISANTE', 'ECHEC', 'NON_VALIDE']:
                detail = "⚠️ Préparation colique insuffisante signalée : risque d'échec de visualisation."
                badge = 'danger'
            elif statut_prep in ['VALIDEE']:
                detail = "✓ Préparation colique validée par le patient."
                badge = 'success'
            else:
                detail = "Consigne obligatoire : Régime sans résidu 72h avant et purge fractionnée selon prescription."
                badge = 'warning'

            alertes.append({
                'type': 'COLOSCOPIE',
                'examen_titre': titre,
                'titre': f"Protocole Coloscopie — {titre}",
                'recommandation': f"Régime sans résidu 72h avant l’acte. Vérifier l'arrêt préalable des anticoagulants. {detail}",
                'badge': badge,
                'message': detail,
            })

    # Alerte allergique critique
    if vecteur[7] > 0:
        alertes.append({
            'type': 'ALLERGIE_CRITIQUE',
            'examen_titre': 'Sécurité Prescription',
            'titre': "Contre-indication Formelle Pénicillines / Produits de contraste",
            'recommandation': "Allergie sévère documentée. Proscrire bêtalactamines et produits iodés sans avis allergologique.",
            'badge': 'danger',
            'message': "Éviction formelle des bêtalactamines / contraste.",
        })

    return alertes
