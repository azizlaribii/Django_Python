"""
Module IA — Suggestion Automatique de Protocole de Préparation
MediConnect / SantéConnect

Rôle : À partir du type d'examen et du profil médical du patient,
l'IA analyse le contexte clinique et recommande automatiquement :
 1. Le protocole de préparation le plus adapté (avec score de confiance)
 2. Des alertes cliniques personnalisées (ex: diabétique + contraste → Metformine)
 3. Un message d'accompagnement IA pour le patient
"""

from ..protocoles import PROTOCOLES_PREPARATION


# ─────────────────────────────────────────────────
# RÈGLES DE CORRESPONDANCE TYPE_EXAMEN → PROTOCOLES
# ─────────────────────────────────────────────────
MAPPING_TYPE_PROTOCOLE = {
    'COLOSCOPIE':             [('COLOSCOPIE', 98)],
    'RECTO_SIGMO':            [('COLOSCOPIE', 75)],
    'COLONOSCOPIE_VIRTUELLE': [('SCANNER_INJECTION', 60), ('COLOSCOPIE', 55)],
    'FIBROSCOPIE':            [('FIBROSCOPIE', 98)],
    'ECHO_ABDOMINALE':        [('ECHOGRAPHIE_ABDOMINALE', 98)],
    'ECHO_OBSTETRICALE':      [('ECHOGRAPHIE_ABDOMINALE', 90)],
    'ECHO_THYROIDE':          [('ECHOGRAPHIE_ABDOMINALE', 70)],
    'ECHO_MAMMAIRE':          [],
    'ECHO_CARDIAQUE':         [],
    'ECHO_MUSCULO':           [],
    'SCANNER_TAP':            [('SCANNER_INJECTION', 95)],
    'SCANNER_CEREBRAL':       [('SCANNER_INJECTION', 85)],
    'SCANNER_RACHIS':         [('SCANNER_INJECTION', 80)],
    'SCANNER_SINUS':          [('SCANNER_INJECTION', 70)],
    'IRM_CEREBRALE':          [],
    'IRM_RACHIS':             [],
    'IRM_PELVIENNE':          [],
    'IRM_GENOU':              [],
    'RADIO_THORAX':           [],
    'RADIO_OSSEUSE':          [],
    'MAMMOGRAPHIE':           [],
    'ECG':                    [],
    'HOLTER_ECG':             [],
    'HOLTER_PA':              [],
    'CORONAROGRAPHIE':        [('SCANNER_INJECTION', 80)],
    'EFR':                    [],
    'CYSTOSCOPIE':            [('FIBROSCOPIE', 50)],
    'BIOPSIE':                [],
    'PONCTION':               [],
    'AUTRE':                  [],
}


