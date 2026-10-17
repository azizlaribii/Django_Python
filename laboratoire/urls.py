from django.urls import path

from . import views

app_name = "laboratoire"

urlpatterns = [
    path("", views.demande_list, name="demande_list"),
    path("resultats/mes-resultats/", views.mes_resultats, name="mes_resultats"),
    path("demandes/nouvelle/", views.demande_create, name="demande_create"),
    path("demandes/<int:pk>/", views.demande_detail, name="demande_detail"),
    path("demandes/<int:pk>/modifier/", views.demande_update, name="demande_update"),
    path("demandes/<int:pk>/annuler/", views.demande_cancel, name="demande_cancel"),
    path("catalogue/", views.type_list, name="type_list"),
    path("catalogue/nouveau/", views.type_create, name="type_create"),
    path("catalogue/<int:pk>/modifier/", views.type_update, name="type_update"),
    path("demandes/<int:demande_id>/prelevements/nouveau/", views.prelevement_create, name="prelevement_create"),
    path("prelevements/<int:pk>/modifier/", views.prelevement_update, name="prelevement_update"),
    path("analyses/<int:analyse_id>/resultats/nouveau/", views.resultat_create, name="resultat_create"),
    path("resultats/<int:pk>/modifier/", views.resultat_update, name="resultat_update"),
    path("resultats/<int:pk>/valider/", views.resultat_validate, name="resultat_validate"),
    path("historique/", views.historique, name="historique"),
]
