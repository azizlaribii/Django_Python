from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db.models import Q

from .models import User, DoctorProfile, LaboratoryProfile, PatientProfile
from .forms import (
    LoginForm,
    RegisterForm,
    UserProfileUpdateForm,
    DoctorProfileForm,
    LaboratoryProfileForm,
    PatientProfileForm,
    AdminUserEditForm,
    AdminCreateUserForm,
)




def home_view(request):
    """Page d'accueil moderne de la plateforme."""
    stats = {
        'doctors': User.objects.filter(role=User.Role.DOCTEUR, is_active=True).count(),
        'labs': User.objects.filter(role=User.Role.LABORATOIRE, is_active=True).count(),
        'patients': User.objects.filter(role=User.Role.PATIENT, is_active=True).count(),
    }
    return render(request, 'home.html', {'stats': stats})


def login_view(request):
    """Gestion de la connexion avec redirection selon le rôle."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Ravi de vous revoir, {user.get_full_name() or user.username} !")
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('dashboard')
        else:
            messages.error(request, "Veuillez corriger les erreurs ci-dessous.")
    else:
        form = LoginForm()

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    """Déconnexion de l'utilisateur."""
    logout(request)
    messages.info(request, "Vous avez été déconnecté avec succès.")
    return redirect('login')


def register_view(request):
    """Inscription multi-rôles pour Docteur, Laboratoire ou Patient."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    default_role = request.GET.get('role', User.Role.PATIENT)
    if default_role not in [User.Role.DOCTEUR, User.Role.LABORATOIRE, User.Role.PATIENT]:
        default_role = User.Role.PATIENT

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Félicitations {user.username} ! Votre compte a été créé avec succès.")
            return redirect('dashboard')
        else:
            messages.error(request, "Erreur lors de la création du compte. Vérifiez les champs saisis.")
    else:
        form = RegisterForm(initial={'role': default_role})

    return render(request, 'accounts/register.html', {
        'form': form,
        'default_role': default_role
    })


@login_required
def dashboard_router(request):
    """Achemine l'utilisateur vers le bon tableau de bord selon son rôle."""
    if request.user.is_admin_user:
        return redirect('admin_dashboard')
    elif request.user.is_doctor:
        return redirect('doctor_dashboard')
    elif request.user.is_laboratory:
        return redirect('lab_dashboard')
    elif request.user.is_patient:
        return redirect('patient_dashboard')
    else:
        return redirect('home')


@login_required
def doctor_dashboard(request):
    """Tableau de bord dédié aux médecins."""
    if not (request.user.is_doctor or request.user.is_admin_user):
        messages.warning(request, "Accès réservé aux praticiens médicaux.")
        return redirect('dashboard')

    profile, _ = DoctorProfile.objects.get_or_create(user=request.user)

    # Données simulées pour la démo médicale
    context = {
        'profile': profile,
        'stats': {
            'patients_count': 42,
            'consultations_today': 7,
            'analyses_pending': 4,
            'prescriptions_month': 89,
        },
        'recent_patients': [
            {'nom': 'Mme Sophie Martin', 'motif': 'Bilan sanguin complet', 'heure': '09:30', 'statut': 'Terminé'},
            {'nom': 'M. Thomas Bernard', 'motif': 'Consultation cardiologie', 'heure': '11:00', 'statut': 'En cours'},
            {'nom': 'Mme Claire Robert', 'motif': 'Suivi traitement', 'heure': '14:15', 'statut': 'À venir'},
            {'nom': 'M. Karim Alami', 'motif': 'Contrôle tension artérielle', 'heure': '16:00', 'statut': 'À venir'},
        ],
        'lab_requests': [
            {'patient': 'Sophie Martin', 'labo': 'BioSanté Lab', 'analyse': 'NFS + Glycémie à jeun', 'statut': 'Résultats reçus'},
            {'patient': 'Thomas Bernard', 'labo': 'Centre Analyse Pasteur', 'analyse': 'Profil Lipidique', 'statut': 'En cours d\'analyse'},
        ]
    }
    return render(request, 'accounts/dashboard_doctor.html', context)


