from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db.models import Q
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
import json

from .models import (
    User, DoctorProfile, LaboratoryProfile, PatientProfile,
    AssociationMedecinPatient, DossierMedical, ExamenMedical,
    ResultatLaboratoire, Prescription, ObservationMedicale,
)
from .forms import (
    LoginForm,
    RegisterForm,
    UserProfileUpdateForm,
    DoctorProfileForm,
    LaboratoryProfileForm,
    PatientProfileForm,
    AdminUserEditForm,
    AdminCreateUserForm,
    ExamenMedicalForm,
    ResultatLaboratoireForm,
    PrescriptionForm,
    ObservationMedicaleForm,
    AssociationForm,
    DossierMedicalForm,
)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def is_admin_check(user):
    return user.is_authenticated and (user.is_admin_user or user.is_staff or user.is_superuser)


def is_doctor_check(user):
    return user.is_authenticated and (user.is_doctor or user.is_admin_user)


def is_patient_check(user):
    return user.is_authenticated and (user.is_patient or user.is_admin_user)


def get_or_create_dossier(patient_user):
    """Crée ou récupère le dossier médical d'un patient."""
    dossier, _ = DossierMedical.objects.get_or_create(patient=patient_user)
    return dossier


# ─────────────────────────────────────────────────────────────
# AUTH & PUBLIC
# ─────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────
# ESPACE PATIENT — Dashboard & Dossier
# ─────────────────────────────────────────────────────────────
@login_required
def patient_dashboard(request):
    """Tableau de bord dédié aux patients."""
    if not (request.user.is_patient or request.user.is_admin_user):
        messages.warning(request, "Accès réservé aux patients.")
        return redirect('dashboard')

    profile, _ = PatientProfile.objects.get_or_create(user=request.user)
    dossier = get_or_create_dossier(request.user)

    # Récupération des données réelles
    examens = ExamenMedical.objects.filter(dossier=dossier).order_by('-date_examen')[:5]
    resultats = ResultatLaboratoire.objects.filter(
        dossier=dossier, statut__in=['DISPONIBLE', 'TRANSMIS'],
    ).order_by('-date_prescription')[:5]
    prescriptions = Prescription.objects.filter(dossier=dossier, statut='ACTIVE').order_by('-date_prescription')
    observations = ObservationMedicale.objects.filter(dossier=dossier, confidentiel=False).order_by('-date_observation')[:3]

    # Médecin traitant
    assoc = AssociationMedecinPatient.objects.filter(
        patient=request.user, est_medecin_traitant=True
    ).select_related('medecin', 'medecin__doctor_profile').first()

    stats = {
        'prescriptions': prescriptions.count(),
        'lab_results': ResultatLaboratoire.objects.filter(
            dossier=dossier, statut__in=['DISPONIBLE', 'TRANSMIS'],
        ).count(),
        'upcoming_appointments': ExamenMedical.objects.filter(
            dossier=dossier, statut='PLANIFIE', date_examen__gte=timezone.now().date()
        ).count(),
        'observations': observations.count(),
    }

    context = {
        'profile': profile,
        'dossier': dossier,
        'stats': stats,
        'examens': examens,
        'resultats': resultats,
        'prescriptions': prescriptions,
        'observations': observations,
        'medecin_traitant': assoc,
    }
    return render(request, 'accounts/dashboard_patient.html', context)


