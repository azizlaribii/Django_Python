from django.contrib import admin

from .models import Categorie, MouvementStock, Produit


@admin.register(Categorie)
class CategorieAdmin(admin.ModelAdmin):
    list_display = ("nom", "description")
    search_fields = ("nom",)


@admin.register(Produit)
class ProduitAdmin(admin.ModelAdmin):
    list_display = ("nom", "reference", "categorie", "quantite", "seuil_alerte", "date_peremption", "actif")
    list_filter = ("actif", "categorie")
    search_fields = ("nom", "reference", "fournisseur")
    readonly_fields = ("quantite", "created_at", "updated_at")


@admin.register(MouvementStock)
class MouvementStockAdmin(admin.ModelAdmin):
    """Lecture seule : les mouvements se créent depuis l'application pour garder le stock cohérent."""
    list_display = ("date", "produit", "type", "quantite", "motif", "stock_apres", "utilisateur")
    list_filter = ("type", "motif")
    search_fields = ("produit__nom", "produit__reference")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
