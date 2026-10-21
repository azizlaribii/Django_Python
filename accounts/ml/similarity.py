"""
Module Similarity — MediConnect ML
Responsabilités :
1. Définition des cohortes archétypes de référence anonymisées (profils cliniques types).
2. Vérification que le vecteur patient comporte exactement 12 variables cliniques, dans le bon ordre.
3. Calcul mathématique de la Similarité Cosinus via Scikit-Learn (cosine_similarity).
4. Présentation claire du résultat comme une SIMILARITÉ avec un profil de référence,
   et JAMAIS comme un pourcentage de risque clinique.
5. Réconciliation stricte entre le titre réel de l'examen et son type pour adapter les recommandations
   (ex : un 'Bilan sanguin' n'est jamais confondu avec une coloscopie).
"""

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from .random_forest import valider_vecteur_patient


# Vecteurs archétypes sur les 12 dimensions cliniques normalisées :
# [age_norm, hta, diabete, dyslip, ic, ir, asthme, allergie, meds_norm, exam_inv, prep_echec, urgence]
PROFILS_ARCHETYPES = [
    {
        'id': 'CARDIO_METABOLIQUE',
        'nom': 'Profil Cardio-Métabolique à Risque Vasculaire',
        'description': 'Patients avec association HTA, diabète ou dyslipidémie nécessitant surveillance coronarienne et rénale.',
        'vecteur': np.array([0.62, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.50, 0.0, 0.0, 0.0]),
        'complications_frequentes': [
            'Accident ischémique cérébral ou transitoire',
            'Cardiopathie ischémique et infarctus du myocarde',
            'Néphropathie diabétique débutante',
        ],
        'recommandations_prevention': [
            'Contrôle tensionnel régulier (objectif < 135/85 mmHg)',
            'Dosage annuel HbA1c, bilan lipidique et créatininémie avec DFG',
            'ECG de repos annuel et échocardiographie si anomalie clinique',
        ],
    },
    {
        'id': 'ATOPIC_ALLERGIC',
        'nom': 'Profil Atopique & Terrain Allergique Sévère',
        'description': 'Patients multi-allergiques à haut risque de choc anaphylactique ou de bronchospasme aux bêtalactamines ou AINS.',
        'vecteur': np.array([0.40, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.25, 0.0, 0.0, 0.0]),
        'complications_frequentes': [
            'Choc anaphylactique ou œdème de Quincke per-anesthésique',
            'Bronchospasme aigu induit par les AINS',
            'Toxidermie médicamenteuse aiguë',
        ],
        'recommandations_prevention': [
            'Éviction formelle documentée des bêtalactamines et AINS',
            'Recherche d’alternatives thérapeutiques validées (macrolides, paracétamol)',
            'Trousse d’urgence antiallergique disponible',
        ],
    },
    {
        'id': 'ENDOSCOPIE_DIGESTIVE',
        'nom': 'Profil Digestif & Surveillance Endoscopique',
        'description': 'Patients avec explorations invasives digestives programmées nécessitant un protocole de préparation spécifique.',
        'vecteur': np.array([0.55, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.25, 1.0, 0.0, 0.0]),
        'complications_frequentes': [
            'Échec de visualisation ou report de l’acte par préparation inadéquate',
            'Déshydratation post-purge chez le patient fragile',
            'Saignement muqueux post-biopsie',
        ],
        'recommandations_prevention': [
            'Suivi rigoureux du protocole pré-examen spécifique',
            'Validation préalable de la gestion des anticoagulants',
            'Surveillance post-procédure en salle de réveil',
        ],
    },
    {
        'id': 'NEPHRO_CONTRASTE',
        'nom': 'Profil Rénal & Vigilance Produits de Contraste',
        'description': 'Patients avec fonction rénale précaire ou programmés pour un scanner injecté de produit de contraste iodé.',
        'vecteur': np.array([0.70, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.60, 1.0, 0.0, 1.0]),
        'complications_frequentes': [
            'Néphropathie aiguë induite par les produits de contraste iodés',
            'Chute brutale du débit de filtration glomérulaire (DFG)',
        ],
        'recommandations_prevention': [
            'Dosage récent de la créatininémie et DFG obligatoire avant injection',
            'Hyperhydratation pré et post-examen (1,5L)',
            'Arrêt transitoire de la metformine 48h autour de l’examen',
        ],
    },
    {
        'id': 'PREVENTION_STANDARD',
        'nom': 'Profil Standard & Suivi Préventif Ambulatoire',
        'description': 'Patient sans facteur de risque majeur aigu, relevant du parcours de soins primaire de routine.',
        'vecteur': np.array([0.35, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.10, 0.0, 0.0, 0.0]),
        'complications_frequentes': [
            'Retard diagnostique par défaut de suivi préventif périodique',
        ],
        'recommandations_prevention': [
            'Bilan biologique de dépistage périodique (glycémie, bilan lipidique)',
            'Mise à jour du calendrier vaccinal',
            'Surveillance biométrique de routine (poids, tension)',
        ],
    },
]


