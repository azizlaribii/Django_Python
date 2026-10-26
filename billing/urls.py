from django.urls import path
from . import views

urlpatterns = [
    path('tarifs/', views.tarif_list, name='tarif_list'),
    path('tarifs/nouveau/', views.tarif_create, name='tarif_create'),
    path('tarifs/<int:pk>/modifier/', views.tarif_update, name='tarif_update'),
    path('tarifs/<int:pk>/supprimer/', views.tarif_delete, name='tarif_delete'),

    path('factures/', views.facture_list, name='facture_list'),
    path('factures/<int:pk>/', views.facture_detail, name='facture_detail'),
    path('factures/nouvelle/', views.facture_create, name='facture_create'),
    path('factures/<int:pk>/modifier/', views.facture_update, name='facture_update'),
    path('factures/<int:pk>/annuler/', views.facture_cancel, name='facture_cancel'),
    path('factures/<int:pk>/paiement/', views.paiement_create, name='paiement_create'),
    path('patients/<int:patient_id>/historique/', views.patient_historique, name='patient_historique'),
    path('mon-historique/', views.patient_historique, name='mon_historique'),
    path('factures/<int:pk>/pdf/', views.facture_pdf, name='facture_pdf'),
]