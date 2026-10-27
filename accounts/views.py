from datetime import timedelta

from django.conf import settings
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
    EtapePreparationExamen,
)
from .protocoles import PROTOCOLES_PREPARATION, appliquer_protocole_examen
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
    ExamenMedicalFullForm,
    ResultatLaboratoireForm,
    PrescriptionForm,
    ObservationMedicaleForm,
    AssociationForm,
    DossierMedicalForm,
    NouveauPatientDossierForm,
    PatientDossierEditForm,
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
    if not patient_user or getattr(patient_user, 'role', None) != User.Role.PATIENT:
        return None
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
    if not request.user.is_patient:
        messages.warning(request, "Accès réservé aux patients.")
        return redirect('dashboard')

    profile, _ = PatientProfile.objects.get_or_create(user=request.user)
    dossier = get_or_create_dossier(request.user)

    # Récupération des données réelles
    examens = ExamenMedical.objects.filter(dossier=dossier).order_by('-date_creation', '-id')[:5]
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
    from laboratoire.models import Resultat as ResultatAnalyse

    stats['lab_new_results'] = ResultatAnalyse.objects.filter(
        analyse_demandee__demande__patient=request.user,
        statut=ResultatAnalyse.Statut.VALIDE,
        date_validation__gte=timezone.now() - timedelta(days=7),
    ).count()

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
    if not request.user.is_patient:
        return redirect('dashboard')

    profile, _ = PatientProfile.objects.get_or_create(user=request.user)
    dossier = get_or_create_dossier(request.user)

    examens = ExamenMedical.objects.filter(dossier=dossier).select_related('medecin').prefetch_related('etapes_preparation').order_by('-date_creation', '-id')
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
    ).select_related('dossier__patient').order_by('-date_creation', '-id')[:6]

    resultats_recents = ResultatLaboratoire.objects.filter(
        medecin_prescripteur=request.user
    ).select_related('dossier__patient', 'laboratoire').order_by('-date_prescription')[:5]

    from laboratoire.models import DemandeAnalyse, Resultat

    demandes_resume = DemandeAnalyse.objects.filter(
        medecin=request.user,
        analyses__resultats__statut=Resultat.Statut.VALIDE,
    ).select_related(
        'patient',
    ).distinct().order_by('-date_demande')[:5]

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
        'demandes_resume': demandes_resume,
        'ia_resume_configuree': bool(
            getattr(settings, 'GOOGLE_API_KEY', '').strip()
            or getattr(settings, 'GEMINI_API_KEY', '').strip()
            or getattr(settings, 'ANTHROPIC_API_KEY', '').strip()
        ),
        'search_q': search_q,
        'tous_patients': tous_patients,
    }
    return render(request, 'accounts/dashboard_doctor.html', context)


@login_required
def doctor_patient_dossier(request, patient_id):
    """Vue complète du dossier d'un patient par le médecin."""
    if not (request.user.is_doctor or request.user.is_admin_user):
        return redirect('dashboard')

    patient = User.objects.filter(id=patient_id, role=User.Role.PATIENT).first()
    if not patient:
        messages.error(request, "Patient introuvable ou le compte demandé n'est pas un patient.")
        return redirect('dossiers_patients_list' if (request.user.is_admin_user or request.user.is_doctor) else 'dashboard')

    # Association médecin-patient : autorise la consultation pour tout médecin ou admin.
    # Si le praticien n'était pas encore rattaché, on l'associe pour lui permettre de suivre le patient.
    if request.user.is_doctor:
        assoc = AssociationMedecinPatient.objects.filter(
            medecin=request.user, patient=patient
        ).first()
        if not assoc:
            AssociationMedecinPatient.objects.get_or_create(
                medecin=request.user,
                patient=patient,
                defaults={
                    'est_medecin_traitant': False,
                    'notes': 'Association médicale lors de la consultation du dossier.',
                }
            )

    profile, _ = PatientProfile.objects.get_or_create(user=patient)
    dossier = get_or_create_dossier(patient)

    examens = ExamenMedical.objects.filter(dossier=dossier).order_by('-date_creation', '-id')
    resultats = ResultatLaboratoire.objects.filter(dossier=dossier).order_by('-date_prescription')
    prescriptions = Prescription.objects.filter(dossier=dossier).order_by('-date_prescription')
    observations = ObservationMedicale.objects.filter(dossier=dossier).order_by('-date_observation')
    medecins_assoc = AssociationMedecinPatient.objects.filter(patient=patient).select_related('medecin')

    labs = User.objects.filter(role=User.Role.LABORATOIRE, is_active=True)

    # ── IA & ML Médical : Analyse intelligente du dossier & Détection des risques
    from .medical_ai import analyser_dossier_ia
    from .medical_ml import evaluer_risques_machine_learning
    ia_data = analyser_dossier_ia(patient, dossier)
    ml_data = evaluer_risques_machine_learning(patient, dossier, ia_data)

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
        'types_choices': ExamenMedical.TYPE_CHOICES,
        'protocoles': PROTOCOLES_PREPARATION,
        'ia_data': ia_data,
        'ml_data': ml_data,
    })


