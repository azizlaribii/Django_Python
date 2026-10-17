from django.urls import path
from . import views

urlpatterns = [
    path('tarifs/', views.tarif_list, name='tarif_list'),
    path('tarifs/nouveau/', views.tarif_create, name='tarif_create'),
    path('tarifs/<int:pk>/modifier/', views.tarif_update, name='tarif_update'),
    path('tarifs/<int:pk>/supprimer/', views.tarif_delete, name='tarif_delete'),
]