"""URLconf de test : routage de la recette (schéma et documentation réservés aux connectés)."""

from alpha.core.documentation_api import routes_documentation
from config.urls import urlpatterns as _base

urlpatterns = [
    *(p for p in _base if getattr(p, "name", None) not in ("schema", "documentation")),
    *routes_documentation(active=True, reservee_connectes=True),
]
