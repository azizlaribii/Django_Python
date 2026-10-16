# Installation du module Stocks médicaux (Membre 6)

1. Copier le dossier `stock/` à la racine du projet (à côté de `accounts/` et `config/`).

2. `config/settings.py`
   ```python
   INSTALLED_APPS = [
       ...
       'accounts',
       'stock',
   ]
   # Optionnel : jours avant péremption pour signaler un produit (30 par défaut)
   STOCK_ALERTE_PEREMPTION_JOURS = 30
   ```

3. `config/urls.py`
   ```python
   urlpatterns = [
       path('admin/', admin.site.urls),
       path('stock/', include('stock.urls')),   # <-- ajouter AVANT la ligne accounts
       path('', include('accounts.urls')),
   ]
   ```

4. `templates/base.html` : ajouter le lien dans la navbar, après le lien « Tableau de bord »
   ```html
   {% if user.is_admin_user or user.is_laboratory or user.is_doctor %}
       <a href="{% url 'stock:dashboard' %}" class="nav-item-link" id="nav-stock">📦 Stocks</a>
   {% endif %}
   ```

5. Commandes
   ```bash
   python manage.py migrate
   python manage.py seed_stock          # données de démonstration (optionnel)
   python manage.py check_stock_alerts  # liste les alertes en console
   python manage.py test stock
   ```

## Droits d'accès
| Rôle | Accès |
|---|---|
| Administrateur | Consultation + gestion complète |
| Laboratoire | Consultation + gestion complète |
| Docteur | Consultation seule |
| Patient | Aucun accès (redirigé avec un message) |

## Points d'intégration
- `stock.services.get_alertes()` renvoie les produits en rupture, à stock faible, périmés ou proches de la péremption : à brancher sur le module Notifications.
- `stock.services.enregistrer_mouvement(...)` est le seul point d'entrée pour modifier une quantité (à appeler depuis les modules Laboratoire/Examens quand un consommable est utilisé).