@login_required
def patient_dossier(request):
    """Vue complète du dossier médical du patient connecté."""
    if not (request.user.is_patient or request.user.is_admin_user):
        return redirect('dashboard')

    profile, _ = PatientProfile.objects.get_or_create(user=request.user)
    dossier = get_or_create_dossier(request.user)

    examens = ExamenMedical.objects.filter(dossier=dossier).order_by('-date_examen')
    resultats = ResultatLaboratoire.objects.filter(
        dossier=dossier, statut__in=['DISPONIBLE', 'TRANSMIS'],
    ).order_by('-date_prescription')
    prescriptions = Prescription.objects.filter(dossier=dossier).order_by('-date_prescription')
    observations = ObservationMedicale.objects.filter(dossier=dossier, confidentiel=False).order_by('-date_observation')
    medecins = AssociationMedecinPatient.objects.filter(patient=request.user).select_related('medecin', 'medecin__doctor_profile')

    return render(request, 'accounts/patient_dossier.html', {
        'profile': profile,
        'dossier': dossier,
        'examens': examens,
        'resultats': resultats,
        'prescriptions': prescriptions,
        'observations': observations,
        'medecins': medecins,
    })


@login_required
def patient_edit_info(request):
    """Modification des informations personnelles du patient."""
    if not (request.user.is_patient or request.user.is_admin_user):
        return redirect('dashboard')
    profile, _ = PatientProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        user_form = UserProfileUpdateForm(request.POST, instance=request.user)
        role_form = PatientProfileForm(request.POST, instance=profile)
        if user_form.is_valid() and role_form.is_valid():
            user_form.save()
            role_form.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Profil mis à jour avec succès !'})
            messages.success(request, "Votre profil a été mis à jour !")
            return redirect('patient_dossier')
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                errors = {**user_form.errors, **role_form.errors}
                return JsonResponse({'success': False, 'errors': errors})
    else:
        user_form = UserProfileUpdateForm(instance=request.user)
        role_form = PatientProfileForm(instance=profile)

    return render(request, 'accounts/profile.html', {
        'user_form': user_form,
        'role_form': role_form,
    })


# ─────────────────────────────────────────────────────────────
# ESPACE MÉDECIN — Dashboard & Gestion Patients
# ─────────────────────────────────────────────────────────────
@login_required
def doctor_dashboard(request):
    """Tableau de bord dédié aux médecins."""
    if not (request.user.is_doctor or request.user.is_admin_user):
        messages.warning(request, "Accès réservé aux praticiens médicaux.")
        return redirect('dashboard')

    profile, _ = DoctorProfile.objects.get_or_create(user=request.user)
    search_q = request.GET.get('q', '').strip()

    # Patients associés à ce médecin
    associations = AssociationMedecinPatient.objects.filter(
        medecin=request.user
    ).select_related('patient', 'patient__patient_profile')

    if search_q:
        associations = associations.filter(
            Q(patient__first_name__icontains=search_q) |
            Q(patient__last_name__icontains=search_q) |
            Q(patient__username__icontains=search_q)
        )

    patients_ids = associations.values_list('patient_id', flat=True)
    examens_recents = ExamenMedical.objects.filter(
        medecin=request.user
    ).select_related('dossier__patient').order_by('-date_examen')[:6]

    resultats_recents = ResultatLaboratoire.objects.filter(
        medecin_prescripteur=request.user
    ).select_related('dossier__patient', 'laboratoire').order_by('-date_prescription')[:5]

    stats = {
        'patients_count': associations.count(),
        'consultations_today': ExamenMedical.objects.filter(
            medecin=request.user, date_examen=timezone.now().date()
        ).count(),
        'analyses_pending': ResultatLaboratoire.objects.filter(
            medecin_prescripteur=request.user, statut__in=['EN_ATTENTE', 'EN_COURS']
        ).count(),
        'prescriptions_month': Prescription.objects.filter(
            medecin=request.user,
            date_prescription__month=timezone.now().month
        ).count(),
    }

    # Tous les patients disponibles pour association
    tous_patients = User.objects.filter(role=User.Role.PATIENT, is_active=True).exclude(id__in=patients_ids)

    context = {
        'profile': profile,
        'stats': stats,
        'associations': associations,
        'examens_recents': examens_recents,
        'resultats_recents': resultats_recents,
        'search_q': search_q,
        'tous_patients': tous_patients,
    }
    return render(request, 'accounts/dashboard_doctor.html', context)


