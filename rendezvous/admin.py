from django.contrib import admin

from .models import Creneau, RendezVous


class RendezVousInline(admin.TabularInline):
    model = RendezVous
    fk_name = "creneau"
    extra = 0
    fields = ("patient", "statut", "motif")
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(Creneau)
class CreneauAdmin(admin.ModelAdmin):
    list_display = ("debut", "fin", "medecin", "est_bloque", "etat")
    list_filter = ("est_bloque", "medecin")
    date_hierarchy = "debut"
    search_fields = ("medecin__username", "medecin__first_name", "medecin__last_name")
    inlines = [RendezVousInline]

    @admin.display(description="État")
    def etat(self, obj):
        return {"libre": "Libre", "reserve": "Réservé", "bloque": "Bloqué", "passe": "Passé"}[obj.etat]


@admin.register(RendezVous)
class RendezVousAdmin(admin.ModelAdmin):
    list_display = ("id", "debut", "patient", "medecin", "statut", "date_creation")
    list_filter = ("statut", "medecin")
    search_fields = ("patient__username", "patient__first_name", "patient__last_name", "motif")
    raw_id_fields = ("creneau",)
    readonly_fields = ("date_creation", "date_modification", "date_confirmation", "date_annulation", "annule_par", "cree_par")

    @admin.display(description="Date", ordering="creneau__debut")
    def debut(self, obj):
        return obj.creneau.debut
