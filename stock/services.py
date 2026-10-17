"""Logique métier du stock. Toute modification de quantité passe par ici
afin de garantir la traçabilité (chaque variation = un MouvementStock)."""
from django.db import transaction

from .models import MOTIFS_ENTREE, MOTIFS_SORTIE, MouvementStock, Produit


class StockError(Exception):
    """Erreur métier (quantité insuffisante, motif invalide...)."""


@transaction.atomic
def enregistrer_mouvement(*, produit, type_mouvement, quantite, motif,
                          utilisateur=None, commentaire="", numero_lot=""):
    if not quantite or quantite <= 0:
        raise StockError("La quantité doit être supérieure à zéro.")

    autorises = MOTIFS_ENTREE if type_mouvement == MouvementStock.Type.ENTREE else MOTIFS_SORTIE
    if motif not in autorises:
        raise StockError("Ce motif n’est pas compatible avec ce type de mouvement.")

    p = Produit.objects.select_for_update().get(pk=produit.pk)
    if not p.actif:
        raise StockError("Ce produit a été retiré du catalogue.")

    if type_mouvement == MouvementStock.Type.ENTREE:
        if p.est_expire:
            raise StockError(
                "La date de péremption de ce produit est dépassée : "
                "mettez-la à jour avant d’enregistrer une entrée."
            )
        nouvelle_quantite = p.quantite + quantite
    else:
        if quantite > p.quantite:
            raise StockError(
                f"Stock insuffisant : {p.quantite} {p.get_unite_display().lower()}(s) disponible(s)."
            )
        if p.est_expire and motif == MouvementStock.Motif.UTILISATION:
            raise StockError(
                "Ce produit est périmé et ne peut pas être utilisé. "
                "Enregistrez plutôt une sortie « Mise au rebut (péremption) »."
            )
        nouvelle_quantite = p.quantite - quantite

    p.quantite = nouvelle_quantite
    p.save(update_fields=["quantite", "updated_at"])

    return MouvementStock.objects.create(
        produit=p, type=type_mouvement, motif=motif, quantite=quantite,
        stock_apres=nouvelle_quantite, numero_lot=numero_lot,
        commentaire=commentaire, utilisateur=utilisateur,
    )


def get_alertes():
    """Produits à surveiller (utilisable aussi par le module Notifications)."""
    base = Produit.objects.actifs().select_related("categorie")
    return {
        "rupture": base.en_rupture(),
        "faible": base.stock_faible(),
        "expire": base.expires().filter(quantite__gt=0),
        "bientot": base.bientot_perimes().filter(quantite__gt=0),
    }