def classifier_examen_reel(titre, code_type):
    """
    Réconcilie le titre textuel et le code technique d'un examen pour corriger
    les erreurs d'étiquetage en base de données.
    Par exemple, si le titre contient 'Bilan sanguin - Glycémie', l'examen est classifié
    en biologie et non en coloscopie, même si le code_type en BDD est 'COLOSCOPIE'.
    """
    t = (titre or '').upper()
    c = (code_type or '').upper()

    # 1. Biologie sanguine (priorité sur les erreurs de dropdown coloscopie/scanner)
    mots_cles_bio = ['SANGUIN', 'PRISE DE SANG', 'GLYCEMIE', 'CHOLESTEROL', 'LABO', 'NFS', 'BILAN LIPIDIQUE', 'IONOGRAMME', 'CREATININE']
    if any(kw in t for kw in mots_cles_bio) or c in ['BIO', 'SANG', 'LABORATOIRE']:
        return 'BIOLOGIE_SANGUINE'

    # 2. Cardiologie (échocardiographie, ECG)
    mots_cles_cardio = ['ECHOGRAPHIE CARDIAQUE', 'ECHOCARDIOGRAPHIE', 'ECG', 'HOLTER']
    if any(kw in t for kw in mots_cles_cardio) or c in ['ECHO_CARDIAQUE', 'ECG', 'HOLTER_ECG']:
        return 'CARDIOLOGIE'

    # 3. Endoscopie digestive haute (FOGD, fibroscopie, gastroscopie)
    mots_cles_fogd = ['FOGD', 'FIBROSCOPIE', 'GASTROSCOPIE', 'OESOPHAG', 'ENDOSCOPIE HAUTE']
    if any(kw in t for kw in mots_cles_fogd) or c in ['FIBROSCOPIE', 'GASTRO']:
        return 'FOGD'

    # 4. Coloscopie / exploration basse
    mots_cles_colo = ['COLOSCOPIE', 'RECTO_SIGMO', 'RECTO', 'COLON', 'POLYP']
    if any(kw in t for kw in mots_cles_colo) or c in ['COLOSCOPIE', 'RECTO_SIGMO']:
        return 'COLOSCOPIE'

    # 5. Scanner / Imagerie injectée
    if 'SCANNER' in t or 'TDM' in t or 'SCANNER' in c:
        return 'SCANNER'

    # 6. IRM
    if 'IRM' in t or 'IRM' in c:
        return 'IRM'

    # 7. Échographie non cardiaque
    if 'ECHOGRAPHIE' in t or 'ECHO' in c:
        return 'ECHOGRAPHIE'

    return c or 'AUTRE'


