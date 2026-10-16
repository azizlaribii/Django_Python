from django.contrib import admin
from django.utils.html import format_html
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    User,
    DoctorProfile,
    LaboratoryProfile,
    PatientProfile,
    Docteur,
    Laboratoire,
    Patient,
)

# Configuration de l'entête Django Admin
admin.site.site_header = "SantéConnect - Espace Administrateur"
admin.site.site_title = "SantéConnect Admin"
admin.site.index_title = "Gestion globale des comptes : Docteurs, Laboratoires, Patients"


class DoctorProfileInline(admin.StackedInline):
    model = DoctorProfile
    can_delete = False
    verbose_name = "Informations Professionnelles Docteur"
    verbose_name_plural = "Informations Professionnelles Docteur"
    extra = 0


class LaboratoryProfileInline(admin.StackedInline):
    model = LaboratoryProfile
    can_delete = False
    verbose_name = "Informations de l'Établissement Laboratoire"
    verbose_name_plural = "Informations de l'Établissement Laboratoire"
    extra = 0


class PatientProfileInline(admin.StackedInline):
    model = PatientProfile
    can_delete = False
    verbose_name = "Dossier & Profil Médical Patient"
    verbose_name_plural = "Dossier & Profil Médical Patient"
    extra = 0


@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    list_display = (
        'username',
        'get_full_name_display',
        'email',
        'role_badge',
        'phone',
        'city',
        'verification_badge',
        'is_active',
        'date_joined',
    )
    list_display_links = ('username', 'get_full_name_display')
    list_filter = ('role', 'is_verified', 'is_active', 'is_staff', 'date_joined')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'phone', 'city')
    ordering = ('-date_joined',)

    actions = ['certifier_comptes', 'retirer_certification', 'activer_comptes', 'desactiver_comptes']


    fieldsets = (
        ("Identifiants & Connexion", {
            'fields': ('username', 'password')
        }),
        ("Rôle & Statut Professionnel", {
            'fields': ('role', 'is_verified'),
            'description': "Sélectionnez le rôle du compte. Les formulaires spécifiques s'afficheront en bas."
        }),
        ("Informations Personnelles / Coordonnées", {
            'fields': ('first_name', 'last_name', 'email', 'phone', 'address', 'city')
        }),
        ("Permissions & Droits", {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'classes': ('collapse',),
        }),
        ("Dates Clés", {
            'fields': ('last_login', 'date_joined'),
            'classes': ('collapse',),
        }),
    )

    def get_inline_instances(self, request, obj=None):
        if not obj:
            return []
        inlines = []
        if obj.role == User.Role.DOCTEUR:
            inlines.append(DoctorProfileInline(self.model, self.admin_site))
        elif obj.role == User.Role.LABORATOIRE:
            inlines.append(LaboratoryProfileInline(self.model, self.admin_site))
        elif obj.role == User.Role.PATIENT:
            inlines.append(PatientProfileInline(self.model, self.admin_site))
        return inlines

    @admin.display(description="Nom Complet")
    def get_full_name_display(self, obj):
        name = obj.get_full_name()
        return name if name else "-"

    @admin.display(description="Rôle")
    def role_badge(self, obj):
        colors = {
            User.Role.ADMIN: ('#ef4444', '#fee2e2', 'Administrateur'),
            User.Role.DOCTEUR: ('#059669', '#d1fae5', '🩺 Docteur'),
            User.Role.LABORATOIRE: ('#7c3aed', '#ede9fe', '🔬 Laboratoire'),
            User.Role.PATIENT: ('#0284c7', '#e0f2fe', '👤 Patient'),
        }
        fg, bg, label = colors.get(obj.role, ('#374151', '#f3f4f6', obj.get_role_display()))
        return format_html(
            '<span style="background-color: {}; color: {}; font-weight: 600; padding: 4px 10px; border-radius: 9999px; font-size: 0.8rem; display: inline-block;">{}</span>',
            bg, fg, label
        )

    @admin.display(description="Certification")
    def verification_badge(self, obj):
        if obj.is_verified:
            return format_html(
                '<span style="color: #059669; font-weight: bold; background: #d1fae5; padding: 3px 8px; border-radius: 6px;">✓ Certifié</span>'
            )
        return format_html(
            '<span style="color: #d97706; background: #fef3c7; padding: 3px 8px; border-radius: 6px;">⏳ En attente</span>'
        )

    @admin.action(description="✓ Certifier et valider les comptes sélectionnés")
    def certifier_comptes(self, request, queryset):
        count = queryset.update(is_verified=True)
        self.message_user(request, f"{count} compte(s) certifié(s) avec succès.")

    @admin.action(description="✗ Révoquer la certification des comptes sélectionnés")
    def retirer_certification(self, request, queryset):
        count = queryset.update(is_verified=False)
        self.message_user(request, f"Certification révoquée pour {count} compte(s).")

    @admin.action(description="Activer l'accès (Compte actif)")
    def activer_comptes(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"{count} compte(s) activé(s).")

    @admin.action(description="Désactiver l'accès (Compte suspendu)")
    def desactiver_comptes(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} compte(s) désactivé(s).")


