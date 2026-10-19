from datetime import datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from . import services
from .forms import (
    AnnulationForm, ClotureForm, CreneauForm, GenerationCreneauxForm, ReservationForm, medecins_qs,
)
from .models import STATUTS_ACTIFS, Creneau, RendezVous
from .permissions import (
    creneaux_gestion_requise, peut_annuler, peut_cloturer, peut_confirmer, peut_gerer_creneaux,
    peut_voir_rdv, rdv_acces_requis,
)
from .services import RendezVousError

User = get_user_model()
Statut = RendezVous.Statut
NOMS_JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

PERIODES = [
    ("a_venir", "À venir"),
    ("aujourdhui", "Aujourd'hui"),
    ("semaine", "Cette semaine"),
    ("passes", "Passés"),
    ("tous", "Toutes les dates"),
]
ETATS_CRENEAU = [("", "Tous"), ("libre", "Libres"), ("reserve", "Réservés"), ("bloque", "Bloqués")]


# --------------------------------------------------------------------------
# Utilitaires
# --------------------------------------------------------------------------
def _paginer(request, queryset, par_page=15):
    page = Paginator(queryset, par_page).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return page, params.urlencode()


def _bornes_jour(jour):
    debut = timezone.make_aware(datetime.combine(jour, time.min))
    return debut, debut + timedelta(days=1)


def _lundi(jour):
    return jour - timedelta(days=jour.weekday())


def _semaine_demandee(request):
    jour = parse_date(request.GET.get("semaine", "") or "") or timezone.localdate()
    return _lundi(jour)


def _medecin_demande(request):
    """Le médecin sélectionné : soi-même pour un docteur, sinon le paramètre ?medecin=."""
    if request.user.is_doctor:
        return request.user
    pk = request.GET.get("medecin", "")
    if pk.isdigit():
        return medecins_qs().filter(pk=int(pk)).first()
    return None


def _contexte_commun(request, active):
    return {
        "active": active,
        "can_manage_slots": peut_gerer_creneaux(request.user),
        "nb_en_attente": RendezVous.objects.visibles_par(request.user)
        .filter(statut=Statut.EN_ATTENTE).a_venir().count(),
    }


def _redirect_suivant(request, defaut):
    suivant = request.POST.get("next") or request.GET.get("next")
    if suivant and suivant.startswith("/") and not suivant.startswith("//"):
        return redirect(suivant)
    return redirect(defaut)


# --------------------------------------------------------------------------
# Liste des rendez-vous (avec filtres)
# --------------------------------------------------------------------------
@rdv_acces_requis
def rdv_list(request):
    user = request.user
    base = RendezVous.objects.visibles_par(user).select_related(
        "creneau", "patient", "medecin", "medecin__doctor_profile"
    )
    maintenant = timezone.now()
    aujourd_hui = timezone.localdate()

    q = request.GET.get("q", "").strip()
    statut = request.GET.get("statut", "")
    periode = request.GET.get("periode", "a_venir")
    medecin = _medecin_demande(request) if not user.is_doctor else None
    date_du = parse_date(request.GET.get("du", "") or "")
    date_au = parse_date(request.GET.get("au", "") or "")

    qs = base
    if q:
        qs = qs.filter(
            Q(patient__first_name__icontains=q) | Q(patient__last_name__icontains=q)
            | Q(patient__username__icontains=q) | Q(medecin__first_name__icontains=q)
            | Q(medecin__last_name__icontains=q) | Q(motif__icontains=q)
        )
    if statut in Statut.values:
        qs = qs.filter(statut=statut)
    if medecin:
        qs = qs.filter(medecin=medecin)
    if periode == "a_venir":
        qs = qs.filter(creneau__debut__gte=maintenant)
    elif periode == "aujourdhui":
        d, f = _bornes_jour(aujourd_hui)
        qs = qs.filter(creneau__debut__gte=d, creneau__debut__lt=f)
    elif periode == "semaine":
        d, _ = _bornes_jour(_lundi(aujourd_hui))
        qs = qs.filter(creneau__debut__gte=d, creneau__debut__lt=d + timedelta(days=7))
    elif periode == "passes":
        qs = qs.filter(creneau__debut__lt=maintenant)
    if date_du:
        qs = qs.filter(creneau__debut__gte=_bornes_jour(date_du)[0])
    if date_au:
        qs = qs.filter(creneau__debut__lt=_bornes_jour(date_au)[1])

    qs = qs.order_by("-creneau__debut" if periode == "passes" else "creneau__debut")
    page_obj, querystring = _paginer(request, qs)

    d, f = _bornes_jour(aujourd_hui)
    stats = base.aggregate(
        a_venir=Count("pk", filter=Q(creneau__debut__gte=maintenant, statut__in=STATUTS_ACTIFS)),
        aujourdhui=Count("pk", filter=Q(creneau__debut__gte=d, creneau__debut__lt=f, statut__in=STATUTS_ACTIFS)),
        en_attente=Count("pk", filter=Q(creneau__debut__gte=maintenant, statut=Statut.EN_ATTENTE)),
        annules=Count("pk", filter=Q(statut=Statut.ANNULE)),
    )

    return render(request, "rendezvous/rdv_list.html", {
        **_contexte_commun(request, "liste"),
        "page_obj": page_obj,
        "querystring": querystring,
        "stats": stats,
        "q": q, "statut_sel": statut, "periode_sel": periode,
        "medecin_sel": medecin.pk if medecin else "",
        "du": request.GET.get("du", ""), "au": request.GET.get("au", ""),
        "statut_choices": Statut.choices,
        "periodes": PERIODES,
        "medecins": medecins_qs() if not user.is_doctor else None,
    })


