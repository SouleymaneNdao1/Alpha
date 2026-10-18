"""Authentification DRF par session avec CSRF TOUJOURS exigé (architecture § 4.1).

``SessionAuthentication`` de DRF ne contrôle le CSRF que pour un utilisateur
authentifié. Les vues anonymes de ``/auth/`` (connexion, MFA…) doivent aussi
être protégées (« login CSRF ») : ``SessionCsrfObligatoire`` vérifie le jeton
``X-CSRFToken`` sur toute méthode non sûre, que l'utilisateur soit connecté ou non.
Refus : 403 ``CSRF_INVALIDE``.
"""

from __future__ import annotations

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import SessionAuthentication

METHODES_SURES = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class SessionCsrfObligatoire(SessionAuthentication):
    def authenticate(self, request):
        if request.method not in METHODES_SURES:
            self.enforce_csrf(request)
        return super().authenticate(request)


class SchemaSessionCsrfObligatoire(OpenApiAuthenticationExtension):
    """Schéma OpenAPI : même cookie de session que ``SessionAuthentication``."""

    target_class = "alpha.comptes.authentification.SessionCsrfObligatoire"
    name = "cookieAuth"

    def get_security_definition(self, auto_schema):
        from django.conf import settings

        return {"type": "apiKey", "in": "cookie", "name": settings.SESSION_COOKIE_NAME}
