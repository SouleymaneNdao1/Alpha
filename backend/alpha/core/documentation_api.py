"""Routes du schéma OpenAPI et de la documentation interactive, selon l'environnement.

| Environnement | ``ALPHA_DOC_API_ACTIVE`` | ``…_RESERVEE_CONNECTES`` | Effet                         |
|---------------|--------------------------|--------------------------|-------------------------------|
| dev, test     | vrai                     | faux                     | ouverts (types du frontend)   |
| recette       | vrai                     | vrai                     | utilisateur connecté exigé (401 sinon) |
| production    | faux                     | —                        | non routés (404)              |
"""

from __future__ import annotations

from django.urls import URLPattern, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated


def routes_documentation(*, active: bool, reservee_connectes: bool) -> list[URLPattern]:
    if not active:
        return []
    acces = (
        {"authentication_classes": [SessionAuthentication], "permission_classes": [IsAuthenticated]}
        if reservee_connectes
        else {"authentication_classes": [], "permission_classes": [AllowAny]}
    )
    return [
        path("api/v1/schema/", SpectacularAPIView.as_view(**acces), name="schema"),
        path(
            "api/v1/docs/",
            SpectacularSwaggerView.as_view(url_name="schema", **acces),
            name="documentation",
        ),
    ]