@login_required
def lab_dashboard(request):
    """Tableau de bord dédié aux laboratoires d'analyse."""
    if not (request.user.is_laboratory or request.user.is_admin_user):
        messages.warning(request, "Accès réservé aux laboratoires.")
        return redirect('dashboard')

    profile, _ = LaboratoryProfile.objects.get_or_create(user=request.user)

    context = {
        'profile': profile,
        'stats': {
            'analyses_today': 28,
            'in_progress': 9,
            'completed': 19,
            'active_doctors': 14,
        },
        'pending_analyses': [
            {'id': 'AN-9402', 'patient': 'Mme Julie Lefebvre', 'medecin': 'Dr. Alexandre Moreau', 'type': 'Hémogramme complet', 'priorite': 'Haute', 'statut': 'En cours'},
            {'id': 'AN-9403', 'patient': 'M. Marc Dubois', 'medecin': 'Dr. Nadia Belkacem', 'type': 'Bilan Hépatique & Rénal', 'priorite': 'Normale', 'statut': 'À valider'},
            {'id': 'AN-9404', 'patient': 'Mme Sarah Cohen', 'medecin': 'Dr. Alexandre Moreau', 'type': 'Test Sérologie & PCR', 'priorite': 'Urgente', 'statut': 'En cours'},
            {'id': 'AN-9405', 'patient': 'M. Lucas Petit', 'medecin': 'Dr. Eric Lambert', 'type': 'Ionogramme sanguin', 'priorite': 'Normale', 'statut': 'Prêt à envoyer'},
        ]
    }
    return render(request, 'accounts/dashboard_lab.html', context)


@login_required
def patient_dashboard(request):
    """Tableau de bord dédié aux patients."""
    if not (request.user.is_patient or request.user.is_admin_user):
        messages.warning(request, "Accès réservé aux patients.")
        return redirect('dashboard')

    profile, _ = PatientProfile.objects.get_or_create(user=request.user)

    context = {
        'profile': profile,
        'stats': {
            'prescriptions': 3,
            'lab_results': 5,
            'upcoming_appointments': 1,
        },
        'medical_records': [
            {'date': '12 Octobre 2026', 'titre': 'Bilan Biologique Complet', 'emetteur': 'BioSanté Lab', 'type': 'Laboratoire', 'telecharger': True},
            {'date': '28 Septembre 2026', 'titre': 'Ordonnance Traitement Saisonnier', 'emetteur': 'Dr. Alexandre Moreau', 'type': 'Prescription', 'telecharger': True},
            {'date': '15 Août 2026', 'titre': 'Certificat Médical d\'aptitude', 'emetteur': 'Dr. Nadia Belkacem', 'type': 'Document', 'telecharger': True},
        ],
        'upcoming_appointment': {
            'date': '24 Octobre 2026',
            'heure': '10:30',
            'praticien': 'Dr. Alexandre Moreau',
            'specialite': 'Médecine Générale',
            'adresse': '14 Avenue de la République, 75011 Paris'
        }
    }
    return render(request, 'accounts/dashboard_patient.html', context)


def is_admin_check(user):
    return user.is_authenticated and (user.is_admin_user or user.is_staff or user.is_superuser)