# --------------------------------------------------------------------------
# Calendrier hebdomadaire
# --------------------------------------------------------------------------
@rdv_acces_requis
def calendrier(request):
    user = request.user
    lundi = _semaine_demandee(request)
    debut_sem, _ = _bornes_jour(lundi)
    fin_sem = debut_sem + timedelta(days=7)
    medecin = _medecin_demande(request)
    statut = request.GET.get("statut", "")
    etat = request.GET.get("etat", "")
    jours = [{"date": lundi + timedelta(days=i), "nom": NOMS_JOURS[i], "items": []} for i in range(7)]

    # Vue « créneaux » pour un médecin précis (docteur connecté ou admin ayant choisi un médecin),
    # vue « rendez-vous » sinon (patient, ou admin sur tous les médecins).
    mode_creneaux = medecin is not None and peut_gerer_creneaux(user)

    if mode_creneaux:
        creneaux = (
            Creneau.objects.du_medecin(medecin)
            .filter(debut__gte=debut_sem, debut__lt=fin_sem)
            .prefetch_related(Prefetch(
                "rendez_vous",
                queryset=RendezVous.objects.select_related("patient").order_by("-date_creation"),
            ))
        )
        for c in creneaux:
            rdv = c.rdv_actif
            if etat and c.etat != etat:
                continue
            if statut and (rdv is None or rdv.statut != statut):
                continue
            jour = timezone.localtime(c.debut).date()
            jours[(jour - lundi).days]["items"].append({"creneau": c, "rdv": rdv, "etat": c.etat})
    else:
        rdvs = (
            RendezVous.objects.visibles_par(user)
            .filter(creneau__debut__gte=debut_sem, creneau__debut__lt=fin_sem)
            .select_related("creneau", "patient", "medecin")
            .order_by("creneau__debut")
        )
        if medecin:
            rdvs = rdvs.filter(medecin=medecin)
        if statut in Statut.values:
            rdvs = rdvs.filter(statut=statut)
        else:
            rdvs = rdvs.exclude(statut=Statut.ANNULE)
        for r in rdvs:
            jour = timezone.localtime(r.creneau.debut).date()
            jours[(jour - lundi).days]["items"].append({"creneau": r.creneau, "rdv": r, "etat": "reserve"})

    aujourd_hui = timezone.localdate()
    for j in jours:
        j["est_aujourdhui"] = j["date"] == aujourd_hui
        j["est_passe"] = j["date"] < aujourd_hui

    return render(request, "rendezvous/calendrier.html", {
        **_contexte_commun(request, "calendrier"),
        "jours": jours,
        "lundi": lundi,
        "dimanche": lundi + timedelta(days=6),
        "semaine_prec": lundi - timedelta(days=7),
        "semaine_suiv": lundi + timedelta(days=7),
        "aujourdhui": aujourd_hui,
        "mode_creneaux": mode_creneaux,
        "medecin": medecin,
        "medecins": medecins_qs() if not user.is_doctor else None,
        "statut_sel": statut, "etat_sel": etat,
        "statut_choices": Statut.choices,
        "etats": ETATS_CRENEAU,
        "nb_items": sum(len(j["items"]) for j in jours),
    })