# ─────────────────────────────────────────────────────────────
# CRUD — ASSOCIATIONS MÉDECIN ↔ PATIENT
# ─────────────────────────────────────────────────────────────
@login_required
@require_POST
def associer_patient(request):
    """Associe un patient à un médecin (ou change le médecin traitant)."""
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    patient_id = request.POST.get('patient_id')
    notes = request.POST.get('notes', '')
    est_traitant = request.POST.get('est_medecin_traitant', 'true') in ['true', 'True', '1', True, 'on']
    medecin_id = request.POST.get('medecin_id')

    if medecin_id:
        medecin = get_object_or_404(User, id=medecin_id, role=User.Role.DOCTEUR)
    elif request.user.is_doctor:
        medecin = request.user
    else:
        return JsonResponse({'success': False, 'error': 'Veuillez sélectionner un médecin.'}, status=400)

    patient = get_object_or_404(User, id=patient_id, role=User.Role.PATIENT)

    if est_traitant:
        AssociationMedecinPatient.objects.filter(patient=patient, est_medecin_traitant=True).exclude(medecin=medecin).update(est_medecin_traitant=False)

    assoc, created = AssociationMedecinPatient.objects.get_or_create(
        medecin=medecin,
        patient=patient,
        defaults={'notes': notes, 'est_medecin_traitant': est_traitant}
    )
    if not created:
        assoc.est_medecin_traitant = est_traitant
        if notes:
            assoc.notes = notes
        assoc.save()

    get_or_create_dossier(patient)
    role_libelle = "Médecin traitant principal" if est_traitant else "Médecin spécialiste / correspondant"
    return JsonResponse({
        'success': True,
        'message': f"Dr. {medecin.get_full_name()} associé à {patient.get_full_name()} ({role_libelle})."
    })


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
    if not request.user.is_doctor:
        return JsonResponse({'success': False, 'error': 'Action réservée aux médecins. L’administrateur peut uniquement consulter les examens.'}, status=403)

    patient = get_object_or_404(User, id=patient_id, role=User.Role.PATIENT)
    dossier = get_or_create_dossier(patient)
    form = ExamenMedicalForm(request.POST)
    if form.is_valid():
        examen = form.save(commit=False)
        examen.dossier = dossier
        examen.medecin = request.user

        score_seuil = request.POST.get('score_seuil_validation')
        if score_seuil:
            try:
                examen.score_seuil_validation = int(score_seuil)
            except ValueError:
                pass
        examen.save()

        # Application automatique du protocole si sélectionné (ex: Coloscopie)
        protocole = request.POST.get('protocole_type', '').strip()
        if protocole and protocole in PROTOCOLES_PREPARATION:
            appliquer_protocole_examen(examen, protocole)

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
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)
        return redirect('dashboard')

    examen = get_object_or_404(ExamenMedical, id=examen_id)
    titre = examen.titre
    examen.delete()
    messages.success(request, f"L'examen « {titre} » a été supprimé.")

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': 'Examen supprimé avec succès.'})

    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
    if next_url:
        return redirect(next_url)

    return redirect('examens_list')