@admin.register(Docteur)
class DocteurAdmin(admin.ModelAdmin):
    list_display = (
        'username',
        'get_full_name_display',
        'get_specialite',
        'get_numero_ordre',
        'phone',
        'city',
        'is_verified',
        'is_active',
    )
    list_filter = ('is_verified', 'is_active', 'doctor_profile__specialite', 'city')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'phone', 'doctor_profile__specialite', 'doctor_profile__numero_ordre')
    inlines = [DoctorProfileInline]

    fieldsets = (
        ("Compte du Médecin", {
            'fields': ('username', 'password', 'first_name', 'last_name', 'email', 'phone', 'address', 'city')
        }),
        ("Statut & Validation par l'Admin", {
            'fields': ('is_verified', 'is_active'),
            'description': "Activez la certification pour accorder la validité au médecin sur la plateforme."
        }),
    )

    def save_model(self, request, obj, form, change):
        obj.role = User.Role.DOCTEUR
        super().save_model(request, obj, form, change)

    @admin.display(description="Nom du Docteur")
    def get_full_name_display(self, obj):
        name = obj.get_full_name()
        return f"Dr. {name}" if name else f"Dr. {obj.username}"

    @admin.display(description="Spécialité")
    def get_specialite(self, obj):
        return getattr(obj.doctor_profile, 'specialite', '-')

    @admin.display(description="N° Ordre")
    def get_numero_ordre(self, obj):
        return getattr(obj.doctor_profile, 'numero_ordre', '-') or '-'


@admin.register(Laboratoire)
class LaboratoireAdmin(admin.ModelAdmin):
    list_display = (
        'username',
        'get_nom_laboratoire',
        'get_numero_agrement',
        'get_responsable',
        'phone',
        'city',
        'is_verified',
        'is_active',
    )
    list_filter = ('is_verified', 'is_active', 'city')
    search_fields = ('username', 'email', 'phone', 'lab_profile__nom_laboratoire', 'lab_profile__numero_agrement', 'lab_profile__responsable')
    inlines = [LaboratoryProfileInline]

    fieldsets = (
        ("Compte du Laboratoire", {
            'fields': ('username', 'password', 'first_name', 'last_name', 'email', 'phone', 'address', 'city')
        }),
        ("Agrément & Statut Admin", {
            'fields': ('is_verified', 'is_active'),
            'description': "Validation requise après vérification du numéro d'agrément officiel."
        }),
    )

    def save_model(self, request, obj, form, change):
        obj.role = User.Role.LABORATOIRE
        super().save_model(request, obj, form, change)

    @admin.display(description="Nom du Laboratoire")
    def get_nom_laboratoire(self, obj):
        return getattr(obj.lab_profile, 'nom_laboratoire', '-')

    @admin.display(description="N° Agrément")
    def get_numero_agrement(self, obj):
        return getattr(obj.lab_profile, 'numero_agrement', '-') or '-'

    @admin.display(description="Biologiste / Resp.")
    def get_responsable(self, obj):
        return getattr(obj.lab_profile, 'responsable', '-') or '-'


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = (
        'username',
        'get_full_name_display',
        'get_groupe_sanguin',
        'get_numero_securite_sociale',
        'phone',
        'city',
        'is_active',
        'date_joined',
    )
    list_filter = ('patient_profile__groupe_sanguin', 'is_active', 'city')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'phone', 'patient_profile__numero_securite_sociale')
    inlines = [PatientProfileInline]

    fieldsets = (
        ("Compte du Patient", {
            'fields': ('username', 'password', 'first_name', 'last_name', 'email', 'phone', 'address', 'city')
        }),
        ("Statut d'accès", {
            'fields': ('is_active',),
        }),
    )

    def save_model(self, request, obj, form, change):
        obj.role = User.Role.PATIENT
        super().save_model(request, obj, form, change)

    @admin.display(description="Nom du Patient")
    def get_full_name_display(self, obj):
        name = obj.get_full_name()
        return name if name else obj.username

    @admin.display(description="Groupe Sanguin")
    def get_groupe_sanguin(self, obj):
        grp = getattr(obj.patient_profile, 'groupe_sanguin', '-')
        return format_html(
            '<span style="background: #fee2e2; color: #dc2626; font-weight: bold; padding: 2px 8px; border-radius: 4px;">{}</span>',
            grp
        )

    @admin.display(description="N° Sécurité / CIN")
    def get_numero_securite_sociale(self, obj):
        return getattr(obj.patient_profile, 'numero_securite_sociale', '-') or '-'
