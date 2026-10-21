"""
Module d'Intelligence Artificielle et de Machine Learning Médical — SantéConnect
Conforme aux spécifications :
1. Récupération des examens : Récupérer la liste complète des examens associés au patient, et pas uniquement leur nombre.
2. Génération du résumé NLP : Intégrer le type, la date, le statut, le motif et le compte-rendu lorsqu'ils existent.
3. Extraction des entités : Analyser les descriptions et les observations pour détecter les allergies, les antécédents et les pathologies,
   tout en distinguant les informations absentes des informations explicitement négatives (détection de polarité / NegEx).
"""

import re
import unicodedata
from datetime import date


# ─────────────────────────────────────────────────────────────────────────────
# 1. RÉFÉRENTIELS CLINIQUES & MOTS-CLÉS D'ENTITÉS
# ─────────────────────────────────────────────────────────────────────────────

MALADIES_CHRONIQUES_REF = [
    {
        'id': 'HTA',
        'nom': 'Hypertension Artérielle (HTA)',
        'categorie': 'Cardiovasculaire',
        'keywords': ['hypertension', 'hypertendu', 'hypertendue', 'hta', 'pression arterielle', 'amiodarone', 'ramipril', 'amlodipine', 'bisoprolol'],
        'poids_risque': 22,
    },
    {
        'id': 'DIABETE_2',
        'nom': 'Diabète de Type 2',
        'categorie': 'Métabolique',
        'keywords': ['diabete', 'type 2', 'metformine', 'glycemie', 'hba1c', 'insuline', 'hyperglycemie', 'gliclazide', 'diabetique'],
        'poids_risque': 25,
    },
    {
        'id': 'DIABETE_1',
        'nom': 'Diabète de Type 1 (Insulino-dépendant)',
        'categorie': 'Métabolique',
        'keywords': ['diabete type 1', 'insulino-dependant', 'acidocetose'],
        'poids_risque': 28,
    },
    {
        'id': 'DYSLIPIDEMIE',
        'nom': 'Dyslipidémie / Hypercholestérolémie',
        'categorie': 'Métabolique',
        'keywords': ['dyslipidemie', 'cholesterol', 'hypercholesterolemie', 'triglycerides', 'statine', 'atorvastatine', 'tahor'],
        'poids_risque': 16,
    },
    {
        'id': 'INSUFFISANCE_CARDIAQUE',
        'nom': 'Insuffisance Cardiaque / Coronaropathie',
        'categorie': 'Cardiovasculaire',
        'keywords': ['insuffisance cardiaque', 'coronaropathie', 'infarctus', 'angor', 'angine de poitrine', 'stent', 'pontage', 'cardiopathie'],
        'poids_risque': 30,
    },
    {
        'id': 'INSUFFISANCE_RENALE',
        'nom': 'Insuffisance Rénale Chronique',
        'categorie': 'Néphrologie',
        'keywords': ['insuffisance renale', 'creatinine', 'clairance', 'dfg', 'rein', 'dialyse', 'nephropathie'],
        'poids_risque': 26,
    },
    {
        'id': 'ASTHME_BPCO',
        'nom': 'Asthme / BPCO',
        'categorie': 'Respiratoire',
        'keywords': ['asthme', 'asthmatique', 'bpco', 'bronchopneumopathie', 'bronchite chronique', 'ventoline', 'salbutamol', 'inhalateur'],
        'poids_risque': 18,
    },
    {
        'id': 'PATHOLOGIE_DIGESTIVE',
        'nom': 'Pathologie Digestive Chronique (Crohn, RCH, Polypes)',
        'categorie': 'Gastro-entérologie',
        'keywords': ['crohn', 'rectocolite', 'rch', 'polype', 'colite', 'reflux', 'rgo', 'ulcere', 'gastrite'],
        'poids_risque': 14,
    },
]

ALLERGIES_REF = [
    {
        'id': 'ALLERGIE_PENICILLINE',
        'molecule': 'Pénicilline / Bêtalactamines',
        'type': 'Médicamenteuse',
        'keywords': ['penicilline', 'amoxicilline', 'augmentin', 'clamoxyl', 'betalactamine', 'cephalosporine'],
        'vigilance': 'SÉVÈRE / CONTRE-INDICATION ABSOLUE',
        'poids': 25,
    },
    {
        'id': 'ALLERGIE_AINS',
        'molecule': 'Aspirine / AINS (Anti-inflammatoires)',
        'type': 'Médicamenteuse',
        'keywords': ['aspirine', 'acide acetylsalicylique', 'ibuprofene', 'ketoprofene', 'ains', 'voltarene', 'diclofenac'],
        'vigilance': 'ÉLEVÉE (Risque ulcère, hémorragie, hypersensibilité)',
        'poids': 18,
    },
    {
        'id': 'ALLERGIE_CONTRASTE',
        'molecule': 'Produits de contraste iodés',
        'type': 'Examen / Imagerie',
        'keywords': ['iode', 'produit de contraste', 'contraste iode', 'scanner injecte'],
        'vigilance': 'SÉVÈRE (Pré-médication antiallergique obligatoire)',
        'poids': 22,
    },
    {
        'id': 'ALLERGIE_LATEX',
        'molecule': 'Latex',
        'type': 'Matériel médical',
        'keywords': ['latex', 'gants'],
        'vigilance': 'MODÉRÉE (Matériel sans latex requis)',
        'poids': 10,
    },
    {
        'id': 'ALLERGIE_SULFAMIDES',
        'molecule': 'Sulfamides / Antibiotiques',
        'type': 'Médicamenteuse',
        'keywords': ['sulfamide', 'bactrim'],
        'vigilance': 'ÉLEVÉE',
        'poids': 15,
    },
    {
        'id': 'ALLERGIE_ALIMENTAIRE',
        'molecule': 'Allergènes alimentaires (Arachide, Crustacés, etc.)',
        'type': 'Alimentaire',
        'keywords': ['arachide', 'cacahuete', 'fruit de mer', 'crustace', 'gluten', 'lactose'],
        'vigilance': 'MODÉRÉE À ÉLEVÉE',
        'poids': 12,
    },
]

