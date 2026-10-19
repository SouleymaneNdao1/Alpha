"""URLconf de test : routage de la production (schéma et documentation absents)."""

from config.urls import handler404  # noqa: F401
from config.urls import urlpatterns as _base

urlpatterns = [p for p in _base if getattr(p, "name", None) not in ("schema", "documentation")]