# ─────────────────────────────────────────────────
# RÈGLES D'ALERTES CLINIQUES CROISÉES
# ─────────────────────────────────────────────────
def _generer_alertes_cliniques(examen_ou_type, dossier):
    """
    Génère des alertes médicales personnalisées en croisant
    l'examen (type, intitulé, description) avec le profil médical complet du patient
    (antécédents, ordonnances, observations, allergies).
    """
    alertes = []
    
    # Extraction type et texte de l'examen
    if hasattr(examen_ou_type, 'type_examen'):
        type_examen = examen_ou_type.type_examen
        examen_text = f"{examen_ou_type.titre} {examen_ou_type.description}".lower()
    else:
        type_examen = str(examen_ou_type)
        examen_text = ""

    # Agrégation des informations médicales du patient
    medical_text_parts = []
    if not dossier and hasattr(examen_ou_type, 'dossier'):
        dossier = examen_ou_type.dossier

    if dossier:
        # Antécédents du profil patient (création du compte patient)
        if hasattr(dossier, 'patient'):
            pp = getattr(dossier.patient, 'patient_profile', None)
            if pp:
                medical_text_parts.append(getattr(pp, 'antecedents', '') or '')

        # Dossier médical central
        medical_text_parts.append(getattr(dossier, 'allergies', '') or '')
        medical_text_parts.append(getattr(dossier, 'antecedents_familiaux', '') or '')
        medical_text_parts.append(getattr(dossier, 'notes_generales', '') or '')

        # Traitements en cours (Prescriptions)
        try:
            for p in dossier.prescriptions.all():
                medical_text_parts.append(f"{p.medicament} {p.instructions}")
        except Exception:
            pass

        # Observations médicales
        try:
            for o in dossier.observations.all():
                medical_text_parts.append(f"{o.titre} {o.contenu}")
        except Exception:
            pass

    antecedents_text = " ".join(medical_text_parts).lower()

    # Détection examen injecté (Scanner, TDM, Artériographie, Coronaro...)
    est_scanner_ou_tdm = (
        type_examen in ('SCANNER_TAP', 'SCANNER_CEREBRAL', 'SCANNER_RACHIS',
                        'SCANNER_SINUS', 'CORONAROGRAPHIE', 'COLONOSCOPIE_VIRTUELLE')
        or any(k in examen_text for k in ['scanner', 'tdm', 'tomodensitometrie', 'coronaro', 'angioscan'])
    )
    est_avec_injection = (
        type_examen in ('SCANNER_TAP', 'CORONAROGRAPHIE')
        or any(k in examen_text for k in ['inject', 'contraste', 'iode', 'iodee', 'pci'])
        or est_scanner_ou_tdm  # par précaution sur les scanners
    )

    # ── Scanner/TDM avec injection + Diabète / Metformine → Alerte arrêt Metformine
    mots_diabete = ['diab', 'metformin', 'glucophage', 'stagid', 'janumet', 'eucreas',
                    'synjardy', 'xigduo', 'insulin', 'glycemie', 'hba1c']
    if est_scanner_ou_tdm and any(mot in antecedents_text for mot in mots_diabete):
        alertes.append({
            'niveau': 'danger',
            'icone': '⚠️',
            'titre': 'Diabète détecté — Arrêt de la Metformine requis',
            'message': (
                "Le patient présente des antécédents de diabète ou un traitement antidiabétique. "
                "En cas d'examen avec injection de produit de contraste iodé (Scanner / TDM), "
                "la Metformine (Glucophage®, Stagid®, etc.) DOIT ÊTRE ARRÊTÉE le jour de l'examen "
                "et pendant 48 heures après pour éliminer tout risque d'acidose lactique rénale. "
                "Un contrôle de la créatinine sanguine / DFG est recommandé avant la reprise."
            ),
        })

    # ── Scanner/IRM + allergie contraste
    if type_examen in ('SCANNER_TAP', 'SCANNER_CEREBRAL', 'SCANNER_RACHIS',
                        'SCANNER_SINUS', 'CORONAROGRAPHIE', 'IRM_CEREBRALE',
                        'IRM_RACHIS', 'IRM_PELVIENNE', 'IRM_GENOU'):
        if any(mot in antecedents_text for mot in ['allergie', 'iode', 'contraste', 'gadolinium']):
            alertes.append({
                'niveau': 'danger',
                'icone': '🚨',
                'titre': 'Allergie au produit de contraste signalée',
                'message': (
                    "Une allergie à l'iode ou au produit de contraste est mentionnée dans le dossier. "
                    "Le radiologue et l'anesthésiste doivent être informés avant l'examen. "
                    "Une prémédication antiallergique (corticoïdes + antihistaminiques) "
                    "sera probablement nécessaire."
                ),
            })

    # ── Endoscopies + anticoagulants
    if type_examen in ('COLOSCOPIE', 'RECTO_SIGMO', 'FIBROSCOPIE', 'CYSTOSCOPIE'):
        if any(mot in antecedents_text for mot in ['anticoagulant', 'coumadine', 'xarelto',
                                                    'eliquis', 'pradaxa', 'plavix', 'aspirine']):
            alertes.append({
                'niveau': 'warning',
                'icone': '💊',
                'titre': 'Anticoagulant / Antiagrégant détecté',
                'message': (
                    "Le dossier mentionne un traitement anticoagulant ou antiagrégant. "
                    "Ces médicaments peuvent nécessiter un arrêt temporaire avant une endoscopie "
                    "avec geste (polypectomie, biopsie). Vérifier les consignes du prescripteur."
                ),
            })

    # ── Coloscopie + insuffisance rénale → purge adaptée
    if type_examen == 'COLOSCOPIE':
        if any(mot in antecedents_text for mot in ['rénale', 'renale', 'dialyse', 'créatinine']):
            alertes.append({
                'niveau': 'warning',
                'icone': '🫘',
                'titre': 'Insuffisance rénale — Purge adaptée requise',
                'message': (
                    "En cas d'insuffisance rénale, certaines solutions de purge intestinale "
                    "(ex: Fleet Phosphosoda) sont contre-indiquées. "
                    "Le médecin doit valider le type de préparation et l'hydratation."
                ),
            })

    # ── IRM + implants métalliques
    if type_examen in ('IRM_CEREBRALE', 'IRM_RACHIS', 'IRM_PELVIENNE', 'IRM_GENOU'):
        if any(mot in antecedents_text for mot in ['pace', 'stimulateur', 'prothèse', 'prothese',
                                                    'implant', 'clip', 'stent', 'metal', 'métal']):
            alertes.append({
                'niveau': 'danger',
                'icone': '🧲',
                'titre': 'Implant métallique possible — Contre-indication IRM ?',
                'message': (
                    "Des implants, prothèses ou stimulateurs peuvent être contre-indiqués à l'IRM. "
                    "Signaler impérativement tout matériel métallique interne au radiologue "
                    "avant d'entrer dans la salle d'examen."
                ),
            })

    return alertes