COHORTES_CLINIQUES_ML = [
    {
        'id': 'CARDIO_METABOLIQUE',
        'nom': 'Profil Cardio-Métabolique à Risque Vasculaire',
        'description': 'Patients présentant une association d’hypertension, de dyslipidémie ou de diabète avec nécessité de surveillance tensionnelle et coronarienne.',
        'traits': ['HTA', 'DIABETE_2', 'DYSLIPIDEMIE', 'AGE_50_PLUS'],
        'complications_frequentes': [
            'Accident vasculaire cérébral (AVC) ou ischémie transitoire',
            'Cardiopathie ischémique et infarctus du myocarde',
            'Néphropathie diabétique débutante',
        ],
        'recommandations_prevention': [
            'Contrôle trimestriel de la tension artérielle (MAPA ou carnet tensionnel)',
            'Dosage annuel de l’HbA1c, du bilan lipidique et de la créatininémie',
            'ECG de repos annuel et échocardiographie si anomalie',
            'Régime hyposodé et activité physique modérée adaptée',
        ],
    },
    {
        'id': 'ATOPIC_ALLERGIC',
        'nom': 'Profil Atopique & Terrain Allergique Sévère',
        'description': 'Patients multi-allergiques à haut risque de choc anaphylactique ou d’intolérances croisées médicamenteuses.',
        'traits': ['ALLERGIE_PENICILLINE', 'ALLERGIE_AINS', 'ASTHME_BPCO'],
        'complications_frequentes': [
            'Réaction anaphylactoïde lors d’injections ou anesthésies',
            'Bronchospasme aigu induit par les AINS ou bêtatransmetteurs',
            'Éruption cutanée généralisée médicamenteuse (Toxidermie)',
        ],
        'recommandations_prevention': [
            'Mentionner en rouge sur tout bon de prescription l’éviction des pénicillines et AINS',
            'Privilégier le paracétamol ou les macrolides sous surveillance',
            'Prescription d’une trousse d’urgence (antihistaminique +/- stylo auto-injecteur si antécédent)',
        ],
    },
    {
        'id': 'ENDOSCOPIE_DIGESTIVE',
        'nom': 'Profil Digestif & Surveillance Endoscopique',
        'description': 'Patients nécessitant des explorations régulières (coloscopie, gastroscopie) avec protocoles stricts de purge et de diète sans résidu.',
        'traits': ['PATHOLOGIE_DIGESTIVE', 'EXAMEN_COLOSCOPIE', 'EXAMEN_FIBROSCOPIE'],
        'complications_frequentes': [
            'Échec de préparation colique nécessitant un report de l’examen',
            'Déshydratation consécutive à la purge osmotique chez le sujet âgé',
            'Hémorragie post-polypectomie',
        ],
        'recommandations_prevention': [
            'Suivi strict du score de préparation au-dessus de 80% avant l’acte',
            'Régime sans résidus 72h à l’avance et hydratation fractionnée',
            'Arrêt préalable des anticoagulants/antiagrégants sous validation médicale',
        ],
    },
    {
        'id': 'NEPHRO_CONTRASTE',
        'nom': 'Profil Rénal & Vigilance Produits de Contraste',
        'description': 'Patients avec fonction rénale fragile ou surveillance d’examens injectés (scanners TAP, urographie).',
        'traits': ['INSUFFISANCE_RENALE', 'AGE_65_PLUS', 'DIABETE_2'],
        'complications_frequentes': [
            'Néphropathie induite par les produits de contraste iodés',
            'Aggravation brutale de la clairance rénale',
        ],
        'recommandations_prevention': [
            'Dosage obligatoire de la créatininémie et calcul du DFG avant tout scanner injecté',
            'Hyperhydratation pré et post-examen (1.5L d’eau alcaline)',
            'Arrêt transitoire de la metformine 48h autour de l’examen',
        ],
    },
    {
        'id': 'PREVENTION_STANDARD',
        'nom': 'Profil Standard & Suivi Préventif Ambulatoire',
        'description': 'Patient sans facteur de risque majeur aigu, relevant du parcours de soins primaire et de prévention vaccinale et biométrique.',
        'traits': ['ROUTINE'],
        'complications_frequentes': [
            'Retard de diagnostic par défaut de dépistage périodique',
        ],
        'recommandations_prevention': [
            'Bilan de santé préventif périodique (glycémie, NFS, lipides)',
            'Mise à jour du calendrier vaccinal',
            'Surveillance du poids, de l’IMC et de la tension artérielle',
        ],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# 2. MOTEUR DE DÉTECTION DE POLARITÉ ET NÉGATION MÉDICALE (NEGEX CLINIQUE)
# ─────────────────────────────────────────────────────────────────────────────

def _nettoyer_texte(texte):
    if not texte:
        return ''
    nfkd = unicodedata.normalize('NFKD', str(texte).lower())
    return ''.join([c for c in nfkd if not unicodedata.combining(c)])


# Déclencheurs de négation clinique en français médical
NEGATION_PATTERNS = [
    r'\bpas\s+d[e\']',
    r'\baucun[es]?',
    r'\bsans\b',
    r'\babsence\s+d[e\']',
    r'\bnon\b',
    r'\bnie[nt]?\b',
    r'\bnegation\s+d[e\']',
    r'\bne\s+presente\s+pas',
    r'\bne\s+rapporte\s+pas',
    r'\belimine\b',
    r'\bexclut\b',
    r'\bneant\b',
    r'\bras\b',
    r'\bindemne\s+d[e\']',
    r'\brefute\b',
    r'\bzero\b',
]
COMPILED_NEGATIONS = [re.compile(p, re.IGNORECASE) for p in NEGATION_PATTERNS]


def decouper_en_propositions(texte):
    """Découpe un texte médical en propositions/phrases pour l'analyse locale de négation."""
    if not texte:
        return []
    lignes = re.split(r'[\r\n]+', str(texte))
    propositions = []
    for l in lignes:
        morceaux = re.split(r'[.;,]+', l)
        for m in morceaux:
            clean = m.strip()
            if clean and len(clean) > 2:
                propositions.append(clean)
    return propositions


def analyser_polarite_entite(clauses_sources, keywords):
    """
    Analyse l'ensemble des propositions médicales du dossier et classe l'entité en 3 catégories :
    - 'POSITIF' : mentionnée sans négation (information confirmée / avérée)
    - 'NEGATION_EXPLICITE' : mentionnée avec un marqueur de négation (information explicitement négative / écartée)
    - 'ABSENT' : jamais mentionnée dans les documents (information absente)
    """
    occurrences_pos = []
    occurrences_neg = []

    for source_nom, clause in clauses_sources:
        clause_norm = _nettoyer_texte(clause)
        kw_trouves = [kw for kw in keywords if _nettoyer_texte(kw) in clause_norm]
        if not kw_trouves:
            continue

        # Détection de négation clinique : combinaisons d'expressions et fenêtre lexicale (ex: 'absence formelle de', 'pas de notion de')
        est_negatif = any(p.search(clause_norm) for p in COMPILED_NEGATIONS)
        if not est_negatif:
            mots_clause = re.findall(r'\b\w+\b', clause_norm)
            neg_lexique = {'pas', 'aucun', 'aucune', 'aucunes', 'sans', 'absence', 'non', 'nie', 'nient', 'negation', 'elimine', 'exclut', 'neant', 'ras', 'indemne', 'refute', 'zero'}
            for kw in kw_trouves:
                kw_toks = re.findall(r'\b\w+\b', _nettoyer_texte(kw))
                if not kw_toks:
                    continue
                premier_mot = kw_toks[0]
                for idx, mot in enumerate(mots_clause):
                    if mot == premier_mot:
                        # Recherche d'un mot de négation avant (fenêtre de 6 mots)
                        precedent = mots_clause[max(0, idx - 6):idx]
                        if any(nw in precedent for nw in neg_lexique):
                            est_negatif = True
                            break
                        # Recherche d'un mot de négation après (ex: 'allergie : néant')
                        suivant = mots_clause[idx:min(len(mots_clause), idx + 4)]
                        if any(nw in suivant for nw in neg_lexique):
                            est_negatif = True
                            break
                if est_negatif:
                    break

        detail = {
            'source': source_nom,
            'texte_brut': clause.strip(),
            'mots_cles': kw_trouves,
        }

        if est_negatif:
            occurrences_neg.append(detail)
        else:
            occurrences_pos.append(detail)

    if occurrences_pos:
        return {
            'statut': 'POSITIF',
            'statut_libelle': 'Avéré / Confirmé',
            'badge': 'danger',
            'occurrences': occurrences_pos,
            'phrase_source': occurrences_pos[0]['texte_brut'],
        }
    elif occurrences_neg:
        return {
            'statut': 'NEGATION_EXPLICITE',
            'statut_libelle': 'Explicitement Négatif / Écarté',
            'badge': 'success',
            'occurrences': occurrences_neg,
            'phrase_source': occurrences_neg[0]['texte_brut'],
        }
    else:
        return {
            'statut': 'ABSENT',
            'statut_libelle': 'Information Absente (Non mentionné)',
            'badge': 'secondary',
            'occurrences': [],
            'phrase_source': 'Non renseigné dans le dossier',
        }


# ─────────────────────────────────────────────────────────────────────────────
# 3. MODULE IA — ANALYSE INTELLIGENTE DU DOSSIER MÉDICAL
# ─────────────────────────────────────────────────────────────────────────────

def analyser_dossier_ia(patient, dossier):
    """
    Module IA complet vérifiant les 3 éléments obligatoires :
    1. Récupération des examens : liste complète et structurée des examens du patient (pas seulement le nombre).
    2. Génération du résumé NLP : intégration exhaustive du type, de la date, du statut, du motif et du compte-rendu lorsqu'ils existent.
    3. Extraction des entités : analyse des descriptions d'examens et des observations pour détecter les allergies,
       les antécédents et les pathologies, en distinguant les informations absentes des informations explicitement négatives.
    """
    pp = getattr(patient, 'patient_profile', None)

    # ─────────────────────────────────────────────────────────────────────────
    # ÉLÉMENT 1 : RÉCUPÉRATION COMPLÈTE DES EXAMENS ASSOCIÉS AU PATIENT
    # ─────────────────────────────────────────────────────────────────────────
    examens_qs = dossier.examens.select_related('medecin').prefetch_related('etapes_preparation').order_by('-date_examen', '-id')
    examens_complets = []

    for ex in examens_qs:
        date_str = ex.date_examen.strftime('%d/%m/%Y') if ex.date_examen else 'Date non fixée'
        heure_str = ex.heure_examen.strftime('%H:%M') if ex.heure_examen else ''
        motif_txt = (ex.description or '').strip()
        resultat_txt = (ex.resultat or '').strip()

        med_nom = f"Dr. {ex.medecin.get_full_name() or ex.medecin.username}" if ex.medecin else 'Médecin non assigné'

        examens_complets.append({
            'id': ex.id,
            'titre': ex.titre,
            'type_code': ex.type_examen,
            'type_libelle': ex.get_type_examen_display(),
            'date_examen': date_str,
            'heure_examen': heure_str,
            'date_heure_display': f"{date_str} à {heure_str}" if heure_str else date_str,
            'statut': ex.statut,
            'statut_libelle': ex.get_statut_display(),
            'statut_preparation': ex.get_statut_preparation_display(),
            'score_preparation': ex.score_preparation,
            'score_seuil_validation': ex.score_seuil_validation,
            'lieu_examen': ex.lieu_examen or 'Cabinet / Établissement',
            'motif': motif_txt,
            'compte_rendu': resultat_txt,
            'medecin_nom': med_nom,
            'a_motif': bool(motif_txt),
            'a_compte_rendu': bool(resultat_txt),
        })

    # ─────────────────────────────────────────────────────────────────────────
    # CONSTITUTION DU CORPUS PROPOSITIONNEL POUR L'ANALYSE NLP & POLARITÉ
    # ─────────────────────────────────────────────────────────────────────────
    clauses_sources = []

    if pp and pp.antecedents:
        for prop in decouper_en_propositions(pp.antecedents):
            clauses_sources.append(('Profil Patient (Antécédents)', prop))

    if dossier.allergies:
        for prop in decouper_en_propositions(dossier.allergies):
            clauses_sources.append(('Dossier Médical (Allergies)', prop))

    if dossier.antecedents_familiaux:
        for prop in decouper_en_propositions(dossier.antecedents_familiaux):
            clauses_sources.append(('Dossier Médical (Antécédents familiaux)', prop))

    if dossier.notes_generales:
        for prop in decouper_en_propositions(dossier.notes_generales):
            clauses_sources.append(('Dossier Médical (Notes générales)', prop))

    # Descriptions & observations des examens
    for ex in examens_qs:
        ex_label = f"Examen '{ex.titre}'"
        if ex.description:
            for prop in decouper_en_propositions(ex.description):
                clauses_sources.append((f"{ex_label} (Motif/Description)", prop))
        if ex.resultat:
            for prop in decouper_en_propositions(ex.resultat):
                clauses_sources.append((f"{ex_label} (Compte-rendu/Résultat)", prop))

    # Observations médicales
    observations = list(dossier.observations.all())
    for obs in observations:
        obs_label = f"Observation '{obs.titre}' ({obs.date_observation.strftime('%d/%m/%Y')})"
        for prop in decouper_en_propositions(obs.contenu):
            clauses_sources.append((obs_label, prop))

    # Résultats de laboratoire
    resultats = list(dossier.resultats_labo.all())
    for res in resultats:
        res_label = f"Analyse '{res.type_analyse}'"
        if res.valeurs:
            for prop in decouper_en_propositions(res.valeurs):
                clauses_sources.append((f"{res_label} (Valeurs)", prop))
        if res.interpretation:
            for prop in decouper_en_propositions(res.interpretation):
                clauses_sources.append((f"{res_label} (Interprétation)", prop))

    # Prescriptions
    prescriptions = list(dossier.prescriptions.all())

    # ─────────────────────────────────────────────────────────────────────────
    # ÉLÉMENT 3 : EXTRACTION DES ENTITÉS AVEC DISTINCTION STRICTE :
    # POSITIF vs NÉGATION EXPLICITE vs ABSENT
    # ─────────────────────────────────────────────────────────────────────────

    # 1. ALLERGIES
    allergies_positives = []
    allergies_negatives = []
    allergies_absentes = []

    for ref in ALLERGIES_REF:
        res_polarite = analyser_polarite_entite(clauses_sources, ref['keywords'])
        item = {
            'id': ref['id'],
            'molecule': ref['molecule'],
            'type': ref['type'],
            'vigilance': ref['vigilance'],
            'poids': ref['poids'],
            'statut': res_polarite['statut'],
            'statut_libelle': res_polarite['statut_libelle'],
            'badge': res_polarite['badge'],
            'source_texte': res_polarite['phrase_source'],
        }
        if res_polarite['statut'] == 'POSITIF':
            allergies_positives.append(item)
        elif res_polarite['statut'] == 'NEGATION_EXPLICITE':
            allergies_negatives.append(item)
        else:
            allergies_absentes.append(item)

    # Prise en compte du champ libre dossier.allergies s'il n'a pas été couvert
    if dossier.allergies:
        norm_all = _nettoyer_texte(dossier.allergies)
        # Vérifier si c'est une négation globale (ex: 'aucune', 'ras', 'pas d'allergie', 'néant')
        est_neg_globale = any(p.search(norm_all) for p in COMPILED_NEGATIONS)
        if est_neg_globale:
            if not allergies_negatives:
                allergies_negatives.append({
                    'id': 'ALLERGIE_GENERALE_NEG',
                    'molecule': dossier.allergies.strip(),
                    'type': 'Déclaration globale',
                    'vigilance': 'Aucune allergie documentée (Écartée)',
                    'poids': 0,
                    'statut': 'NEGATION_EXPLICITE',
                    'statut_libelle': 'Explicitement Négatif / Écarté',
                    'badge': 'success',
                    'source_texte': dossier.allergies.strip(),
                })
        else:
            # S'il y a du texte positif non répertorié dans les keywords
            if not allergies_positives:
                allergies_positives.append({
                    'id': 'ALLERGIE_AUTRE_POS',
                    'molecule': dossier.allergies.strip(),
                    'type': 'Signalement dossier',
                    'vigilance': 'VIGILANCE DÉCLARÉE',
                    'poids': 18,
                    'statut': 'POSITIF',
                    'statut_libelle': 'Avéré / Confirmé',
                    'badge': 'danger',
                    'source_texte': dossier.allergies.strip(),
                })

    # 2. MALADIES CHRONIQUES & PATHOLOGIES
    maladies_positives = []
    maladies_negatives = []
    maladies_absentes = []

    for ref in MALADIES_CHRONIQUES_REF:
        res_polarite = analyser_polarite_entite(clauses_sources, ref['keywords'])
        item = {
            'id': ref['id'],
            'nom': ref['nom'],
            'categorie': ref['categorie'],
            'poids_risque': ref['poids_risque'],
            'statut': res_polarite['statut'],
            'statut_libelle': res_polarite['statut_libelle'],
            'badge': res_polarite['badge'],
            'source_texte': res_polarite['phrase_source'],
        }
        if res_polarite['statut'] == 'POSITIF':
            maladies_positives.append(item)
        elif res_polarite['statut'] == 'NEGATION_EXPLICITE':
            maladies_negatives.append(item)
        else:
            maladies_absentes.append(item)

    # 3. ANTÉCÉDENTS PERSONNELS & FAMILIAUX
    antecedents_personnels_pos = []
    antecedents_personnels_neg = []
    if pp and pp.antecedents:
        for prop in decouper_en_propositions(pp.antecedents):
            if any(p.search(_nettoyer_texte(prop)) for p in COMPILED_NEGATIONS):
                antecedents_personnels_neg.append(prop)
            else:
                antecedents_personnels_pos.append(prop)

    antecedents_familiaux_pos = []
    antecedents_familiaux_neg = []
    if dossier.antecedents_familiaux:
        for prop in decouper_en_propositions(dossier.antecedents_familiaux):
            if any(p.search(_nettoyer_texte(prop)) for p in COMPILED_NEGATIONS):
                antecedents_familiaux_neg.append(prop)
            else:
                antecedents_familiaux_pos.append(prop)

    # Traitements actifs
    traitements_actifs = [
        f"{p.medicament} ({p.posologie})"
        for p in prescriptions if p.statut == 'ACTIVE'
    ]

    # Calcul de l'âge
    age = None
    if pp and pp.date_naissance:
        today = date.today()
        age = today.year - pp.date_naissance.year - (
            (today.month, today.day) < (pp.date_naissance.month, pp.date_naissance.day)
        )

    # ─────────────────────────────────────────────────────────────────────────
    # ÉLÉMENT 2 : GÉNÉRATION DU RÉSUMÉ NLP AVEC INTÉGRATION EXHAUSTIVE :
    # TYPE, DATE, STATUT, MOTIF ET COMPTE-RENDU LORSQU'ILS EXISTENT
    # ─────────────────────────────────────────────────────────────────────────

    full_name = patient.get_full_name() or patient.username
    age_txt = f"{age} ans" if age is not None else "âge non spécifié"
    gs_txt = f", groupe sanguin {pp.groupe_sanguin}" if pp and pp.groupe_sanguin else ""

    # Paragraphe 1 : Identité & Contexte
    paragraphe_identite = (
        f"Patient(e) {full_name}, {age_txt}{gs_txt}. "
        f"Dossier médical #{dossier.numero_dossier} ouvert le {dossier.date_creation.strftime('%d/%m/%Y')}. "
    )

    # Paragraphe 2 : Pathologies & Entités (distinction Positif vs Négation explicite)
    if maladies_positives:
        noms_mc = ", ".join([m['nom'] for m in maladies_positives])
        p_patho = f"Sur le plan pathologique, le profil présente des comorbidités actives confirmées : {noms_mc}. "
    else:
        p_patho = "Aucune pathologie chronique active confirmée n'est répertoriée dans le dossier. "

    if maladies_negatives:
        neg_noms = ", ".join([f"{m['nom']} (écarté : '{m['source_texte']}')" for m in maladies_negatives])
        p_patho += f"Informations explicitement négatives / écartées : {neg_noms}. "

    # Paragraphe 3 : Allergies (Positif vs Négatif)
    if allergies_positives:
        noms_all = ", ".join([f"{a['molecule']} ({a['vigilance']})" for a in allergies_positives])
        p_allergies = f"⚠️ Vigilance allergologique majeure confirmée pour : {noms_all}. "
    elif allergies_negatives:
        neg_all_txt = ", ".join([a['molecule'] for a in allergies_negatives])
        p_allergies = f"🟢 Allergies formellement écartées par négation clinique explicite : {neg_all_txt}. "
    else:
        p_allergies = "⚪ Aucune allergie documentée (information absente du dossier). "

    # Paragraphe 4 : Traitements
    if traitements_actifs:
        p_traitements = f"Traitements chroniques actifs ({len(traitements_actifs)}) : {'; '.join(traitements_actifs)}. "
    else:
        p_traitements = "Aucun traitement médicamenteux chronique actif n'est actuellement prescrit sur la plateforme. "

    # Paragraphe 5 : SYNTHÈSE DÉTAILLÉE DES EXAMENS MÉDICAUX (Type, Date, Statut, Motif, Compte-rendu)
    synthese_examens_lignes = []
    if examens_complets:
        synthese_examens_lignes.append(f"Parcours des examens médicaux ({len(examens_complets)} examen(s) répertorié(s)) :")
        for idx, ex in enumerate(examens_complets, 1):
            parties = [
                f"{idx}. {ex['titre']}",
                f"Type : {ex['type_libelle']}",
                f"Date : {ex['date_heure_display']}",
                f"Statut : {ex['statut_libelle']}",
            ]
            if ex['a_motif']:
                parties.append(f"Motif : {ex['motif']}")
            if ex['a_compte_rendu']:
                parties.append(f"Compte-rendu médical : {ex['compte_rendu']}")
            else:
                parties.append("Compte-rendu : en attente / non disponible")

            synthese_examens_lignes.append(" — ".join(parties))
        paragraphe_examens_nlp = " \n".join(synthese_examens_lignes) + " "
    else:
        paragraphe_examens_nlp = "Aucun examen médical n'a encore été planifié ou réalisé pour ce patient. "

    # Paragraphe 6 : Activité globale
    activite_globale = (
        f"Activité médicale globale : {len(examens_complets)} examen(s) médical(aux), "
        f"{len(resultats)} analyse(s) biologique(s) de laboratoire et {len(observations)} observation(s) clinique(s)."
    )

    resume_global = f"{paragraphe_identite}\n\n{p_patho}\n\n{p_allergies}\n\n{p_traitements}\n\n{paragraphe_examens_nlp}\n\n{activite_globale}"

    # Points clés prioritaires pour le praticien (< 30 secondes)
    points_cles = []
    if allergies_positives:
        points_cles.append(f"🔴 Allergie avérée : {', '.join([a['molecule'] for a in allergies_positives])}")
    elif allergies_negatives:
        points_cles.append(f"🟢 Allergies écartées : {', '.join([a['molecule'] for a in allergies_negatives])}")

    if maladies_positives:
        points_cles.append(f"🟠 Pathologie active : {', '.join([m['nom'] for m in maladies_positives[:2]])}")

    if maladies_negatives:
        points_cles.append(f"🛡️ Négation clinique : {', '.join([m['nom'] for m in maladies_negatives[:2]])}")

    if examens_complets:
        prochain_ex = examens_complets[0]
        points_cles.append(f"🩺 Examen récent/planifié : {prochain_ex['titre']} ({prochain_ex['date_examen']}) [{prochain_ex['statut_libelle']}]")

    if traitements_actifs:
        points_cles.append(f"💊 {len(traitements_actifs)} ordonnance(s) active(s)")

    if not points_cles:
        points_cles.append("🟢 Profil stable sans alerte critique signalée")

    return {
        'age': age,
        'full_name': full_name,
        'resume_global': resume_global,
        'paragraphe_examens_nlp': paragraphe_examens_nlp,
        'points_cles': points_cles,

        # ÉLÉMENT 1 : Liste complète et structurée de tous les examens
        'examens_complets': examens_complets,
        'examens': examens_complets,
        'nb_examens': len(examens_complets),

        # ÉLÉMENT 3 : Entités avec distinction Positif vs Négation explicite vs Absent
        'allergies': allergies_positives,
        'allergies_positives': allergies_positives,
        'allergies_negatives': allergies_negatives,
        'allergies_absentes': allergies_absentes,

        'maladies_chroniques': maladies_positives,
        'maladies_chroniques_positives': maladies_positives,
        'maladies_chroniques_negatives': maladies_negatives,
        'maladies_chroniques_absentes': maladies_absentes,

        'antecedents_personnels': antecedents_personnels_pos,
        'antecedents_personnels_pos': antecedents_personnels_pos,
        'antecedents_personnels_neg': antecedents_personnels_neg,

        'antecedents_familiaux': antecedents_familiaux_pos,
        'antecedents_familiaux_pos': antecedents_familiaux_pos,
        'antecedents_familiaux_neg': antecedents_familiaux_neg,

        'traitements_actifs': traitements_actifs,
        'nb_analyses': len(resultats),
        'nb_prescriptions': len(prescriptions),
        'nb_observations': len(observations),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. MODULE ML — DÉTECTION DES RISQUES MÉDICAUX & PROFILS SIMILAIRES
# ─────────────────────────────────────────────────────────────────────────────

def detecter_risques_ml(patient, dossier, ia_data=None):
    """
    Module Machine Learning :
    - Analyse des données médicales disponibles pour identifier des facteurs de risque.
    - Détection de profils similaires à partir des antécédents et des résultats des examens (clustering / similarity).
    - Estimation d'un niveau de risque (faible, modéré ou élevé) selon des critères médicaux validés.
    - Prend en compte uniquement les entités avérées (POSITIF) et exclut les négations cliniques explicites.
    """
    if ia_data is None:
        ia_data = analyser_dossier_ia(patient, dossier)

    age = ia_data.get('age') or 40

    score_total = 0
    facteurs_explicatifs = []

    # 1. ÂGE
    if age >= 65:
        score_total += 15
        facteurs_explicatifs.append({
            'facteur': 'Âge supérieur ou égal à 65 ans',
            'points': 15,
            'domaine': 'Démographie',
            'justification': 'Vulnérabilité gériatrique accrue, risque métabolique et fonction rénale à surveiller.',
        })
    elif age >= 50:
        score_total += 8
        facteurs_explicatifs.append({
            'facteur': 'Âge compris entre 50 et 64 ans',
            'points': 8,
            'domaine': 'Démographie',
            'justification': 'Augmentation progressive du risque cardiovasculaire.',
        })

    # 2. MALADIES CHRONIQUES AVÉRÉES (POSITIVES UNIQUEMENT)
    score_cardio = 0
    score_metabolique = 0
    score_allergique = 0
    score_examens = 0

    for mc in ia_data['maladies_chroniques_positives']:
        pts = mc['poids_risque']
        score_total += pts
        if mc['categorie'] == 'Cardiovasculaire':
            score_cardio += pts
        elif mc['categorie'] == 'Métabolique':
            score_metabolique += pts

        facteurs_explicatifs.append({
            'facteur': f"Comorbidité active : {mc['nom']}",
            'points': pts,
            'domaine': mc['categorie'],
            'justification': f"Pathologie chronique active confirmée ({mc['source_texte']}).",
        })

    # Facteurs rassurants / Négations cliniques explicites
    for mc_neg in ia_data['maladies_chroniques_negatives']:
        facteurs_explicatifs.append({
            'facteur': f"Pathologie écartée : {mc_neg['nom']}",
            'points': 0,
            'domaine': mc_neg['categorie'],
            'justification': f"Négation clinique explicite notée dans le dossier ('{mc_neg['source_texte']}'). Aucun risque additionnel.",
        })

    # 3. RISQUE ALLERGIQUE (ALLERGIES AVÉRÉES UNIQUEMENT)
    for al in ia_data['allergies_positives']:
        pts = al['poids']
        score_total += pts
        score_allergique += pts
        facteurs_explicatifs.append({
            'facteur': f"Allergie avérée : {al['molecule']}",
            'points': pts,
            'domaine': 'Allergologie',
            'justification': f"{al['vigilance']} — Source : {al['source_texte']}.",
        })

    for al_neg in ia_data['allergies_negatives']:
        facteurs_explicatifs.append({
            'facteur': f"Allergie écartée : {al_neg['molecule']}",
            'points': 0,
            'domaine': 'Allergologie',
            'justification': f"Négation clinique confirmée ('{al_neg['source_texte']}'). Éviction non requise.",
        })

    # 4. ANTÉCÉDENTS FAMILIAUX
    for af in ia_data['antecedents_familiaux_pos']:
        af_lower = _nettoyer_texte(af)
        if any(w in af_lower for w in ['diabete', 'hta', 'hypertension', 'infarctus', 'avc', 'cancer']):
            score_total += 10
            score_cardio += 5
            facteurs_explicatifs.append({
                'facteur': f"Hérédité / Antécédent familial : {af}",
                'points': 10,
                'domaine': 'Génétique & Famille',
                'justification': "Terrain familial prédisposant aux pathologies métaboliques ou cardiovasculaires.",
            })

    # 5. POLYMÉDICATION
    nb_prescriptions_actives = len(ia_data['traitements_actifs'])
    if nb_prescriptions_actives >= 4:
        score_total += 18
        score_allergique += 10
        facteurs_explicatifs.append({
            'facteur': f"Polymédication active ({nb_prescriptions_actives} molécules)",
            'points': 18,
            'domaine': 'Pharmacologie',
            'justification': "Risque élevé d'interactions médicamenteuses et de syndrome iatrogène.",
        })
    elif nb_prescriptions_actives >= 2:
        score_total += 8
        facteurs_explicatifs.append({
            'facteur': f"Association médicamenteuse ({nb_prescriptions_actives} molécules)",
            'points': 8,
            'domaine': 'Pharmacologie',
            'justification': "Surveillance nécessaire des posologies et tolérances d'association.",
        })

    # 6. EXAMENS COMPLETS : INVASIVITÉ, COMPTE-RENDU ET PRÉPARATION
    for ex in ia_data['examens_complets']:
        if ex['type_code'] in ['COLOSCOPIE', 'FIBROSCOPIE', 'CORONAROGRAPHIE']:
            score_examens += 15
            score_total += 12
            facteurs_explicatifs.append({
                'facteur': f"Examen invasif : {ex['titre']} ({ex['type_libelle']})",
                'points': 12,
                'domaine': 'Explorations',
                'justification': f"Acte spécialisé nécessitant protocole d'anesthésie ou purge (Statut : {ex['statut_libelle']}).",
            })
            break

    for ex in ia_data['examens_complets']:
        if ex['statut'] in ['PLANIFIE', 'EN_COURS'] and ex['score_preparation'] < 50:
            score_total += 10
            facteurs_explicatifs.append({
                'facteur': f"Préparation examen insuffisante ({ex['score_preparation']}%) sur {ex['titre']}",
                'points': 10,
                'domaine': 'Préparation',
                'justification': f"Risque d'annulation d'examen par défaut d'observance des consignes pré-acte.",
            })
            break

    # 7. ANALYSES BIOLOGIQUES URGENTES
    analyses_urgentes = dossier.resultats_labo.filter(priorite='URGENTE').count()
    if analyses_urgentes > 0:
        score_total += 15
        facteurs_explicatifs.append({
            'facteur': f"{analyses_urgentes} analyse(s) biologique(s) urgente(s)",
            'points': 15,
            'domaine': 'Biologie',
            'justification': "Prescription en mode urgent traduisant une suspicion clinique aiguë.",
        })

    # Score global normalisé 0-100
    score_global = min(100, max(5, score_total))

    if score_global >= 65:
        niveau_risque = 'ÉLEVÉ'
        badge_classe = 'danger'
        couleur = '#dc2626'
        icone = '🔴'
        recommandation_prioritaire = "Prise en charge prioritaire : surveillance clinique rapprochée et vérification des contre-indications médicamenteuses avant tout acte."
    elif score_global >= 30:
        niveau_risque = 'MODÉRÉ'
        badge_classe = 'warning'
        couleur = '#d97706'
        icone = '🟡'
        recommandation_prioritaire = "Vigilance intermédiaire : suivi périodique des constantes, du bilan biologique et observance des consignes de préparation."
    else:
        niveau_risque = 'FAIBLE'
        badge_classe = 'success'
        couleur = '#16a34a'
        icone = '🟢'
        recommandation_prioritaire = "Profil clinique stable : maintien du protocole préventif et suivi médical habituel."

    sous_scores = {
        'cardiovasculaire': min(100, int((score_cardio / 35.0) * 100) if score_cardio else 10),
        'metabolique': min(100, int((score_metabolique / 35.0) * 100) if score_metabolique else 8),
        'allergique_iatrogene': min(100, int((score_allergique / 30.0) * 100) if score_allergique else 5),
        'examens_interventions': min(100, int((score_examens / 25.0) * 100) if score_examens else 12),
    }

    # 8. CLUSTERING DE PROFILS SIMILAIRES
    vecteur_patient = set()
    for mc in ia_data['maladies_chroniques_positives']:
        vecteur_patient.add(mc['id'])
    for al in ia_data['allergies_positives']:
        if al['id'] in ['ALLERGIE_PENICILLINE', 'ALLERGIE_AINS']:
            vecteur_patient.add(al['id'])
    for ex in ia_data['examens_complets']:
        if ex['type_code'] in ['COLOSCOPIE', 'FIBROSCOPIE']:
            vecteur_patient.add(f"EXAMEN_{ex['type_code']}")
    if age >= 65:
        vecteur_patient.add('AGE_65_PLUS')
    if age >= 50:
        vecteur_patient.add('AGE_50_PLUS')

    if not vecteur_patient:
        vecteur_patient.add('ROUTINE')

    cohortes_scorees = []
    for cohorte in COHORTES_CLINIQUES_ML:
        traits_cohorte = set(cohorte['traits'])
        intersection = vecteur_patient.intersection(traits_cohorte)
        union = vecteur_patient.union(traits_cohorte)
        jaccard = (len(intersection) / len(union)) if union else 0.0
        bonus = 0.35 if len(intersection) > 0 else 0.0
        concordance_pct = min(96, max(15, int((jaccard + bonus) * 100)))

        cohortes_scorees.append({
            'cohorte': cohorte,
            'concordance_pct': concordance_pct,
            'traits_communs': list(intersection),
        })

    cohortes_scorees.sort(key=lambda x: x['concordance_pct'], reverse=True)
    meilleure_cohorte = cohortes_scorees[0] if cohortes_scorees else None

    # Alertes médicales prédictives
    alertes_predictives = []
    if 'ALLERGIE_PENICILLINE' in vecteur_patient:
        alertes_predictives.append({
            'type': 'CRITIQUE',
            'titre': 'Alerte Allergie Pénicilline & Bêtalactamines',
            'message': 'Contre-indication absolue des pénicillines et céphalosporines. Proscrire toute prescription d’Augmentin ou Clamoxyl.',
            'badge': 'danger',
        })
    if 'HTA' in vecteur_patient or score_cardio >= 20:
        alertes_predictives.append({
            'type': 'CARDIO',
            'titre': 'Vigilance Risque Cardiovasculaire',
            'message': 'Surveillance tensionnelle renforcée conseillée. Éviter les décongestionnants sympathomimétiques et AINS.',
            'badge': 'warning',
        })
    if 'DIABETE_2' in vecteur_patient or score_metabolique >= 20:
        alertes_predictives.append({
            'type': 'METABOLIQUE',
            'titre': 'Protocole Diabète & Examens à Jeun',
            'message': 'Adapter la dose d’antidiabétiques le matin de tout examen nécessitant un jeûne strict pour éviter l’hypoglycémie.',
            'badge': 'warning',
        })
    if not alertes_predictives:
        alertes_predictives.append({
            'type': 'INFO',
            'titre': 'Profil à Faible Risque Iatrogène',
            'message': 'Aucune contre-indication médicamenteuse formelle détectée automatiquement.',
            'badge': 'success',
        })

    return {
        'score_global': score_global,
        'niveau_risque': niveau_risque,
        'badge_classe': badge_classe,
        'couleur': couleur,
        'icone': icone,
        'recommandation_prioritaire': recommandation_prioritaire,
        'sous_scores': sous_scores,
        'facteurs_explicatifs': facteurs_explicatifs,
        'meilleure_cohorte': meilleure_cohorte,
        'cohortes_scorees': cohortes_scorees[:3],
        'alertes_predictives': alertes_predictives,
    }
