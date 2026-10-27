from django.contrib import admin

from .models import (
    AnalyseDemandee,
    DemandeAnalyse,
    HistoriqueAction,
    Prelevement,
    Resultat,
    TypeAnalyse,
)


@admin.register(TypeAnalyse)
class TypeAnalyseAdmin(admin.ModelAdmin):
    list_display = ("code", "nom", "unite", "actif")
    list_filter = ("actif",)
    search_fields = ("code", "nom")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AnalyseDemandeeInline(admin.TabularInline):
    model = AnalyseDemandee
    extra = 0
    readonly_fields = ("demande", "type_analyse", "statut")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DemandeAnalyse)
class DemandeAnalyseAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "medecin", "laboratoire", "date_demande", "statut")
    list_filter = ("statut", "priorite", "date_demande")
    search_fields = ("patient__username", "patient__first_name", "patient__last_name")
    inlines = (AnalyseDemandeeInline,)
    readonly_fields = (
        "patient", "medecin", "laboratoire", "date_demande", "priorite",
        "statut", "commentaire", "cree_par",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Prelevement)
class PrelevementAdmin(admin.ModelAdmin):
    list_display = ("code_prelevement", "demande", "type_prelevement", "statut", "date_reception")
    list_filter = ("type_prelevement", "statut")
    search_fields = ("code_prelevement",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Resultat)
class ResultatAdmin(admin.ModelAdmin):
    list_display = ("id", "analyse_demandee", "statut", "saisi_par", "valide_par", "date_validation")
    list_filter = ("statut",)
    readonly_fields = (
        "analyse_demandee", "prelevement", "valeur", "unite", "valeur_reference",
        "interpretation", "observation", "commentaire_interne",
        "commentaire_patient", "statut", "saisi_par", "valide_par",
        "date_saisie", "date_modification", "date_validation",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(HistoriqueAction)
class HistoriqueActionAdmin(admin.ModelAdmin):
    list_display = ("date_action", "utilisateur", "type_action", "objet_concerne", "objet_id")
    list_filter = ("type_action", "objet_concerne", "date_action")
    search_fields = ("utilisateur__username", "objet_concerne")
    readonly_fields = (
        "utilisateur", "type_action", "objet_concerne", "objet_id", "date_action", "details",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