@login_required
@user_passes_test(is_admin_check, login_url='login')
def admin_dashboard(request):
    """Tableau de bord de gestion pour l'administrateur (Docteurs, Labos, Patients)."""
    search_query = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', 'ALL')

    users_qs = User.objects.all().select_related(
        'doctor_profile', 'lab_profile', 'patient_profile'
    ).order_by('-date_joined')

    if search_query:
        users_qs = users_qs.filter(
            Q(username__istartswith=search_query) |
            Q(first_name__istartswith=search_query) |
            Q(last_name__istartswith=search_query) |
            Q(email__istartswith=search_query) |
            Q(city__istartswith=search_query) |
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query)
        )


    if role_filter != 'ALL':
        users_qs = users_qs.filter(role=role_filter)

    total_users = User.objects.count()
    doctors_count = User.objects.filter(role=User.Role.DOCTEUR).count()
    labs_count = User.objects.filter(role=User.Role.LABORATOIRE).count()
    patients_count = User.objects.filter(role=User.Role.PATIENT).count()
    pending_verification = User.objects.filter(
        role__in=[User.Role.DOCTEUR, User.Role.LABORATOIRE],
        is_verified=False
    ).count()

    context = {
        'users': users_qs,
        'search_query': search_query,
        'role_filter': role_filter,
        'stats': {
            'total': total_users,
            'doctors': doctors_count,
            'labs': labs_count,
            'patients': patients_count,
            'pending': pending_verification,
        }
    }
    return render(request, 'accounts/dashboard_admin.html', context)


@login_required
@user_passes_test(is_admin_check, login_url='login')
@require_POST
def toggle_user_verification(request, user_id):
    """Action rapide pour certifier ou annuler la certification d'un compte."""
    user = get_object_or_404(User, id=user_id)
    user.is_verified = not user.is_verified
    user.save()
    status_text = "certifié" if user.is_verified else "non certifié"
    messages.success(request, f"Le compte de {user.username} est désormais {status_text}.")
    return redirect('admin_dashboard')


@login_required
@user_passes_test(is_admin_check, login_url='login')
@require_POST
def toggle_user_active(request, user_id):
    """Action rapide pour activer ou suspendre un compte utilisateur."""
    user = get_object_or_404(User, id=user_id)
    if user == request.user:
        messages.error(request, "Vous ne pouvez pas désactiver votre propre compte administrateur.")
        return redirect('admin_dashboard')

    user.is_active = not user.is_active
    user.save()
    status_text = "activé" if user.is_active else "désactivé / suspendu"
    messages.success(request, f"Le compte de {user.username} a été {status_text}.")
    return redirect('admin_dashboard')


@login_required
def profile_view(request):
    """Modification des données du profil de l'utilisateur connecté."""
    user = request.user
    role_form = None

    if request.method == 'POST':
        user_form = UserProfileUpdateForm(request.POST, instance=user)

        if user.role == User.Role.DOCTEUR:
            profile, _ = DoctorProfile.objects.get_or_create(user=user)
            role_form = DoctorProfileForm(request.POST, instance=profile)
        elif user.role == User.Role.LABORATOIRE:
            profile, _ = LaboratoryProfile.objects.get_or_create(user=user)
            role_form = LaboratoryProfileForm(request.POST, instance=profile)
        elif user.role == User.Role.PATIENT:
            profile, _ = PatientProfile.objects.get_or_create(user=user)
            role_form = PatientProfileForm(request.POST, instance=profile)

        if user_form.is_valid() and (role_form is None or role_form.is_valid()):
            user_form.save()
            if role_form:
                role_form.save()
            messages.success(request, "Votre profil a été mis à jour avec succès !")
            return redirect('profile')
        else:
            messages.error(request, "Veuillez corriger les erreurs dans le formulaire.")
    else:
        user_form = UserProfileUpdateForm(instance=user)
        if user.role == User.Role.DOCTEUR:
            profile, _ = DoctorProfile.objects.get_or_create(user=user)
            role_form = DoctorProfileForm(instance=profile)
        elif user.role == User.Role.LABORATOIRE:
            profile, _ = LaboratoryProfile.objects.get_or_create(user=user)
            role_form = LaboratoryProfileForm(instance=profile)
        elif user.role == User.Role.PATIENT:
            profile, _ = PatientProfile.objects.get_or_create(user=user)
            role_form = PatientProfileForm(instance=profile)

    return render(request, 'accounts/profile.html', {
        'user_form': user_form,
        'role_form': role_form,
    })