# --------------------------------------------------------------------------
# Réservation
# --------------------------------------------------------------------------
@rdv_acces_requis
def reserver(request):
    """Étape 1 : choisir un médecin puis un créneau libre de la semaine."""
    user = request.user
    lundi = max(_semaine_demandee(request), _lundi(timezone.localdate()))
    debut_sem, _ = _bornes_jour(lundi)
    specialite = request.GET.get("specialite", "").strip()

    medecins = medecins_qs().select_related("doctor_profile")
    specialites = sorted({
        m.doctor_profile.specialite for m in medecins if hasattr(m, "doctor_profile") and m.doctor_profile.specialite
    })
    if specialite:
        medecins = medecins.filter(doctor_profile__specialite=specialite)
    medecin = _medecin_demande(request)
    if medecin is None and not user.is_doctor and medecins.count() == 1:
        medecin = medecins.first()

    jours = []
    if medecin:
        libres = Creneau.objects.du_medecin(medecin).disponibles().filter(
            debut__gte=debut_sem, debut__lt=debut_sem + timedelta(days=7)
        )
        par_jour = {}
        for c in libres:
            par_jour.setdefault(timezone.localtime(c.debut).date(), []).append(c)
        jours = [
            {"date": lundi + timedelta(days=i), "nom": NOMS_JOURS[i],
             "creneaux": par_jour.get(lundi + timedelta(days=i), [])}
            for i in range(7)
        ]
    prochain = None
    if medecin and not any(j["creneaux"] for j in jours):
        prochain = Creneau.objects.du_medecin(medecin).disponibles().filter(
            debut__gte=debut_sem + timedelta(days=7)
        ).first()

    return render(request, "rendezvous/reserver.html", {
        **_contexte_commun(request, "reserver"),
        "medecins": medecins,
        "medecin": medecin,
        "specialites": specialites,
        "specialite_sel": specialite,
        "jours": jours,
        "lundi": lundi,
        "dimanche": lundi + timedelta(days=6),
        "semaine_prec": lundi - timedelta(days=7) if lundi > _lundi(timezone.localdate()) else None,
        "semaine_suiv": lundi + timedelta(days=7),
        "prochain": prochain,
        "aucun_creneau": bool(medecin) and prochain is None and not any(j["creneaux"] for j in jours),
    })


@rdv_acces_requis
def reserver_creneau(request, pk):
    """Étape 2 : confirmer la réservation d'un créneau précis (motif, patient)."""
    creneau = get_object_or_404(Creneau.objects.select_related("medecin", "medecin__doctor_profile"), pk=pk)
    if request.user.is_doctor and creneau.medecin_id != request.user.pk:
        raise Http404
    if not creneau.est_disponible:
        messages.error(request, "Ce créneau n'est plus disponible, merci d'en choisir un autre.")
        return redirect(f"{reverse("rendezvous:reserver")}?medecin={creneau.medecin_id}&semaine={timezone.localtime(creneau.debut):%Y-%m-%d}")

    initial = {}
    if request.GET.get("patient", "").isdigit():
        initial["patient"] = int(request.GET["patient"])
    form = ReservationForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        patient = request.user if request.user.is_patient else form.cleaned_data["patient"]
        try:
            rdv = services.reserver(
                creneau=creneau, patient=patient, motif=form.cleaned_data["motif"], par=request.user
            )
        except RendezVousError as e:
            messages.error(request, str(e))
        else:
            if rdv.statut == Statut.CONFIRME:
                messages.success(request, "Rendez-vous enregistré et confirmé.")
            else:
                messages.success(request, "Demande de rendez-vous envoyée : le médecin doit la confirmer.")
            return redirect("rendezvous:rdv_detail", pk=rdv.pk)

    return render(request, "rendezvous/reserver_confirmer.html", {
        **_contexte_commun(request, "reserver"),
        "creneau": creneau,
        "form": form,
    })


