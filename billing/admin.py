from django.contrib import admin
from .models import Tarif, Facture, LigneFacture

class LigneInline(admin.TabularInline):
    model = LigneFacture
    extra = 1

@admin.register(Facture)
class FactureAdmin(admin.ModelAdmin):
    inlines = [LigneInline]
    list_display = ('numero', 'patient', 'statut', 'date_emission')
    readonly_fields = ('numero',)

admin.site.register(Tarif)