def trouver_profil_similaire(vecteur_patient, examens_patient=None):
    """
    Calcule la Similarité Cosinus mathématique entre le vecteur patient (12 variables)
    et les profils archétypes de référence.

    Formule mathématique :
        cos(theta) = (u . v) / (||u||_2 * ||v||_2)

    Avertissement :
    Le résultat représente un indice géométrique de similarité de profil (0 à 100%),
    et JAMAIS une probabilité ou un niveau de risque médical.
    """
    if examens_patient is None:
        examens_patient = []

    # Validation rigoureuse de la dimension et de l'intégrité du vecteur
    vecteur = valider_vecteur_patient(vecteur_patient)

    # Matrice de tous les archétypes (5 x 12)
    matrice_archetypes = np.array([p['vecteur'] for p in PROFILS_ARCHETYPES])

    # Calcul réel Cosine Similarity via Scikit-Learn
    norme = np.linalg.norm(vecteur)
    if norme == 0:
        sims = np.zeros(len(PROFILS_ARCHETYPES))
    else:
        sims = cosine_similarity([vecteur], matrice_archetypes)[0]

    # Analyse des examens réellement programmés
    types_reels = [
        classifier_examen_reel(ex.get('titre', ''), ex.get('type_code', ''))
        for ex in examens_patient
    ]
    has_fogd = ('FOGD' in types_reels)
    has_colo = ('COLOSCOPIE' in types_reels)

    resultats = []
    for idx, profil_base in enumerate(PROFILS_ARCHETYPES):
        profil = dict(profil_base)
        profil['vecteur'] = [float(x) for x in profil_base['vecteur']]
        score_cosinus = float(sims[idx])
        pourcentage = round(max(0.0, score_cosinus) * 100, 1)

        # Adaptation médicale au geste endoscopique réel
        if profil['id'] == 'ENDOSCOPIE_DIGESTIVE':
            if has_fogd and not has_colo:
                profil['nom'] = 'Profil Endoscopie Digestive Haute (FOGD)'
                profil['description'] = 'Patient programmé pour une fibroscopie œso-gastro-duodénale (FOGD) requérant un jeûne strict et une protection des voies aériennes.'
                profil['complications_frequentes'] = [
                    "Risque d'inhalation bronchique / fausse route si estomac non vide",
                    "Dépression respiratoire ou hypotension per-sédation",
                    "Saignement muqueux superficiel en cas de biopsies œso-gastriques",
                ]
                profil['recommandations_prevention'] = [
                    "Jeûne strict de 6 heures minimum (ni boire, ni manger, ni fumer avant l'examen)",
                    "Vérification préalable de l'absence de troubles de l'hémostase",
                    "Retrait impératif de tout appareil ou prothèse dentaire amovible avant le geste",
                    "Surveillance post-procédure jusqu'au retour complet du réflexe de déglutition",
                ]
            elif has_colo:
                profil['nom'] = 'Profil Coloscopie & Exploration Basse'
                profil['description'] = 'Patient orienté vers une exploration colique nécessitant un régime sans résidu et une purge préalable.'
                profil['complications_frequentes'] = [
                    "Échec de visualisation muqueuse par préparation colique insuffisante",
                    "Déshydratation aiguë post-purge chez les sujets âgés ou polymédiqués",
                    "Saignement post-polypectomie",
                ]
                profil['recommandations_prevention'] = [
                    "Régime sans résidu strict 72 heures avant l'examen",
                    "Purge colique fractionnée selon ordonnance médicale",
                    "Validation préalable de la gestion des anticoagulants et antiagrégants",
                ]

        resultats.append({
            'cohorte': profil,
            'similarite_pct': pourcentage,
            'concordance_pct': pourcentage,  # Clé conservée pour rétrocompatibilité
            'description': profil['description'],
            'nature_mesure': "Similarité vectorielle cos(θ) avec le profil de référence (ne représente pas un niveau de risque)",
        })

    # Tri par ordre décroissant de similarité cosinus
    resultats.sort(key=lambda x: x['similarite_pct'], reverse=True)
    meilleur = resultats[0] if resultats else None

    return {
        'meilleur_profil': meilleur,
        'tous_profils': resultats[:3],
    }