# --------------------------------------------------------------------------
# Détail et actions sur un rendez-vous
# --------------------------------------------------------------------------
def _get_rdv_visible(request, pk):
    rdv = get_object_or_404(
        RendezVous.objects.select_related(
            "creneau", "patient", "patient__patient_profile", "medecin", "medecin__doctor_profile",
            "cree_par", "annule_par",
        ),
        pk=pk,
    )
    if not peut_voir_rdv(request.user, rdv):
        raise Http404
    return rdv


@rdv_acces_requis
def rdv_detail(request, pk):
    rdv = _get_rdv_visible(request, pk)
    user = request.user
    autres = (
        RendezVous.objects.visibles_par(user)
        .filter(patient=rdv.patient).exclude(pk=rdv.pk)
        .select_related("creneau", "medecin").order_by("-creneau__debut")[:5]
    )
    return render(request, "rendezvous/rdv_detail.html", {
        **_contexte_commun(request, "liste"),
        "rdv": rdv,
        "autres_rdv": autres,
        "peut_confirmer": peut_confirmer(user, rdv) and not rdv.est_passe,
        "peut_annuler": peut_annuler(user, rdv),
        "peut_cloturer": peut_cloturer(user, rdv),
        "annulation_form": AnnulationForm(),
        "cloture_form": ClotureForm(),
        "delai_annulation": services.delai_annulation_patient(),
    })


@require_POST
@rdv_acces_requis
def rdv_confirmer(request, pk):
    rdv = _get_rdv_visible(request, pk)
    try:
        services.confirmer(rdv, par=request.user)
        messages.success(request, "Rendez-vous confirmé.")
    except RendezVousError as e:
        messages.error(request, str(e))
    return _redirect_suivant(request, reverse("rendezvous:rdv_detail", args=[rdv.pk]))


@require_POST
@rdv_acces_requis
def rdv_annuler(request, pk):
    rdv = _get_rdv_visible(request, pk)
    form = AnnulationForm(request.POST)
    form.is_valid()
    try:
        services.annuler(rdv, par=request.user, motif=form.cleaned_data.get("motif_annulation", ""))
        messages.success(request, "Rendez-vous annulé : le créneau est de nouveau disponible.")
    except RendezVousError as e:
        messages.error(request, str(e))
    return _redirect_suivant(request, reverse("rendezvous:rdv_detail", args=[rdv.pk]))


@require_POST
@rdv_acces_requis
def rdv_cloturer(request, pk):
    rdv = _get_rdv_visible(request, pk)
    form = ClotureForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choix invalide.")
        return redirect(reverse("rendezvous:rdv_detail", args=[rdv.pk]))
    try:
        services.cloturer(rdv, par=request.user, statut=form.cleaned_data["statut"], notes=form.cleaned_data["notes"])
        messages.success(request, "Rendez-vous clôturé.")
    except RendezVousError as e:
        messages.error(request, str(e))
    return _redirect_suivant(request, reverse("rendezvous:rdv_detail", args=[rdv.pk]))


# --------------------------------------------------------------------------
# Gestion des créneaux (médecin / admin)
# --------------------------------------------------------------------------
@creneaux_gestion_requise
def creneau_list(request):
    user = request.user
    medecin = _medecin_demande(request)
    etat = request.GET.get("etat", "")
    date_du = parse_date(request.GET.get("du", "") or "") or timezone.localdate()
    date_au = parse_date(request.GET.get("au", "") or "")

    qs = Creneau.objects.select_related("medecin").prefetch_related(
        Prefetch("rendez_vous", queryset=RendezVous.objects.select_related("patient"))
    ).filter(debut__gte=_bornes_jour(date_du)[0])
    if medecin:
        qs = qs.filter(medecin=medecin)
    if date_au:
        qs = qs.filter(debut__lt=_bornes_jour(date_au)[1])
    if etat == "libre":
        qs = qs.filter(est_bloque=False).exclude(rendez_vous__statut__in=STATUTS_ACTIFS)
    elif etat == "reserve":
        qs = qs.avec_rdv_actif()
    elif etat == "bloque":
        qs = qs.filter(est_bloque=True)

    page_obj, querystring = _paginer(request, qs.order_by("debut"), par_page=25)
    return render(request, "rendezvous/creneau_list.html", {
        **_contexte_commun(request, "creneaux"),
        "page_obj": page_obj,
        "querystring": querystring,
        "medecins": medecins_qs() if not user.is_doctor else None,
        "medecin_sel": medecin.pk if medecin and not user.is_doctor else "",
        "etat_sel": etat, "etats": ETATS_CRENEAU,
        "du": date_du.isoformat(), "au": request.GET.get("au", ""),
        "nb_libres": Creneau.objects.disponibles().filter(**({"medecin": medecin} if medecin else {})).count(),
    })