@login_required
def doctor_patient_dossier(request, patient_id):
    """Vue complète du dossier d'un patient par le médecin."""
    if not (request.user.is_doctor or request.user.is_admin_user):
        return redirect('dashboard')

    patient = get_object_or_404(User, id=patient_id, role=User.Role.PATIENT)

    # Vérifier que ce médecin est associé à ce patient
    if request.user.is_doctor:
        assoc = AssociationMedecinPatient.objects.filter(
            medecin=request.user, patient=patient
        ).first()
        if not assoc:
            messages.error(request, "Vous n'êtes pas autorisé à accéder au dossier de ce patient.")
            return redirect('doctor_dashboard')

    profile, _ = PatientProfile.objects.get_or_create(user=patient)
    dossier = get_or_create_dossier(patient)

    examens = ExamenMedical.objects.filter(dossier=dossier).order_by('-date_examen')
    resultats = ResultatLaboratoire.objects.filter(dossier=dossier).order_by('-date_prescription')
    prescriptions = Prescription.objects.filter(dossier=dossier).order_by('-date_prescription')
    observations = ObservationMedicale.objects.filter(dossier=dossier).order_by('-date_observation')
    medecins_assoc = AssociationMedecinPatient.objects.filter(patient=patient).select_related('medecin')

    labs = User.objects.filter(role=User.Role.LABORATOIRE, is_active=True)

    return render(request, 'accounts/doctor_patient_dossier.html', {
        'patient': patient,
        'profile': profile,
        'dossier': dossier,
        'examens': examens,
        'resultats': resultats,
        'prescriptions': prescriptions,
        'observations': observations,
        'medecins_assoc': medecins_assoc,
        'labs': labs,
    })


# ─────────────────────────────────────────────────────────────
# CRUD — ASSOCIATIONS MÉDECIN ↔ PATIENT
# ─────────────────────────────────────────────────────────────
@login_required
@require_POST
def associer_patient(request):
    """Associe un patient à un médecin."""
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    patient_id = request.POST.get('patient_id')
    notes = request.POST.get('notes', '')
    est_traitant = request.POST.get('est_medecin_traitant', 'true') == 'true'

    patient = get_object_or_404(User, id=patient_id, role=User.Role.PATIENT)
    assoc, created = AssociationMedecinPatient.objects.get_or_create(
        medecin=request.user,
        patient=patient,
        defaults={'notes': notes, 'est_medecin_traitant': est_traitant}
    )
    if created:
        get_or_create_dossier(patient)
        return JsonResponse({'success': True, 'message': f'{patient.get_full_name()} associé avec succès.'})
    else:
        return JsonResponse({'success': False, 'error': 'Ce patient est déjà dans votre liste.'})


@login_required
@require_POST
def dissocier_patient(request, patient_id):
    """Retire l'association médecin-patient."""
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    assoc = get_object_or_404(AssociationMedecinPatient, medecin=request.user, patient_id=patient_id)
    nom = assoc.patient.get_full_name() or assoc.patient.username
    assoc.delete()
    messages.success(request, f"L'association avec {nom} a été supprimée.")
    return redirect('doctor_dashboard')


# ─────────────────────────────────────────────────────────────
# CRUD — EXAMENS MÉDICAUX
# ─────────────────────────────────────────────────────────────
@login_required
@require_POST
def add_examen(request, patient_id):
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    patient = get_object_or_404(User, id=patient_id, role=User.Role.PATIENT)
    dossier = get_or_create_dossier(patient)
    form = ExamenMedicalForm(request.POST)
    if form.is_valid():
        examen = form.save(commit=False)
        examen.dossier = dossier
        examen.medecin = request.user
        examen.save()
        return JsonResponse({'success': True, 'message': 'Examen ajouté avec succès.'})
    return JsonResponse({'success': False, 'errors': form.errors})


