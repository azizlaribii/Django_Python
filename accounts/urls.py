from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('dashboard/', views.dashboard_router, name='dashboard'),
    path('dashboard/docteur/', views.doctor_dashboard, name='doctor_dashboard'),
    path('dashboard/laboratoire/', views.lab_dashboard, name='lab_dashboard'),
    path('dashboard/patient/', views.patient_dashboard, name='patient_dashboard'),
    path('dashboard/admin-hub/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-hub/verify/<int:user_id>/', views.toggle_user_verification, name='toggle_user_verification'),
    path('admin-hub/toggle-active/<int:user_id>/', views.toggle_user_active, name='toggle_user_active'),
    path('admin-hub/add-user/', views.admin_add_user, name='admin_add_user'),
    path('admin-hub/edit/<int:user_id>/', views.admin_edit_user, name='admin_edit_user'),
    path('admin-hub/delete/<int:user_id>/', views.admin_delete_user, name='admin_delete_user'),
    path('profile/', views.profile_view, name='profile'),
]