@creneaux_gestion_requise
def creneau_ajouter(request):
    form = CreneauForm(request.POST or None, user=request.user)
    if request.method == "POST":
        try:
            valide = form.is_valid()
        except ValidationError as e:  # chevauchement détecté par Creneau.clean()
            form.add_error(None, e)
            valide = False
        if valide:
            form.creneau.save()
            messages.success(request, f"Créneau ajouté : {form.creneau}.")
            return redirect("rendezvous:creneau_list")
    return render(request, "rendezvous/creneau_form.html", {
        **_contexte_commun(request, "creneaux"),
        "form": form, "titre": "Ajouter un créneau", "mode": "unique",
    })


@creneaux_gestion_requise
def creneau_generer(request):
    form = GenerationCreneauxForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        medecin = request.user if request.user.is_doctor else d["medecin"]
        try:
            crees, ignores = services.generer_creneaux(
                medecin=medecin, date_debut=d["date_debut"], date_fin=d["date_fin"], jours=d["jours"],
                heure_debut=d["heure_debut"], heure_fin=d["heure_fin"], duree_minutes=d["duree_minutes"],
                pause_debut=d.get("pause_debut"), pause_fin=d.get("pause_fin"),
            )
        except RendezVousError as e:
            form.add_error(None, str(e))
        else:
            msg = f"{crees} créneau(x) créé(s)."
            if ignores:
                msg += f" {ignores} ignoré(s) (déjà passés ou en conflit avec un créneau existant)."
            messages.success(request, msg)
            url = reverse("rendezvous:creneau_list")
            if not request.user.is_doctor:
                url += f"?medecin={medecin.pk}"
            return redirect(url)
    return render(request, "rendezvous/creneau_form.html", {
        **_contexte_commun(request, "creneaux"),
        "form": form, "titre": "Générer un planning de créneaux", "mode": "generation",
    })


@require_POST
@creneaux_gestion_requise
def creneau_bloquer(request, pk):
    creneau = get_object_or_404(Creneau, pk=pk)
    try:
        services.basculer_blocage(creneau, par=request.user)
        messages.success(request, "Créneau bloqué." if creneau.est_bloque else "Créneau rouvert à la réservation.")
    except RendezVousError as e:
        messages.error(request, str(e))
    return _redirect_suivant(request, "rendezvous:creneau_list")


@require_POST
@creneaux_gestion_requise
def creneau_supprimer(request, pk):
    creneau = get_object_or_404(Creneau, pk=pk)
    try:
        services.supprimer_creneau(creneau, par=request.user)
        messages.success(request, "Créneau supprimé.")
    except RendezVousError as e:
        messages.error(request, str(e))
    return _redirect_suivant(request, "rendezvous:creneau_list")


# --------------------------------------------------------------------------
# API JSON (session) — créneaux libres d'un médecin pour une date
# --------------------------------------------------------------------------
@require_GET
@rdv_acces_requis
def api_creneaux_disponibles(request):
    medecin_id = request.GET.get("medecin", "")
    jour = parse_date(request.GET.get("date", "") or "")
    if not medecin_id.isdigit() or jour is None:
        return JsonResponse({"erreur": "Paramètres attendus : medecin=<id>&date=AAAA-MM-JJ"}, status=400)
    d, f = _bornes_jour(jour)
    creneaux = Creneau.objects.disponibles().filter(medecin_id=int(medecin_id), debut__gte=d, debut__lt=f)
    return JsonResponse({
        "medecin": int(medecin_id),
        "date": jour.isoformat(),
        "creneaux": [
            {"id": c.pk, "debut": timezone.localtime(c.debut).isoformat(),
             "fin": timezone.localtime(c.fin).isoformat(), "duree_minutes": c.duree_minutes}
            for c in creneaux
        ],
    })
