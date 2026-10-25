from django.urls import path

from . import views

app_name = "laboratoire"

urlpatterns = [
    path("", views.demande_list, name="demande_list"),
    path("supervision/", views.supervision, name="supervision"),
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
    path(
        "demandes/<int:pk>/compte-rendu/",
        views.compte_rendu,
        name="compte_rendu",
    ),
    path(
        "demandes/<int:pk>/compte-rendu/generer/",
        views.generer_resume_view,
        name="generer_resume",
    ),
    path("demandes/<int:pk>/", views.demande_detail, name="demande_detail"),
    path("demandes/<int:pk>/modifier/", views.demande_update, name="demande_update"),
    path("demandes/<int:pk>/annuler/", views.demande_cancel, name="demande_cancel"),
    path("demandes/<int:pk>/supprimer/", views.demande_delete, name="demande_delete"),
    path("catalogue/", views.type_list, name="type_list"),
    path("catalogue/nouveau/", views.type_create, name="type_create"),
    path("catalogue/<int:pk>/modifier/", views.type_update, name="type_update"),
    path(
        "catalogue/<int:pk>/activer-desactiver/",
        views.type_toggle_active,
        name="type_toggle_active",
    ),
    path("bilans/", views.bilan_list, name="bilan_list"),
    path("bilans/nouveau/", views.bilan_create, name="bilan_create"),
    path("bilans/<int:pk>/modifier/", views.bilan_update, name="bilan_update"),
    path(
        "bilans/<int:pk>/activer-desactiver/",
        views.bilan_toggle_active,
        name="bilan_toggle_active",
    ),
    path("parametres/", views.parametres_laboratoire, name="parametres"),
    path("prelevements/", views.prelevement_list, name="prelevement_list"),
    path("prelevements/<int:pk>/etape/", views.prelevement_etape, name="prelevement_etape"),
    path("prelevements/<int:pk>/refuser/", views.prelevement_rejeter, name="prelevement_rejeter"),
    path("prelevements/<int:pk>/refaire/", views.prelevement_refaire, name="prelevement_refaire"),
    path("prelevements/<int:pk>/resultats/", views.prelevement_resultats, name="prelevement_resultats"),
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
