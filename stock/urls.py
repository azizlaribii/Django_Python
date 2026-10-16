from django.urls import path

from . import views

app_name = "stock"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("produits/", views.produit_list, name="produit_list"),
    path("produits/nouveau/", views.produit_create, name="produit_create"),
    path("produits/<int:pk>/", views.produit_detail, name="produit_detail"),
    path("produits/<int:pk>/modifier/", views.produit_update, name="produit_update"),
    path("produits/<int:pk>/supprimer/", views.produit_delete, name="produit_delete"),
    path("produits/<int:pk>/<str:type_mouvement>/", views.mouvement_create, name="mouvement_create"),
    path("mouvements/", views.mouvement_list, name="mouvement_list"),
    path("categories/", views.categorie_list, name="categorie_list"),
    path("categories/ajouter/", views.categorie_create, name="categorie_create"),
    path("categories/<int:pk>/supprimer/", views.categorie_delete, name="categorie_delete"),
]
