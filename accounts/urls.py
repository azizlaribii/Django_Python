from django.urls import path
from . import views

urlpatterns = [
    # ── PUBLIC / AUTH ───────────────────────────────────────────
    path('', views.home_view, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('profile/', views.profile_view, name='profile'),

    # ── ROUTER ──────────────────────────────────────────────────
    path('dashboard/', views.dashboard_router, name='dashboard'),

    # ── ADMIN ───────────────────────────────────────────────────
    path('dashboard/admin-hub/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-hub/verify/<int:user_id>/', views.toggle_user_verification, name='toggle_user_verification'),
    path('admin-hub/toggle-active/<int:user_id>/', views.toggle_user_active, name='toggle_user_active'),
    path('admin-hub/add-user/', views.admin_add_user, name='admin_add_user'),
    path('admin-hub/edit/<int:user_id>/', views.admin_edit_user, name='admin_edit_user'),
    path('admin-hub/delete/<int:user_id>/', views.admin_delete_user, name='admin_delete_user'),

    # ── LABORATOIRE ─────────────────────────────────────────────
    path('dashboard/laboratoire/', views.lab_dashboard, name='lab_dashboard'),
    path('labo/resultat/<int:resultat_id>/update/', views.lab_update_resultat, name='lab_update_resultat'),

    # ── PATIENT ─────────────────────────────────────────────────
    path('dashboard/patient/', views.patient_dashboard, name='patient_dashboard'),
    path('patient/dossier/', views.patient_dossier, name='patient_dossier'),
    path('patient/edit/', views.patient_edit_info, name='patient_edit_info'),

    # ── MÉDECIN ─────────────────────────────────────────────────
    path('dashboard/docteur/', views.doctor_dashboard, name='doctor_dashboard'),
    path('docteur/patient/<int:patient_id>/dossier/', views.doctor_patient_dossier, name='doctor_patient_dossier'),

    # ── ASSOCIATIONS ────────────────────────────────────────────
    path('docteur/associer-patient/', views.associer_patient, name='associer_patient'),
    path('docteur/dissocier/<int:patient_id>/', views.dissocier_patient, name='dissocier_patient'),

    # ── EXAMENS ─────────────────────────────────────────────────
    path('docteur/patient/<int:patient_id>/examen/add/', views.add_examen, name='add_examen'),
    path('docteur/examen/<int:examen_id>/edit/', views.edit_examen, name='edit_examen'),
    path('docteur/examen/<int:examen_id>/delete/', views.delete_examen, name='delete_examen'),
    path('api/examen/<int:examen_id>/', views.get_examen_detail, name='api_examen_detail'),

    # ── RÉSULTATS LABO ──────────────────────────────────────────
    path('docteur/patient/<int:patient_id>/resultat/add/', views.add_resultat, name='add_resultat'),
    path('docteur/resultat/<int:resultat_id>/edit/', views.edit_resultat, name='edit_resultat'),
    path('docteur/resultat/<int:resultat_id>/delete/', views.delete_resultat, name='delete_resultat'),
    path('api/resultat/<int:resultat_id>/', views.get_resultat_detail, name='api_resultat_detail'),

    # ── PRESCRIPTIONS ───────────────────────────────────────────
    path('docteur/patient/<int:patient_id>/prescription/add/', views.add_prescription, name='add_prescription'),
    path('docteur/prescription/<int:prescription_id>/edit/', views.edit_prescription, name='edit_prescription'),
    path('docteur/prescription/<int:prescription_id>/delete/', views.delete_prescription, name='delete_prescription'),
    path('api/prescription/<int:prescription_id>/', views.get_prescription_detail, name='api_prescription_detail'),

    # ── OBSERVATIONS ────────────────────────────────────────────
    path('docteur/patient/<int:patient_id>/observation/add/', views.add_observation, name='add_observation'),
    path('docteur/observation/<int:observation_id>/edit/', views.edit_observation, name='edit_observation'),
    path('docteur/observation/<int:observation_id>/delete/', views.delete_observation, name='delete_observation'),
    path('api/observation/<int:observation_id>/', views.get_observation_detail, name='api_observation_detail'),
]