@login_required
@user_passes_test(is_admin_check, login_url='login')
def admin_edit_user(request, user_id):
    """Page dédiée et claire permettant à l'administrateur de modifier entièrement un compte."""
    target_user = get_object_or_404(User, id=user_id)
    role_form = None

    if request.method == 'POST':
        user_form = AdminUserEditForm(request.POST, instance=target_user)

        if target_user.role == User.Role.DOCTEUR:
            profile, _ = DoctorProfile.objects.get_or_create(user=target_user)
            role_form = DoctorProfileForm(request.POST, instance=profile)
        elif target_user.role == User.Role.LABORATOIRE:
            profile, _ = LaboratoryProfile.objects.get_or_create(user=target_user)
            role_form = LaboratoryProfileForm(request.POST, instance=profile)
        elif target_user.role == User.Role.PATIENT:
            profile, _ = PatientProfile.objects.get_or_create(user=target_user)
            role_form = PatientProfileForm(request.POST, instance=profile)

        if user_form.is_valid() and (role_form is None or role_form.is_valid()):
            updated_user = user_form.save()
            if role_form:
                role_form.save()
            messages.success(request, f"✓ Le compte de {updated_user.get_full_name() or updated_user.username} a été modifié avec succès !")
            return redirect('admin_dashboard')
        else:
            messages.error(request, "Erreur lors de la modification. Veuillez vérifier les champs obligatoires.")
    else:
        user_form = AdminUserEditForm(instance=target_user)
        if target_user.role == User.Role.DOCTEUR:
            profile, _ = DoctorProfile.objects.get_or_create(user=target_user)
            role_form = DoctorProfileForm(instance=profile)
        elif target_user.role == User.Role.LABORATOIRE:
            profile, _ = LaboratoryProfile.objects.get_or_create(user=target_user)
            role_form = LaboratoryProfileForm(instance=profile)
        elif target_user.role == User.Role.PATIENT:
            profile, _ = PatientProfile.objects.get_or_create(user=target_user)
            role_form = PatientProfileForm(instance=profile)

    return render(request, 'accounts/admin_edit_user.html', {
        'target_user': target_user,
        'user_form': user_form,
        'role_form': role_form,
    })


@login_required
@user_passes_test(is_admin_check, login_url='login')
@require_POST
def admin_delete_user(request, user_id):
    """Permet à l'administrateur de supprimer un compte utilisateur."""
    target_user = get_object_or_404(User, id=user_id)
    if target_user == request.user:
        messages.error(request, "Vous ne pouvez pas supprimer votre propre compte administrateur.")
        return redirect('admin_dashboard')

    name = target_user.get_full_name() or target_user.username
    target_user.delete()
    messages.success(request, f"Le compte de {name} a été définitivement supprimé.")
    return redirect('admin_dashboard')


@login_required
@user_passes_test(is_admin_check, login_url='login')
def admin_add_user(request):
    """Permet à l'administrateur de créer directement un compte (Docteur, Laboratoire, Patient ou Admin)."""
    default_role = request.GET.get('role', User.Role.PATIENT)
    if default_role not in [User.Role.DOCTEUR, User.Role.LABORATOIRE, User.Role.PATIENT, User.Role.ADMIN]:
        default_role = User.Role.PATIENT

    if request.method == 'POST':
        form = AdminCreateUserForm(request.POST)
        if form.is_valid():
            new_user = form.save()
            messages.success(request, f"✓ Le compte de {new_user.get_full_name() or new_user.username} ({new_user.get_role_display()}) a été créé avec succès !")
            return redirect('admin_dashboard')
        else:
            messages.error(request, "Erreur lors de la création du compte. Veuillez vérifier les champs saisis.")
    else:
        form = AdminCreateUserForm(initial={'role': default_role, 'is_verified': True, 'is_active': True})

    return render(request, 'accounts/admin_add_user.html', {
        'form': form,
        'default_role': default_role,
    })


