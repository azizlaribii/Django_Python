from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from .forms import CategorieForm, MouvementForm, ProduitForm
from .models import Categorie, MouvementStock, Produit, seuil_peremption_jours
from .permissions import peut_gerer_stock, stock_consultation_requise, stock_gestion_requise
from .services import StockError, enregistrer_mouvement, get_alertes

Type = MouvementStock.Type
Motif = MouvementStock.Motif

STATUT_CHOICES = [
    ("", "Tous les statuts"),
    ("rupture", "En rupture"),
    ("faible", "Stock faible"),
    ("expire", "Périmés"),
    ("bientot", "Péremption proche"),
    ("normal", "Disponibles"),
]
STATUT_FILTRES = {
    "rupture": "en_rupture", "faible": "stock_faible", "expire": "expires",
    "bientot": "bientot_perimes", "normal": "normaux",
}


def _paginer(request, queryset, par_page=15):
    page = Paginator(queryset, par_page).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return page, params.urlencode()


# --------------------------------------------------------------------------
# Tableau de bord
# --------------------------------------------------------------------------
@stock_consultation_requise
def dashboard(request):
    alertes = get_alertes()
    blocs = [
        {"cle": "rupture", "titre": "Produits en rupture", "icone": "⛔", "mode": "stock",
         "s": "produit en rupture", "p": "produits en rupture"},
        {"cle": "faible", "titre": "Stock faible", "icone": "⚠️", "mode": "stock",
         "s": "produit à stock faible", "p": "produits à stock faible"},
        {"cle": "expire", "titre": "Produits périmés", "icone": "☠️", "mode": "date",
         "s": "produit périmé", "p": "produits périmés"},
        {"cle": "bientot", "titre": "Péremption proche", "icone": "⏳", "mode": "date",
         "s": "produit proche de la péremption", "p": "produits proches de la péremption"},
    ]
    for bloc in blocs:
        qs = alertes[bloc["cle"]]
        bloc["nb"] = qs.count()
        bloc["produits"] = list(qs.order_by("date_peremption", "nom")[:8]
                                if bloc["mode"] == "date" else qs.order_by("quantite", "nom")[:8])
    total_alertes = sum(b["nb"] for b in blocs)
    parties = [f'{b["nb"]} {b["s"] if b["nb"] == 1 else b["p"]}' for b in blocs if b["nb"]]
    resume = (f"{total_alertes} alerte{'s' if total_alertes > 1 else ''} de stock : " + ", ".join(parties) + "."
              if total_alertes else "Aucune alerte de stock.")
    # Texte lu à voix haute (Web Speech API) : résumé + noms des produits concernés
    lecture = resume + " " + " ".join(
        f'{b["titre"]} : ' + ", ".join(p.nom for p in b["produits"]) + "."
        for b in blocs if b["nb"]
    )
    return render(request, "stock/dashboard.html", {
        "blocs": blocs, "total_alertes": total_alertes, "resume": resume, "lecture": lecture,
        "nb_produits": Produit.objects.actifs().count(),
        "derniers_mouvements": MouvementStock.objects.select_related("produit", "utilisateur")[:8],
        "seuil_jours": seuil_peremption_jours(),
        "can_manage": peut_gerer_stock(request.user),
    })


# --------------------------------------------------------------------------
# Produits
# --------------------------------------------------------------------------
@stock_consultation_requise
def produit_list(request):
    qs = Produit.objects.actifs().select_related("categorie")
    q = request.GET.get("q", "").strip()
    categorie = request.GET.get("categorie", "")
    statut = request.GET.get("statut", "")

    if q:
        qs = qs.filter(Q(nom__icontains=q) | Q(reference__icontains=q) | Q(fournisseur__icontains=q))
    if categorie.isdigit():
        qs = qs.filter(categorie_id=int(categorie))
    if statut in STATUT_FILTRES:
        qs = getattr(qs, STATUT_FILTRES[statut])()

    page, querystring = _paginer(request, qs)
    return render(request, "stock/produit_list.html", {
        "page_obj": page, "querystring": querystring, "q": q,
        "categorie_sel": categorie, "statut_sel": statut,
        "categories": Categorie.objects.all(), "statut_choices": STATUT_CHOICES,
        "can_manage": peut_gerer_stock(request.user),
    })


@stock_consultation_requise
def produit_detail(request, pk):
    produit = get_object_or_404(Produit.objects.select_related("categorie"), pk=pk, actif=True)
    return render(request, "stock/produit_detail.html", {
        "produit": produit,
        "mouvements": produit.mouvements.select_related("utilisateur")[:20],
        "can_manage": peut_gerer_stock(request.user),
    })