@login_required
def get_examen_detail(request, examen_id):
    """Renvoie les détails d'un examen en JSON pour la modale."""
    examen = get_object_or_404(
        ExamenMedical.objects.select_related('dossier__patient', 'medecin'),
        id=examen_id
    )
    data = {
        'id': examen.id,
        'titre': examen.titre,
        'type_examen': examen.type_examen,
        'type_display': examen.get_type_examen_display(),
        'description': examen.description,
        'date_examen': examen.date_examen.strftime('%Y-%m-%d'),
        'heure_examen': examen.heure_examen.strftime('%H:%M') if examen.heure_examen else '',
        'lieu_examen': examen.lieu_examen or '',
        'consignes_preparation': examen.consignes_preparation or '',
        'statut_preparation': examen.statut_preparation,
        'statut_preparation_display': examen.get_statut_preparation_display(),
        'statut': examen.statut,
        'statut_display': examen.get_statut_display(),
        'resultat': examen.resultat or '',
        'patient_id': examen.dossier.patient.id,
        'patient_name': examen.dossier.patient.get_full_name() or examen.dossier.patient.username,
        'medecin_id': examen.medecin.id if examen.medecin else '',
        'medecin_name': examen.medecin.get_full_name() if examen.medecin else 'Non assigné',
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
    """Affiche les indicateurs et tâches récentes réservés au laboratoire."""
    if not request.user.is_laboratory:
        if request.user.is_admin_user:
            return redirect('laboratoire:demande_list')
        messages.warning(request, "Accès réservé aux laboratoires.")
        return redirect('dashboard')

    from laboratoire.models import Prelevement
    from laboratoire.permissions import prelevements_visibles

    prelevements = prelevements_visibles(request.user)
    actifs = prelevements.filter(
        statut__in=[
            Prelevement.Statut.A_EFFECTUER,
            Prelevement.Statut.PRELEVE,
            Prelevement.Statut.RECU,
        ],
    )
    return render(request, 'laboratoire/dashboard.html', {
        'stats_prelevements': {
            'total': prelevements.count(),
            'a_effectuer': prelevements.filter(
                statut=Prelevement.Statut.A_EFFECTUER,
            ).count(),
            'a_receptionner': prelevements.filter(
                statut=Prelevement.Statut.PRELEVE,
            ).count(),
            'resultats_a_saisir': prelevements.filter(
                statut=Prelevement.Statut.RECU,
            ).count(),
            'termines': prelevements.filter(
                statut=Prelevement.Statut.TERMINE,
            ).count(),
            'refuses': prelevements.filter(
                statut=Prelevement.Statut.REJETE,
            ).count(),
        },
        'prelevements_recents': actifs.select_related(
            'demande__patient',
        ).order_by('-date_creation')[:8],
    })


@login_required
@require_POST
def lab_update_resultat(request, resultat_id):
    """Permet au laboratoire de mettre à jour un résultat d'analyse legacy."""
    if not request.user.is_laboratory:
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    from laboratoire.permissions import laboratory_team_user_ids

    resultat = get_object_or_404(
        ResultatLaboratoire,
        id=resultat_id,
        laboratoire__in=laboratory_team_user_ids(request.user),
    )
    statut = request.POST.get('statut', resultat.statut)
    if statut not in dict(ResultatLaboratoire.STATUT_CHOICES):
        return JsonResponse({'success': False, 'error': 'Statut invalide'}, status=400)

    # Pour les résultats legacy, pas besoin de permission valider_resultat
    # (comportement différent du nouveau système laboratoire)

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


# ─────────────────────────────────────────────────────────────
# GESTION DES DOSSIERS PATIENTS
# ─────────────────────────────────────────────────────────────
@login_required
def dossiers_patients_list(request):
    """
    Vue principale de gestion de tous les dossiers patients :
    - Recherche avancée multi-critères
    - Filtrage par groupe sanguin, médecin traitant, statut d'allergies
    - Statistiques globales
    - Liens vers vue globale 360°, modification, association médecin, planifier examen
    """
    if not (request.user.is_doctor or request.user.is_admin_user):
        messages.warning(request, "Accès réservé aux praticiens et administrateurs.")
        return redirect('dashboard')

    search_q = request.GET.get('q', '').strip()
    groupe_filter = request.GET.get('groupe', 'ALL')
    medecin_filter = request.GET.get('medecin', 'ALL')
    allergies_filter = request.GET.get('allergies', 'ALL')

    # S'assurer que tous les patients ont un dossier médical
    patients = User.objects.filter(role=User.Role.PATIENT, is_active=True)
    for p in patients:
        get_or_create_dossier(p)

    dossiers_qs = DossierMedical.objects.filter(
        patient__role=User.Role.PATIENT
    ).select_related(
        'patient', 'patient__patient_profile'
    ).prefetch_related(
        'patient__medecins_associes__medecin',
        'examens',
        'resultats_labo'
    ).order_by('-date_mise_a_jour')

    if search_q:
        dossiers_qs = dossiers_qs.filter(
            Q(patient__first_name__icontains=search_q) |
            Q(patient__last_name__icontains=search_q) |
            Q(patient__username__icontains=search_q) |
            Q(patient__email__icontains=search_q) |
            Q(patient__phone__icontains=search_q) |
            Q(numero_dossier__icontains=search_q) |
            Q(patient__patient_profile__numero_securite_sociale__icontains=search_q) |
            Q(allergies__icontains=search_q)
        )

    if groupe_filter != 'ALL':
        dossiers_qs = dossiers_qs.filter(patient__patient_profile__groupe_sanguin=groupe_filter)

    if medecin_filter != 'ALL':
        if medecin_filter == 'NONE':
            dossiers_qs = dossiers_qs.filter(patient__medecins_associes__isnull=True)
        else:
            dossiers_qs = dossiers_qs.filter(patient__medecins_associes__medecin_id=medecin_filter)

    if allergies_filter == 'YES':
        dossiers_qs = dossiers_qs.exclude(allergies='').exclude(allergies__isnull=True)
    elif allergies_filter == 'NO':
        dossiers_qs = dossiers_qs.filter(Q(allergies='') | Q(allergies__isnull=True))

    docteurs = User.objects.filter(role=User.Role.DOCTEUR, is_active=True).order_by('last_name', 'first_name')

    total_dossiers = DossierMedical.objects.filter(patient__role=User.Role.PATIENT).count()
    dossiers_avec_medecin = DossierMedical.objects.filter(patient__role=User.Role.PATIENT, patient__medecins_associes__isnull=False).distinct().count()
    dossiers_sans_medecin = total_dossiers - dossiers_avec_medecin
    dossiers_allergies = DossierMedical.objects.filter(patient__role=User.Role.PATIENT).exclude(allergies='').exclude(allergies__isnull=True).count()
    examens_en_cours = ExamenMedical.objects.filter(statut__in=['PLANIFIE', 'EN_COURS']).count()
    analyses_en_cours = ResultatLaboratoire.objects.filter(statut__in=['EN_ATTENTE', 'EN_COURS']).count()

    stats = {
        'total': total_dossiers,
        'avec_medecin': dossiers_avec_medecin,
        'sans_medecin': dossiers_sans_medecin,
        'allergies': dossiers_allergies,
        'examens_en_cours': examens_en_cours,
        'analyses_en_cours': analyses_en_cours,
    }

    blood_groups = PatientProfile.BLOOD_GROUPS

    return render(request, 'accounts/dossiers_list.html', {
        'dossiers': dossiers_qs,
        'stats': stats,
        'search_q': search_q,
        'groupe_filter': groupe_filter,
        'medecin_filter': medecin_filter,
        'allergies_filter': allergies_filter,
        'docteurs': docteurs,
        'blood_groups': blood_groups,
    })


@login_required
@require_POST
def creer_patient_dossier(request):
    """Création complète d'un patient et de son dossier médical en 1 étape."""
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    form = NouveauPatientDossierForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'success': False, 'errors': form.errors})

    cd = form.cleaned_data
    username = cd['username'].strip()
    if User.objects.filter(username=username).exists():
        return JsonResponse({'success': False, 'errors': {'username': ["Ce nom d'utilisateur est déjà utilisé."]}})

    import random, string
    default_pwd = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
    patient_user = User.objects.create_user(
        username=username,
        email=cd.get('email', ''),
        password=default_pwd,
        first_name=cd.get('first_name', ''),
        last_name=cd.get('last_name', ''),
        phone=cd.get('phone', ''),
        city=cd.get('city', ''),
        address=cd.get('address', ''),
        role=User.Role.PATIENT,
        is_verified=True,
        is_active=True
    )

    pp, _ = PatientProfile.objects.get_or_create(user=patient_user)
    pp.date_naissance = cd.get('date_naissance')
    pp.groupe_sanguin = cd.get('groupe_sanguin') or 'O+'
    pp.numero_securite_sociale = cd.get('numero_securite_sociale', '')
    pp.personne_contact = cd.get('personne_contact', '')
    pp.antecedents = cd.get('antecedents', '')
    pp.save()

    dossier = get_or_create_dossier(patient_user)
    dossier.allergies = cd.get('allergies', '')
    dossier.antecedents_familiaux = cd.get('antecedents_familiaux', '')
    dossier.notes_generales = cd.get('notes_generales', '')
    dossier.save()

    doc = cd.get('medecin_traitant')
    if not doc and request.user.is_doctor:
        doc = request.user
    if doc:
        AssociationMedecinPatient.objects.get_or_create(
            medecin=doc,
            patient=patient_user,
            defaults={'est_medecin_traitant': True, 'notes': 'Association initiale à la création du dossier.'}
        )

    messages.success(request, f"Dossier créé avec succès pour {patient_user.get_full_name()} (#{dossier.numero_dossier}) !")
    return JsonResponse({
        'success': True,
        'message': f"Dossier créé avec succès pour {patient_user.get_full_name()} !",
        'patient_id': patient_user.id
    })


