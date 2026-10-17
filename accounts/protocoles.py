"""
Protocoles médicaux prédéfinis de préparation aux examens.
Permet d'initialiser automatiquement une checklist d'étapes de préparation
avec score pondéré et seuil requis pour valider l'examen (ex: Coloscopie, Échographie...).
"""
from django.utils import timezone
from .models import EtapePreparationExamen

PROTOCOLES_PREPARATION = {
    'COLOSCOPIE': {
        'id': 'COLOSCOPIE',
        'nom': 'Coloscopie totale (Régime sans résidu & Purge intestinale)',
        'type_examen': 'COLOSCOPIE',
        'score_seuil': 100,
        'titre_par_defaut': 'Coloscopie totale avec sédation',
        'consignes_resume': (
            "1. Régime sans résidu strict pendant les 3 jours précédant l'examen.\n"
            "2. Prise de la solution de lavage intestinal selon les horaires prescrits.\n"
            "3. Jeûne complet (ni liquide, ni solide, ni tabac) 2 heures avant l'examen.\n"
            "4. Être impérativement accompagné pour le retour au domicile."
        ),
        'etapes': [
            {
                'ordre': 1,
                'delai': 'J-3 avant l’examen',
                'titre': 'Début du régime sans résidu strict',
                'description': 'Supprimer totalement fruits, légumes, céréales complètes, viandes grasses et laitages fermentés. Consommer uniquement riz blanc, pâtes, poisson blanc, volaille et biscottes.',
                'points': 20
            },
            {
                'ordre': 2,
                'delai': 'Veille (J-1) à 18h00',
                'titre': 'Arrêt des aliments solides & prise de la 1ère dose de préparation',
                'description': 'Plus aucun aliment solide. Boire la 1ère dose de la solution de purge diluée dans 1L d’eau sur 1 heure, puis boire 500ml d’eau claire ou thé clair.',
                'points': 25
            },
            {
                'ordre': 3,
                'delai': 'Veille (J-1) dans la soirée',
                'titre': 'Hydratation claire abondante',
                'description': 'Boire au moins 1L supplémentaire d’eau plate ou bouillon clair filtré pour optimiser le nettoyage du côlon.',
                'points': 15
            },
            {
                'ordre': 4,
                'delai': 'Jour J (H-4 avant examen)',
                'titre': 'Prise de la 2ème dose de préparation',
                'description': 'Boire la 2ème dose de purge diluée sur 1h. Les selles émises doivent devenir totalement liquides, claires et limpides sans résidu.',
                'points': 25
            },
            {
                'ordre': 5,
                'delai': 'Jour J (H-2 avant examen)',
                'titre': 'Jeûne strict absolu (ni liquide, ni tabac)',
                'description': 'Arrêt total de toute boisson, nourriture ou cigarette pour la sécurité anesthésique. Prévoir obligatoirement un accompagnant pour la sortie.',
                'points': 15
            },
        ]
    },
    'ECHOGRAPHIE_ABDOMINALE': {
        'id': 'ECHOGRAPHIE_ABDOMINALE',
        'nom': 'Échographie Abdomino-pelvienne (À jeun & Vessie pleine)',
        'type_examen': 'ECHO_ABDOMINALE',
        'score_seuil': 100,
        'titre_par_defaut': 'Échographie abdomino-pelvienne',
        'consignes_resume': (
            "1. À jeun strict depuis 6 heures (pas de repas, pas de boisson sucrée, pas de tabac).\n"
            "2. Boire 1 litre d'eau plate 1 heure avant l'examen.\n"
            "3. Ne pas uriner pour garder la vessie bien pleine."
        ),
        'etapes': [
            {
                'ordre': 1,
                'delai': 'H-6 avant examen',
                'titre': 'Jeûne alimentaire et arrêt du tabac',
                'description': 'Ne pas manger d’aliments solides ni liquides sucrés ou gazeux (pour éviter les gaz digestifs et permettre une bonne vidange biliaire).',
                'points': 40
            },
            {
                'ordre': 2,
                'delai': 'H-1 avant examen',
                'titre': 'Boire 1 litre d’eau plate',
                'description': 'Boire 4 à 5 verres d’eau plate en 15 minutes sans interruption.',
                'points': 30
            },
            {
                'ordre': 3,
                'delai': 'De H-1 jusqu’à l’examen',
                'titre': 'Rétention urinaire (Ne pas uriner)',
                'description': 'Garder la vessie pleine afin de créer une fenêtre acoustique pour visualiser les organes pelviens.',
                'points': 30
            },
        ]
    },
    'SCANNER_INJECTION': {
        'id': 'SCANNER_INJECTION',
        'nom': 'Scanner / TDM avec injection de produit de contraste iodé',
        'type_examen': 'SCANNER_TAP',
        'score_seuil': 100,
        'titre_par_defaut': 'Scanner thoraco-abdomino-pelvien injecté',
        'consignes_resume': (
            "1. Bilan rénal récent (Créatinine & DFG).\n"
            "2. À jeun strict 4h avant l'examen.\n"
            "3. Bonne hydratation avant et après l'examen.\n"
            "4. Arrêt temporaire des biguanides (Metformine) si diabétique."
        ),
        'etapes': [
            {
                'ordre': 1,
                'delai': 'Avant J-2',
                'titre': 'Dosage de la créatinine sanguine & DFG',
                'description': 'Fournir les résultats du bilan biologique récent vérifiant le bon fonctionnement rénal.',
                'points': 35
            },
            {
                'ordre': 2,
                'delai': '48h avant (si diabétique)',
                'titre': 'Arrêt des antidiabétiques oraux (Metformine)',
                'description': 'Suspendre les médicaments contenant de la metformine sur avis de votre médecin pour prévenir tout risque rénal.',
                'points': 25
            },
            {
                'ordre': 3,
                'delai': 'H-4 avant examen',
                'titre': 'Jeûne alimentaire strict',
                'description': 'Ne pas consommer de nourriture solide ni de boisson autre qu’une petite quantité d’eau plate.',
                'points': 25
            },
            {
                'ordre': 4,
                'delai': 'Jour J',
                'titre': 'Apporter le produit de contraste & ordonnance',
                'description': 'Récupérer le produit de contraste iodé prescrit en pharmacie et l’apporter avec vos clichés antérieurs.',
                'points': 15
            },
        ]
    },
    'FIBROSCOPIE': {
        'id': 'FIBROSCOPIE',
        'nom': 'Endoscopie digestive haute / Fibroscopie œso-gastro-duodénale',
        'type_examen': 'FIBROSCOPIE',
        'score_seuil': 100,
        'titre_par_defaut': 'Endoscopie œso-gastro-duodénale (FOGD)',
        'consignes_resume': (
            "1. À jeun strict depuis 6 heures (aucun aliment solide).\n"
            "2. Arrêt des liquides et du tabac 3h avant.\n"
            "3. Retirer prothèses dentaires et lunettes avant l'examen."
        ),
        'etapes': [
            {
                'ordre': 1,
                'delai': 'H-6 avant examen',
                'titre': 'Jeûne solide complet',
                'description': 'L’estomac doit être entièrement vide pour permettre un examen visuel net et éviter les régurgitations.',
                'points': 40
            },
            {
                'ordre': 2,
                'delai': 'H-3 avant examen',
                'titre': 'Arrêt total des liquides et de la cigarette',
                'description': 'Ne plus boire ni fumer (le tabac stimule les sécrétions gastriques acides).',
                'points': 40
            },
            {
                'ordre': 3,
                'delai': 'Avant d’entrer en salle',
                'titre': 'Retrait des prothèses amovibles et bijoux',
                'description': 'Retirer prothèses dentaires mobiles et lunettes pour faciliter le passage sécurisé de l’endoscope.',
                'points': 20
            },
        ]
    }
}


def appliquer_protocole_examen(examen, protocole_key):
    """
    Applique un protocole prédéfini à un examen médical :
    remplit les consignes et génère les étapes de préparation associées.
    """
    proto = PROTOCOLES_PREPARATION.get(protocole_key)
    if not proto:
        return False

    # Mettre à jour le type, le résumé des consignes et le seuil requis
    examen.protocole_type = proto['id']
    if not examen.consignes_preparation:
        examen.consignes_preparation = proto['consignes_resume']
    if proto.get('score_seuil'):
        examen.score_seuil_validation = proto['score_seuil']

    examen.save(update_fields=['protocole_type', 'consignes_preparation', 'score_seuil_validation'])

    # Supprimer d'éventuelles anciennes étapes et créer les étapes du protocole
    examen.etapes_preparation.all().delete()
    for etape_data in proto['etapes']:
        EtapePreparationExamen.objects.create(
            examen=examen,
            ordre=etape_data.get('ordre', 0),
            delai=etape_data.get('delai', ''),
            titre=etape_data.get('titre', ''),
            description=etape_data.get('description', ''),
            points=etape_data.get('points', 20),
            est_validee=False,
        )

    # Recalculer le score initial (0%)
    examen.recalculer_score_preparation(save=True)
    return True