@stock_gestion_requise
def produit_create(request):
    form = ProduitForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            produit = form.save()
            quantite = form.cleaned_data.get("quantite_initiale") or 0
            if quantite > 0:
                enregistrer_mouvement(
                    produit=produit, type_mouvement=Type.ENTREE, quantite=quantite,
                    motif=Motif.INITIAL, utilisateur=request.user,
                    commentaire="Création du produit",
                )
        messages.success(request, f"Le produit « {produit.nom} » a été ajouté au stock.")
        return redirect("stock:produit_detail", pk=produit.pk)
    return render(request, "stock/produit_form.html", {
        "form": form, "titre": "Nouveau produit", "active": "produits",
    })


@stock_gestion_requise
def produit_update(request, pk):
    produit = get_object_or_404(Produit, pk=pk, actif=True)
    form = ProduitForm(request.POST or None, instance=produit)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Le produit a été mis à jour.")
        return redirect("stock:produit_detail", pk=produit.pk)
    return render(request, "stock/produit_form.html", {
        "form": form, "produit": produit, "titre": f"Modifier : {produit.nom}", "active": "produits",
    })


@stock_gestion_requise
def produit_delete(request, pk):
    """« Suppression » = retrait du catalogue : l'historique des mouvements est conservé."""
    produit = get_object_or_404(Produit, pk=pk, actif=True)
    if request.method == "POST":
        produit.actif = False
        produit.save(update_fields=["actif", "updated_at"])
        messages.success(request, f"Le produit « {produit.nom} » a été supprimé du catalogue.")
        return redirect("stock:produit_list")
    return render(request, "stock/produit_confirm_delete.html", {"produit": produit})


# --------------------------------------------------------------------------
# Mouvements
# --------------------------------------------------------------------------
@stock_gestion_requise
def mouvement_create(request, pk, type_mouvement):
    types = {"entree": Type.ENTREE, "sortie": Type.SORTIE}
    if type_mouvement not in types:
        raise Http404
    type_m = types[type_mouvement]
    produit = get_object_or_404(Produit, pk=pk, actif=True)

    form = MouvementForm(request.POST or None, type_mouvement=type_m,
                         stock_max=produit.quantite if type_m == Type.SORTIE else None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            enregistrer_mouvement(
                produit=produit, type_mouvement=type_m, quantite=data["quantite"],
                motif=data["motif"], utilisateur=request.user,
                commentaire=data.get("commentaire", ""), numero_lot=data.get("numero_lot", ""),
            )
        except StockError as e:
            form.add_error(None, str(e))
        else:
            messages.success(request, f"{type_m.label} de {data['quantite']} enregistrée pour « {produit.nom} ».")
            return redirect("stock:produit_detail", pk=produit.pk)

    return render(request, "stock/mouvement_form.html", {
        "form": form, "produit": produit, "type_m": type_m, "is_entree": type_m == Type.ENTREE,
    })


@stock_consultation_requise
def mouvement_list(request):
    qs = MouvementStock.objects.select_related("produit", "utilisateur")
    q = request.GET.get("q", "").strip()
    type_sel = request.GET.get("type", "")
    debut = parse_date(request.GET.get("date_debut", "") or "")
    fin = parse_date(request.GET.get("date_fin", "") or "")

    if q:
        qs = qs.filter(Q(produit__nom__icontains=q) | Q(produit__reference__icontains=q))
    if type_sel in Type.values:
        qs = qs.filter(type=type_sel)
    if debut:
        qs = qs.filter(date__date__gte=debut)
    if fin:
        qs = qs.filter(date__date__lte=fin)

    page, querystring = _paginer(request, qs, par_page=20)
    return render(request, "stock/mouvement_list.html", {
        "page_obj": page, "querystring": querystring, "q": q, "type_sel": type_sel,
        "date_debut": request.GET.get("date_debut", ""), "date_fin": request.GET.get("date_fin", ""),
        "types": Type.choices, "can_manage": peut_gerer_stock(request.user),
    })


# --------------------------------------------------------------------------
# Catégories
# --------------------------------------------------------------------------
@stock_consultation_requise
def categorie_list(request):
    categories = Categorie.objects.annotate(nb=Count("produits", filter=Q(produits__actif=True)))
    return render(request, "stock/categorie_list.html", {
        "categories": categories, "form": CategorieForm(),
        "can_manage": peut_gerer_stock(request.user),
    })


@stock_gestion_requise
@require_POST
def categorie_create(request):
    form = CategorieForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "Catégorie ajoutée.")
    else:
        for erreurs in form.errors.values():
            for e in erreurs:
                messages.error(request, e)
    return redirect("stock:categorie_list")


@stock_gestion_requise
@require_POST
def categorie_delete(request, pk):
    categorie = get_object_or_404(Categorie, pk=pk)
    categorie.delete()  # les produits rattachés deviennent « sans catégorie »
    messages.success(request, f"Catégorie « {categorie.nom} » supprimée.")
    return redirect("stock:categorie_list")