@login_required
def get_patient_dossier_data(request, patient_id):
    """Renvoie les données complètes du patient et dossier en JSON pour pré-remplir la modale."""
    if not (request.user.is_doctor or request.user.is_admin_user or request.user.id == patient_id):
        return JsonResponse({'error': 'Non autorisé'}, status=403)

    patient = get_object_or_404(User, id=patient_id, role=User.Role.PATIENT)
    pp, _ = PatientProfile.objects.get_or_create(user=patient)
    dossier = get_or_create_dossier(patient)

    traitant_assoc = AssociationMedecinPatient.objects.filter(patient=patient, est_medecin_traitant=True).first()
    medecin_id = traitant_assoc.medecin_id if traitant_assoc else ''

    data = {
        'id': patient.id,
        'username': patient.username,
        'first_name': patient.first_name,
        'last_name': patient.last_name,
        'full_name': patient.get_full_name() or patient.username,
        'email': patient.email,
        'phone': patient.phone or '',
        'city': patient.city or '',
        'address': patient.address or '',
        'date_naissance': pp.date_naissance.strftime('%Y-%m-%d') if pp.date_naissance else '',
        'groupe_sanguin': pp.groupe_sanguin or 'O+',
        'numero_securite_sociale': pp.numero_securite_sociale or '',
        'personne_contact': pp.personne_contact or '',
        'antecedents': pp.antecedents or '',
        'numero_dossier': dossier.numero_dossier,
        'allergies': dossier.allergies or '',
        'antecedents_familiaux': dossier.antecedents_familiaux or '',
        'notes_generales': dossier.notes_generales or '',
        'medecin_traitant_id': medecin_id,
    }
    return JsonResponse(data)