@login_required
@require_POST
def edit_examen(request, examen_id):
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    examen = get_object_or_404(ExamenMedical, id=examen_id)
    form = ExamenMedicalForm(request.POST, instance=examen)
    if form.is_valid():
        form.save()
        return JsonResponse({'success': True, 'message': 'Examen modifié avec succès.'})
    return JsonResponse({'success': False, 'errors': form.errors})


@login_required
@require_POST
def delete_examen(request, examen_id):
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    examen = get_object_or_404(ExamenMedical, id=examen_id)
    patient_id = examen.dossier.patient.id
    examen.delete()
    messages.success(request, "Examen supprimé.")
    return redirect('doctor_patient_dossier', patient_id=patient_id)


@login_required
def get_examen_detail(request, examen_id):
    """Renvoie les détails d'un examen en JSON pour la modale."""
    examen = get_object_or_404(ExamenMedical, id=examen_id)
    data = {
        'id': examen.id,
        'titre': examen.titre,
        'type_examen': examen.type_examen,
        'description': examen.description,
        'date_examen': examen.date_examen.strftime('%Y-%m-%d'),
        'heure_examen': examen.heure_examen.strftime('%H:%M') if examen.heure_examen else '',
        'statut': examen.statut,
        'resultat': examen.resultat,
    }
    return JsonResponse(data)


# ─────────────────────────────────────────────────────────────
# CRUD — RÉSULTATS LABORATOIRE
# ─────────────────────────────────────────────────────────────
@login_required
@require_POST
def add_resultat(request, patient_id):
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    patient = get_object_or_404(User, id=patient_id, role=User.Role.PATIENT)
    dossier = get_or_create_dossier(patient)
    form = ResultatLaboratoireForm(request.POST)
    if form.is_valid():
        resultat = form.save(commit=False)
        resultat.dossier = dossier
        resultat.medecin_prescripteur = request.user
        resultat.save()
        return JsonResponse({'success': True, 'message': 'Analyse prescrite avec succès.'})
    return JsonResponse({'success': False, 'errors': form.errors})


@login_required
@require_POST
def edit_resultat(request, resultat_id):
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    resultat = get_object_or_404(ResultatLaboratoire, id=resultat_id)
    form = ResultatLaboratoireForm(request.POST, instance=resultat)
    if form.is_valid():
        form.save()
        return JsonResponse({'success': True, 'message': 'Résultat mis à jour.'})
    return JsonResponse({'success': False, 'errors': form.errors})


@login_required
@require_POST
def delete_resultat(request, resultat_id):
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    resultat = get_object_or_404(ResultatLaboratoire, id=resultat_id)
    patient_id = resultat.dossier.patient.id
    resultat.delete()
    messages.success(request, "Résultat supprimé.")
    return redirect('doctor_patient_dossier', patient_id=patient_id)


@login_required
def get_resultat_detail(request, resultat_id):
    """Renvoie les détails d'un résultat labo en JSON."""
    resultat = get_object_or_404(ResultatLaboratoire, id=resultat_id)
    data = {
        'id': resultat.id,
        'type_analyse': resultat.type_analyse,
        'reference': resultat.reference,
        'priorite': resultat.priorite,
        'statut': resultat.statut,
        'date_prescription': resultat.date_prescription.strftime('%Y-%m-%d'),
        'date_realisation': resultat.date_realisation.strftime('%Y-%m-%d') if resultat.date_realisation else '',
        'valeurs': resultat.valeurs,
        'interpretation': resultat.interpretation,
        'laboratoire_id': resultat.laboratoire_id or '',
    }
    return JsonResponse(data)


# ─────────────────────────────────────────────────────────────
# CRUD — PRESCRIPTIONS
# ─────────────────────────────────────────────────────────────
@login_required
@require_POST
def add_prescription(request, patient_id):
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    patient = get_object_or_404(User, id=patient_id, role=User.Role.PATIENT)
    dossier = get_or_create_dossier(patient)
    form = PrescriptionForm(request.POST)
    if form.is_valid():
        prescription = form.save(commit=False)
        prescription.dossier = dossier
        prescription.medecin = request.user
        prescription.save()
        return JsonResponse({'success': True, 'message': 'Prescription ajoutée.'})
    return JsonResponse({'success': False, 'errors': form.errors})


