from django.urls import path

from . import views

app_name = "laboratoire"

urlpatterns = [
    path("", views.demande_list, name="demande_list"),
    path("supervision/", views.supervision, name="supervision"),
    path("supervision/demandes/<int:pk>/reaffecter/", views.demande_reaffecter, name="demande_reaffecter"),
    path("supervision/demandes/<int:pk>/annuler/", views.demande_annuler_admin, name="demande_annuler_admin"),
    path("rapports/", views.rapports, name="rapports"),
    path("rapports/export/<str:format>/", views.rapports_export, name="rapports_export"),
    path("resultats/mes-resultats/", views.mes_resultats, name="mes_resultats"),
    path(
        "patient/demandes/<int:pk>/compte-rendu.pdf",
        views.patient_report_pdf,
        name="patient_report_pdf",
    ),
    path(
        "patient/anciens-resultats/<int:pk>/compte-rendu.pdf",
        views.patient_legacy_report_pdf,
        name="patient_legacy_report_pdf",
    ),
    path("medecin/alertes/", views.doctor_notifications, name="doctor_notifications"),
    path(
        "medecin/patients/<int:patient_id>/historique-analyses/",
        views.doctor_patient_history,
        name="doctor_patient_history",
    ),
    path(
        "demandes/<int:pk>/compte-rendu.pdf",
        views.doctor_report_pdf,
        name="doctor_report_pdf",
    ),
    path("demandes/nouvelle/", views.demande_create, name="demande_create"),
    path("demandes/<int:pk>/", views.demande_detail, name="demande_detail"),
    path("demandes/<int:pk>/modifier/", views.demande_update, name="demande_update"),
    path("demandes/<int:pk>/annuler/", views.demande_cancel, name="demande_cancel"),
    path("catalogue/", views.type_list, name="type_list"),
    path("catalogue/nouveau/", views.type_create, name="type_create"),
    path("catalogue/<int:pk>/modifier/", views.type_update, name="type_update"),
    path("bilans/", views.bilan_list, name="bilan_list"),
    path("bilans/nouveau/", views.bilan_create, name="bilan_create"),
    path("bilans/<int:pk>/modifier/", views.bilan_update, name="bilan_update"),
    path("parametres/", views.parametres_laboratoire, name="parametres"),
    path("demandes/<int:demande_id>/prelevements/nouveau/", views.prelevement_create, name="prelevement_create"),
    path("prelevements/<int:pk>/modifier/", views.prelevement_update, name="prelevement_update"),
    path(
        "prelevements/<int:pk>/etiquette/",
        views.prelevement_etiquette,
        name="prelevement_etiquette",
    ),
    path("analyses/<int:analyse_id>/resultats/nouveau/", views.resultat_create, name="resultat_create"),
    path("resultats/<int:pk>/modifier/", views.resultat_update, name="resultat_update"),
    path("resultats/<int:pk>/valider/", views.resultat_validate, name="resultat_validate"),
    path("resultats/<int:pk>/rejeter/", views.resultat_reject, name="resultat_reject"),
    path("validation/", views.validation_queue, name="validation_queue"),
    path("historique/", views.historique, name="historique"),
]