@login_required
@require_POST
def edit_patient_dossier(request, patient_id):
    """Modification complète des informations personnelles, du profil et du dossier."""
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    patient = get_object_or_404(User, id=patient_id, role=User.Role.PATIENT)
    pp, _ = PatientProfile.objects.get_or_create(user=patient)
    dossier = get_or_create_dossier(patient)

    patient.first_name = request.POST.get('first_name', patient.first_name)
    patient.last_name = request.POST.get('last_name', patient.last_name)
    patient.email = request.POST.get('email', patient.email)
    patient.phone = request.POST.get('phone', patient.phone)
    patient.city = request.POST.get('city', patient.city)
    patient.address = request.POST.get('address', patient.address)
    patient.save()

    date_naissance_str = request.POST.get('date_naissance')
    if date_naissance_str:
        from datetime import datetime
        try:
            pp.date_naissance = datetime.strptime(date_naissance_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    pp.groupe_sanguin = request.POST.get('groupe_sanguin', pp.groupe_sanguin)
    pp.numero_securite_sociale = request.POST.get('numero_securite_sociale', pp.numero_securite_sociale)
    pp.personne_contact = request.POST.get('personne_contact', pp.personne_contact)
    pp.antecedents = request.POST.get('antecedents', pp.antecedents)
    pp.save()

    dossier.allergies = request.POST.get('allergies', dossier.allergies)
    dossier.antecedents_familiaux = request.POST.get('antecedents_familiaux', dossier.antecedents_familiaux)
    dossier.notes_generales = request.POST.get('notes_generales', dossier.notes_generales)
    dossier.save()

    medecin_id = request.POST.get('medecin_traitant')
    if medecin_id:
        doc = User.objects.filter(id=medecin_id, role=User.Role.DOCTEUR).first()
        if doc:
            AssociationMedecinPatient.objects.filter(patient=patient, est_medecin_traitant=True).exclude(medecin=doc).update(est_medecin_traitant=False)
            assoc, _ = AssociationMedecinPatient.objects.get_or_create(medecin=doc, patient=patient)
            assoc.est_medecin_traitant = True
            assoc.save()

    return JsonResponse({'success': True, 'message': 'Informations du dossier mises à jour avec succès.'})


@login_required
@require_POST
def delete_patient_dossier(request, patient_id):
    """Suppression d'un patient et de son dossier médical."""
    if not (request.user.is_doctor or request.user.is_admin_user):
        messages.error(request, "Action réservée aux praticiens et administrateurs.")
        return redirect('dossiers_patients_list')

    patient = get_object_or_404(User, id=patient_id, role=User.Role.PATIENT)
    nom = patient.get_full_name() or patient.username
    patient.delete()
    messages.success(request, f"Le dossier médical de {nom} a été supprimé.")
    return redirect('dossiers_patients_list')


# ─────────────────────────────────────────────────────────────
# GESTION DES EXAMENS ET PRÉPARATIONS (CRUD COMPLET)
# ─────────────────────────────────────────────────────────────
@login_required
def examens_crud_list(request):
    """
    Page centrale de gestion des examens et de leur préparation :
    - Liste complète de tous les examens avec consignes de préparation
    - Filtres par statut, statut de préparation, type d'examen, médecin, patient
    - Recherche instantanée
    - Actions : Création, Modification, Fiche de préparation patient, Suppression, Validation préparation
    """
    if not (request.user.is_doctor or request.user.is_admin_user):
        messages.warning(request, "Accès réservé aux médecins et administrateurs.")
        return redirect('dashboard')

    search_q = request.GET.get('q', '').strip()
    type_filter = request.GET.get('type', 'ALL')
    statut_filter = request.GET.get('statut', 'ALL')
    prep_filter = request.GET.get('prep', 'ALL')
    patient_filter = request.GET.get('patient', 'ALL')
    medecin_filter = request.GET.get('medecin', 'ALL')

    examens_qs = ExamenMedical.objects.select_related(
        'dossier__patient',
        'dossier__patient__patient_profile',
        'medecin'
    ).order_by('-date_creation', '-id')

    if search_q:
        examens_qs = examens_qs.filter(
            Q(titre__icontains=search_q) |
            Q(dossier__patient__first_name__icontains=search_q) |
            Q(dossier__patient__last_name__icontains=search_q) |
            Q(dossier__patient__username__icontains=search_q) |
            Q(consignes_preparation__icontains=search_q) |
            Q(description__icontains=search_q) |
            Q(lieu_examen__icontains=search_q)
        )

    if type_filter != 'ALL':
        examens_qs = examens_qs.filter(type_examen=type_filter)

    if statut_filter != 'ALL':
        examens_qs = examens_qs.filter(statut=statut_filter)

    if prep_filter != 'ALL':
        examens_qs = examens_qs.filter(statut_preparation=prep_filter)

    if patient_filter != 'ALL':
        examens_qs = examens_qs.filter(dossier__patient_id=patient_filter)

    if medecin_filter != 'ALL':
        examens_qs = examens_qs.filter(medecin_id=medecin_filter)

    total_examens = ExamenMedical.objects.count()
    planifies = ExamenMedical.objects.filter(statut='PLANIFIE').count()
    en_cours = ExamenMedical.objects.filter(statut='EN_COURS').count()
    termines = ExamenMedical.objects.filter(statut='TERMINE').count()
    prep_a_faire = ExamenMedical.objects.filter(statut_preparation__in=['A_FAIRE', 'EN_COURS']).count()
    prep_validees = ExamenMedical.objects.filter(statut_preparation='VALIDEE').count()

    stats = {
        'total': total_examens,
        'planifies': planifies,
        'en_cours': en_cours,
        'termines': termines,
        'prep_a_faire': prep_a_faire,
        'prep_validees': prep_validees,
    }

    types_choices = ExamenMedical.TYPE_CHOICES
    statut_choices = ExamenMedical.STATUT_CHOICES
    prep_choices = ExamenMedical.STATUT_PREPARATION_CHOICES

    patients = User.objects.filter(role=User.Role.PATIENT, is_active=True).order_by('last_name', 'first_name')
    docteurs = User.objects.filter(role=User.Role.DOCTEUR, is_active=True).order_by('last_name', 'first_name')

    context = {
        'examens': examens_qs.prefetch_related('etapes_preparation'),
        'stats': stats,
        'search_q': search_q,
        'type_filter': type_filter,
        'statut_filter': statut_filter,
        'prep_filter': prep_filter,
        'patient_filter': patient_filter,
        'medecin_filter': medecin_filter,
        'types_choices': types_choices,
        'statut_choices': statut_choices,
        'prep_choices': prep_choices,
        'patients': patients,
        'docteurs': docteurs,
        'protocoles': PROTOCOLES_PREPARATION,
    }
    return render(request, 'accounts/examens_list.html', context)


@login_required
@require_POST
def add_examen_global(request):
    """Création d'un examen depuis la vue globale des examens."""
    if not request.user.is_doctor:
        return JsonResponse({'success': False, 'error': 'Action réservée aux médecins. L’administrateur peut uniquement consulter la liste des examens.'}, status=403)

    patient_id = request.POST.get('patient')
    if not patient_id:
        return JsonResponse({'success': False, 'errors': {'patient': ['Veuillez sélectionner un patient.']}})

    patient = get_object_or_404(User, id=patient_id, role=User.Role.PATIENT)
    dossier = get_or_create_dossier(patient)

    medecin_id = request.POST.get('medecin')
    if medecin_id:
        medecin = get_object_or_404(User, id=medecin_id, role=User.Role.DOCTEUR)
    elif request.user.is_doctor:
        medecin = request.user
    else:
        medecin = None

    form = ExamenMedicalForm(request.POST)
    if form.is_valid():
        examen = form.save(commit=False)
        examen.dossier = dossier
        examen.medecin = medecin

        score_seuil = request.POST.get('score_seuil_validation')
        if score_seuil:
            try:
                examen.score_seuil_validation = int(score_seuil)
            except ValueError:
                pass

        examen.save()

        # Application automatique du protocole de préparation choisi (ex: Coloscopie)
        protocole = request.POST.get('protocole_type', '').strip()
        if protocole and protocole in PROTOCOLES_PREPARATION:
            appliquer_protocole_examen(examen, protocole)

        return JsonResponse({
            'success': True,
            'message': f"L'examen '{examen.titre}' a été planifié avec succès pour {patient.get_full_name()}."
        })
    return JsonResponse({'success': False, 'errors': form.errors})


@login_required
def examen_fiche_preparation(request, examen_id):
    """Vue détaillée & imprimable de la fiche de préparation du patient avec checklist interactive."""
    examen = get_object_or_404(
        ExamenMedical.objects.select_related('dossier__patient', 'dossier__patient__patient_profile', 'medecin')
        .prefetch_related('etapes_preparation__validee_par'),
        id=examen_id
    )
    if not (request.user.is_doctor or request.user.is_admin_user or request.user == examen.dossier.patient):
        messages.error(request, "Accès refusé à cette fiche.")
        return redirect('dashboard')

    patient = examen.dossier.patient
    pp = getattr(patient, 'patient_profile', None)
    etapes = examen.etapes_preparation.all().order_by('ordre', 'id')

    return render(request, 'accounts/examen_fiche_preparation.html', {
        'examen': examen,
        'patient': patient,
        'profile': pp,
        'dossier': examen.dossier,
        'etapes': etapes,
        'protocoles': PROTOCOLES_PREPARATION,
    })


@login_required
@require_POST
def valider_preparation_examen(request, examen_id):
    """Action rapide pour marquer la préparation d'un examen comme VALIDEE."""
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    examen = get_object_or_404(ExamenMedical, id=examen_id)
    nouveau_statut = request.POST.get('statut_preparation', 'VALIDEE')
    examen.statut_preparation = nouveau_statut
    examen.save()

    return JsonResponse({
        'success': True,
        'message': f"Préparation validée pour {examen.titre}.",
        'statut_display': examen.get_statut_preparation_display()
    })


@login_required
@require_POST
def appliquer_protocole_a_examen(request, examen_id):
    """Permet au médecin ou à l'administrateur d'appliquer un protocole prédéfini de préparation."""
    if not (request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Action réservée aux médecins et administrateurs.'}, status=403)

    examen = get_object_or_404(ExamenMedical, id=examen_id)
    protocole_key = request.POST.get('protocole_type', '').strip()

    if protocole_key not in PROTOCOLES_PREPARATION:
        return JsonResponse({'success': False, 'error': 'Protocole non reconnu.'}, status=400)

    appliquer_protocole_examen(examen, protocole_key)

    return JsonResponse({
        'success': True,
        'message': f"Protocole « {PROTOCOLES_PREPARATION[protocole_key]['nom']} » appliqué avec succès !",
        'protocole_nom': PROTOCOLES_PREPARATION[protocole_key]['nom']
    })


@login_required
@require_POST
def toggle_etape_preparation(request, etape_id):
    """Permet au patient ou au médecin de cocher/décocher une étape de préparation et recalcule le score."""
    etape = get_object_or_404(
        EtapePreparationExamen.objects.select_related('examen__dossier__patient'),
        id=etape_id
    )
    examen = etape.examen

    # Contrôle d'accès : le patient concerné, son médecin ou l'administrateur
    if not (request.user == examen.dossier.patient or request.user.is_doctor or request.user.is_admin_user):
        return JsonResponse({'success': False, 'error': 'Accès non autorisé.'}, status=403)

    etape.est_validee = not etape.est_validee
    if etape.est_validee:
        etape.date_validation = timezone.now()
        etape.validee_par = request.user
    else:
        etape.date_validation = None
        etape.validee_par = None
    etape.save()

    # Recalcul automatique du score de préparation et mise à jour du statut_preparation
    score = examen.recalculer_score_preparation(save=True)
    validees, total = examen.progression_etapes
    est_pret = examen.est_pret_pour_examen

    if est_pret:
        msg = f"🎉 Bravo ! Score seuil atteint ({score}% / {examen.score_seuil_validation}%). La préparation est validée : le patient est prêt pour l'examen !"
    else:
        msg = f"Étape mise à jour. Score de préparation actuel : {score}% (Seuil requis : {examen.score_seuil_validation}%)."

    return JsonResponse({
        'success': True,
        'etape_id': etape.id,
        'est_validee': etape.est_validee,
        'date_validation': etape.date_validation.strftime('%d/%m/%Y à %H:%M') if etape.date_validation else None,
        'score_preparation': score,
        'score_seuil': examen.score_seuil_validation,
        'statut_preparation': examen.statut_preparation,
        'statut_display': examen.get_statut_preparation_display(),
        'validees_count': validees,
        'total_count': total,
        'est_pret': est_pret,
        'message': msg
    })


@login_required
def get_protocole_details(request, protocole_id):
    """Retourne les détails et étapes d'un protocole en JSON pour le formulaire d'ajout d'examen."""
    proto = PROTOCOLES_PREPARATION.get(protocole_id)
    if not proto:
        return JsonResponse({'success': False, 'error': 'Protocole non trouvé.'}, status=404)
    return JsonResponse({'success': True, 'protocole': proto})


# ─────────────────────────────────────────────────────────────
# API — IA & ML MÉDICAL
# ─────────────────────────────────────────────────────────────
@login_required
def api_dossier_analyse_ia(request, patient_id):
    """API endpoint retournant l'analyse IA complète du dossier médical en JSON."""
    if not (request.user.is_doctor or request.user.is_admin_user or request.user.id == patient_id):
        return JsonResponse({'error': 'Non autorisé'}, status=403)
    patient = get_object_or_404(User, id=patient_id, role=User.Role.PATIENT)
    dossier = get_or_create_dossier(patient)
    from .medical_ai import analyser_dossier_ia
    data = analyser_dossier_ia(patient, dossier)
    return JsonResponse({'success': True, 'data': data})


@login_required
def api_dossier_risques_ml(request, patient_id):
    """API endpoint retournant la détection des risques ML et profils similaires en JSON."""
    if not (request.user.is_doctor or request.user.is_admin_user or request.user.id == patient_id):
        return JsonResponse({'error': 'Non autorisé'}, status=403)
    patient = get_object_or_404(User, id=patient_id, role=User.Role.PATIENT)
    dossier = get_or_create_dossier(patient)
    from .medical_ai import analyser_dossier_ia
    from .medical_ml import evaluer_risques_machine_learning
    ia_data = analyser_dossier_ia(patient, dossier)
    ml_data = evaluer_risques_machine_learning(patient, dossier, ia_data)
    return JsonResponse({'success': True, 'data': ml_data})



@login_required
def api_examen_ia_suggestion(request, examen_id):
    """API endpoint retournant la suggestion IA de protocole pour un examen médical."""
    examen = get_object_or_404(ExamenMedical, id=examen_id)

    # Access control: doctor, admin, or the patient themselves
    patient = examen.dossier.patient if examen.dossier else None
    is_owner = patient and request.user.id == patient.id
    if not (request.user.is_doctor or request.user.is_admin_user or is_owner):
        return JsonResponse({'success': False, 'error': 'Non autorisé'}, status=403)

    dossier = examen.dossier if examen.dossier else None
    from .ml.ai_examen import analyser_examen_ia
    ia_data = analyser_examen_ia(examen, dossier)
    return JsonResponse({'success': True, 'ia': ia_data})