@login_required
@require_POST
def edit_prescription(request, prescription_id):
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    prescription = get_object_or_404(Prescription, id=prescription_id)
    form = PrescriptionForm(request.POST, instance=prescription)
    if form.is_valid():
        form.save()
        return JsonResponse({'success': True, 'message': 'Prescription modifiée.'})
    return JsonResponse({'success': False, 'errors': form.errors})


@login_required
@require_POST
def delete_prescription(request, prescription_id):
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    prescription = get_object_or_404(Prescription, id=prescription_id)
    patient_id = prescription.dossier.patient.id
    prescription.delete()
    messages.success(request, "Prescription supprimée.")
    return redirect('doctor_patient_dossier', patient_id=patient_id)


@login_required
def get_prescription_detail(request, prescription_id):
    """Renvoie les détails d'une prescription en JSON."""
    p = get_object_or_404(Prescription, id=prescription_id)
    data = {
        'id': p.id,
        'medicament': p.medicament,
        'posologie': p.posologie,
        'instructions': p.instructions,
        'date_prescription': p.date_prescription.strftime('%Y-%m-%d'),
        'date_fin': p.date_fin.strftime('%Y-%m-%d') if p.date_fin else '',
        'statut': p.statut,
    }
    return JsonResponse(data)


# ─────────────────────────────────────────────────────────────
# CRUD — OBSERVATIONS MÉDICALES
# ─────────────────────────────────────────────────────────────
@login_required
@require_POST
def add_observation(request, patient_id):
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    patient = get_object_or_404(User, id=patient_id, role=User.Role.PATIENT)
    dossier = get_or_create_dossier(patient)
    form = ObservationMedicaleForm(request.POST)
    if form.is_valid():
        obs = form.save(commit=False)
        obs.dossier = dossier
        obs.medecin = request.user
        obs.save()
        return JsonResponse({'success': True, 'message': 'Observation enregistrée.'})
    return JsonResponse({'success': False, 'errors': form.errors})


@login_required
@require_POST
def edit_observation(request, observation_id):
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    obs = get_object_or_404(ObservationMedicale, id=observation_id)
    form = ObservationMedicaleForm(request.POST, instance=obs)
    if form.is_valid():
        form.save()
        return JsonResponse({'success': True, 'message': 'Observation modifiée.'})
    return JsonResponse({'success': False, 'errors': form.errors})


@login_required
@require_POST
def delete_observation(request, observation_id):
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    obs = get_object_or_404(ObservationMedicale, id=observation_id)
    patient_id = obs.dossier.patient.id
    obs.delete()
    messages.success(request, "Observation supprimée.")
    return redirect('doctor_patient_dossier', patient_id=patient_id)


@login_required
def get_observation_detail(request, observation_id):
    obs = get_object_or_404(ObservationMedicale, id=observation_id)
    data = {
        'id': obs.id,
        'titre': obs.titre,
        'contenu': obs.contenu,
        'date_observation': obs.date_observation.strftime('%Y-%m-%d'),
        'confidentiel': obs.confidentiel,
    }
    return JsonResponse(data)


