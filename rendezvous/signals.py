"""Signal émis à chaque changement d'état d'un rendez-vous.

Point d'intégration pour le module commun Notifications / rappels :

    from rendezvous.signals import rdv_statut_change

    @receiver(rdv_statut_change)
    def notifier(sender, rdv, ancien_statut, par, **kwargs):
        ...

`ancien_statut` vaut None lors de la création du rendez-vous.
"""
from django.dispatch import Signal

rdv_statut_change = Signal()
