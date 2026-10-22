from django.urls import path

from . import views

app_name = "rendezvous"

urlpatterns = [
    path("", views.rdv_list, name="rdv_list"),
    path("calendrier/", views.calendrier, name="calendrier"),
    path("reserver/", views.reserver, name="reserver"),
    path("reserver/<int:pk>/", views.reserver_creneau, name="reserver_creneau"),
    path("<int:pk>/", views.rdv_detail, name="rdv_detail"),
    path("<int:pk>/confirmer/", views.rdv_confirmer, name="rdv_confirmer"),
    path("<int:pk>/annuler/", views.rdv_annuler, name="rdv_annuler"),
    path("<int:pk>/modifier/", views.rdv_deplacer, name="rdv_deplacer"),
    path("<int:pk>/cloturer/", views.rdv_cloturer, name="rdv_cloturer"),
    path("creneaux/", views.creneau_list, name="creneau_list"),
    path("creneaux/ajouter/", views.creneau_ajouter, name="creneau_ajouter"),
    path("creneaux/generer/", views.creneau_generer, name="creneau_generer"),
    path("creneaux/<int:pk>/modifier/", views.creneau_modifier, name="creneau_modifier"),
    path("creneaux/<int:pk>/bloquer/", views.creneau_bloquer, name="creneau_bloquer"),
    path("creneaux/<int:pk>/supprimer/", views.creneau_supprimer, name="creneau_supprimer"),
    path("api/suggestion-specialite/", views.api_suggestion_specialite, name="api_suggestion_specialite"),
    path("ia/performance/", views.ia_performance, name="ia_performance"),
    path("api/creneaux-disponibles/", views.api_creneaux_disponibles, name="api_creneaux_disponibles"),
]