# ─────────────────────────────────────────────────────────────
# ESPACE LABORATOIRE
# ─────────────────────────────────────────────────────────────
@login_required
def lab_dashboard(request):
    """Tableau de bord dédié aux laboratoires d'analyse."""
    if not (request.user.is_laboratory or request.user.is_admin_user):
        messages.warning(request, "Accès réservé aux laboratoires.")
        return redirect('dashboard')

    profile, _ = LaboratoryProfile.objects.get_or_create(user=request.user)
    from laboratoire.permissions import laboratory_team_user_ids

    team_user_ids = laboratory_team_user_ids(request.user)

    pending_analyses = ResultatLaboratoire.objects.filter(
        laboratoire__in=team_user_ids
    ).select_related('dossier__patient', 'medecin_prescripteur').order_by('-date_prescription')

    total_analyses = ResultatLaboratoire.objects.filter(laboratoire__in=team_user_ids).count()
    in_progress = ResultatLaboratoire.objects.filter(laboratoire__in=team_user_ids, statut='EN_COURS').count()
    completed = ResultatLaboratoire.objects.filter(laboratoire__in=team_user_ids, statut__in=['DISPONIBLE', 'TRANSMIS']).count()
    active_doctors = ResultatLaboratoire.objects.filter(
        laboratoire__in=team_user_ids,
        medecin_prescripteur__isnull=False
    ).values('medecin_prescripteur').distinct().count()

    stats = {
        'analyses_prescrites': total_analyses,
        'analyses_today': total_analyses,
        'in_progress': in_progress,
        'completed': completed,
        'active_doctors': active_doctors,
    }

    context = {
        'profile': profile,
        'stats': stats,
        'pending_analyses': pending_analyses,
    }
    return render(request, 'accounts/dashboard_lab.html', context)


@login_required
@require_POST
def lab_update_resultat(request, resultat_id):
    """Permet au laboratoire de mettre à jour un résultat d'analyse."""
    if not request.user.is_laboratory:
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    from laboratoire.permissions import can_validate_results, laboratory_team_user_ids

    resultat = get_object_or_404(
        ResultatLaboratoire,
        id=resultat_id,
        laboratoire__in=laboratory_team_user_ids(request.user),
    )
    statut = request.POST.get('statut', resultat.statut)
    if statut not in dict(ResultatLaboratoire.STATUT_CHOICES):
        return JsonResponse({'success': False, 'error': 'Statut invalide'}, status=400)
    published_statuses = ['DISPONIBLE', 'TRANSMIS']
    if (
        (statut in published_statuses or resultat.statut in published_statuses)
        and not can_validate_results(request.user)
    ):
        return JsonResponse(
            {'success': False, 'error': 'Validation réservée aux professionnels du laboratoire'},
            status=403,
        )
    valeurs = request.POST.get('valeurs', resultat.valeurs)
    interpretation = request.POST.get('interpretation', resultat.interpretation)

    avant = {
        'statut': resultat.statut,
        'valeurs': resultat.valeurs,
        'interpretation': resultat.interpretation,
        'date_realisation': resultat.date_realisation.isoformat() if resultat.date_realisation else None,
    }
    resultat.statut = statut
    resultat.valeurs = valeurs
    resultat.interpretation = interpretation
    if statut in ['DISPONIBLE', 'TRANSMIS'] and not resultat.date_realisation:
        resultat.date_realisation = timezone.now().date()
    from laboratoire.services import enregistrer_action

    with transaction.atomic():
        resultat.save()
        enregistrer_action(
            utilisateur=request.user,
            action='RESULTAT_LEGACY_MODIFIE',
            objet='ResultatLaboratoire',
            objet_id=resultat.pk,
            details={
                'avant': avant,
                'apres': {
                    'statut': resultat.statut,
                    'valeurs': resultat.valeurs,
                    'interpretation': resultat.interpretation,
                    'date_realisation': (
                        resultat.date_realisation.isoformat() if resultat.date_realisation else None
                    ),
                },
            },
        )
    return JsonResponse({'success': True, 'message': 'Résultat mis à jour.'})


# ─────────────────────────────────────────────────────────────
# ESPACE ADMIN
# ─────────────────────────────────────────────────────────────
@login_required
@user_passes_test(is_admin_check, login_url='login')
def admin_dashboard(request):
    """Tableau de bord de gestion pour l'administrateur."""
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