# ─────────────────────────────────────────────────
# MESSAGES D'ACCOMPAGNEMENT PAR TYPE D'EXAMEN
# ─────────────────────────────────────────────────
_MESSAGES_PAR_TYPE = {
    'COLOSCOPIE': (
        "La coloscopie est un examen clé pour détecter les polypes et cancers colorectaux. "
        "La qualité de la préparation intestinale est déterminante pour sa réussite. "
        "Un côlon insuffisamment préparé peut entraîner un report ou une répétition de l'examen."
    ),
    'FIBROSCOPIE': (
        "La fibroscopie gastrique explore l'œsophage, l'estomac et le duodénum. "
        "L'estomac doit être absolument vide pour un examen de qualité et sécurisé."
    ),
    'ECHO_ABDOMINALE': (
        "L'échographie abdomino-pelvienne nécessite un estomac vide et une vessie pleine. "
        "Ces deux conditions sont indispensables pour obtenir des images de qualité diagnostique."
    ),
    'ECHO_OBSTETRICALE': (
        "L'échographie obstétricale nécessite une vessie bien remplie, surtout au 1er trimestre. "
        "Boire environ 1L d'eau 1h avant et ne pas uriner jusqu'à l'examen."
    ),
    'SCANNER_TAP': (
        "Le scanner avec injection de produit de contraste iodé nécessite des précautions rénales spécifiques. "
        "Une hydratation abondante avant et après l'examen est fortement recommandée."
    ),
    'IRM_CEREBRALE': (
        "L'IRM ne nécessite généralement pas de préparation alimentaire particulière, "
        "mais tout implant métallique (pace-maker, prothèse) doit être signalé impérativement."
    ),
}

_MESSAGE_GENERIQUE = (
    "Suivez attentivement les consignes de préparation indiquées ci-dessous. "
    "En cas de doute ou de symptôme inhabituel, contactez votre médecin prescripteur avant l'examen."
)


# ─────────────────────────────────────────────────
# FONCTION PRINCIPALE — ANALYSE IA EXAMEN
# ─────────────────────────────────────────────────
def analyser_examen_ia(examen, dossier=None):
    """
    Analyse un ExamenMedical et retourne un dict avec :
      - protocole_suggere   : clé du protocole recommandé (str ou None)
      - protocole_nom       : nom lisible
      - confiance           : score de confiance 0-100
      - protocoles_alternatifs : suggestions secondaires (list)
      - alertes_cliniques   : alertes médicales (list)
      - message_ia          : message patient personnalisé
      - a_protocole_existant : True si protocole déjà appliqué
      - suggestions_disponibles : True si l'IA a des protocoles pour ce type

    Args:
        examen  : instance ExamenMedical
        dossier : instance DossierMedical (optionnel)
    """
    type_examen = examen.type_examen
    protocole_actuel = examen.protocole_type or ''

    # 1. Récupérer les protocoles compatibles
    candidats = MAPPING_TYPE_PROTOCOLE.get(type_examen, [])
    candidats = [(k, s) for k, s in candidats if k in PROTOCOLES_PREPARATION]
    candidats.sort(key=lambda x: x[1], reverse=True)

    suggestions_disponibles = len(candidats) > 0

    # 2. Meilleure suggestion
    protocole_suggere = None
    protocole_nom = None
    confiance = 0
    protocoles_alternatifs = []

    if candidats:
        meilleur_key, meilleur_score = candidats[0]
        protocole_suggere = meilleur_key
        protocole_nom = PROTOCOLES_PREPARATION[meilleur_key]['nom']
        confiance = meilleur_score

        for alt_key, alt_score in candidats[1:]:
            protocoles_alternatifs.append({
                'key': alt_key,
                'nom': PROTOCOLES_PREPARATION[alt_key]['nom'],
                'confiance': alt_score,
            })

    # 3. Alertes cliniques personnalisées
    alertes = _generer_alertes_cliniques(examen, dossier)

    # 4. Message IA
    message_ia = _MESSAGES_PAR_TYPE.get(type_examen, _MESSAGE_GENERIQUE)

    # 5. Statut protocole actuel
    a_protocole_existant = bool(protocole_actuel and protocole_actuel in PROTOCOLES_PREPARATION)
    protocole_actuel_identique = (protocole_actuel == protocole_suggere)

    return {
        'type_examen': type_examen,
        'type_examen_display': examen.get_type_examen_display(),
        'protocole_suggere': protocole_suggere,
        'protocole_nom': protocole_nom,
        'confiance': confiance,
        'protocoles_alternatifs': protocoles_alternatifs,
        'alertes_cliniques': alertes,
        'message_ia': message_ia,
        'a_protocole_existant': a_protocole_existant,
        'protocole_actuel': protocole_actuel,
        'protocole_actuel_identique': protocole_actuel_identique,
        'suggestions_disponibles': suggestions_disponibles,
        'nb_alertes': len(alertes),
    }
