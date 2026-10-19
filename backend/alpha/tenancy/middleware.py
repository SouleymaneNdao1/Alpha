"""Middlewares du contexte tenant (architecture § 3.3).

Ordre dans ``MIDDLEWARE`` :
    SessionMiddleware
    RequestIdMiddleware
    TenantContextMiddleware        # ouvre la transaction et pose le contexte
    CsrfViewMiddleware
    AuthenticationMiddleware
    SessionActiviteMiddleware      # (B5)
    StatutEtablissementMiddleware  # SUSPENDU → 403, LECTURE_SEULE → 423 sur écriture
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse

from alpha.core import contexte
from alpha.core.erreurs import corps_erreur

from .contexte import appliquer_contexte
from .models import Etablissement, StatutEtablissement

journal = logging.getLogger("alpha.tenancy")

ETABLISSEMENT_SUSPENDU = "ETABLISSEMENT_SUSPENDU"
ETABLISSEMENT_LECTURE_SEULE = "ETABLISSEMENT_LECTURE_SEULE"
MESSAGES = {
    ETABLISSEMENT_SUSPENDU: "L'accès à votre établissement est suspendu. "
    "Contactez votre administrateur.",
    ETABLISSEMENT_LECTURE_SEULE: "Votre établissement est en lecture seule : "
    "aucune modification n'est possible.",
}

# Routes d'authentification : toujours accessibles (déconnexion, état de la
# session) ; la connexion traite elle-même le cas SUSPENDU (§ 4.2, étape 4).
PREFIXE_AUTH = "/api/v1/auth/"
METHODES_SURES = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
# Seule route servie sans contexte ni transaction (sonde de santé, ajout B8).
CHEMIN_SANS_CONTEXTE = "/api/v1/sante/"


def _uuid_session(valeur: object) -> uuid.UUID | None:
    if not valeur:
        return None
    try:
        return uuid.UUID(str(valeur))
    except ValueError:
        return None


def lire_contexte_session(request: HttpRequest) -> tuple[uuid.UUID | None, str, uuid.UUID | None]:
    """(tenant, scope, utilisateur) déduits de la session ; incohérent → anonyme (échec fermé)."""
    session = getattr(request, "session", None)
    if session is None:
        return None, contexte.SCOPE_ANONYMOUS, None
    tenant = _uuid_session(session.get("tenant_id"))
    scope = session.get("scope", contexte.SCOPE_ANONYMOUS)
    utilisateur = _uuid_session(session.get("_auth_user_id"))

    if scope == contexte.SCOPE_TENANT and tenant is not None:
        return tenant, scope, utilisateur
    if scope == contexte.SCOPE_PLATFORM and tenant is None:
        return None, scope, utilisateur
    if scope != contexte.SCOPE_ANONYMOUS or tenant is not None:
        journal.warning("Session au contexte incohérent (scope=%r) : traitée en anonyme.", scope)
    return None, contexte.SCOPE_ANONYMOUS, None


class TenantContextMiddleware:
    """Ouvre la transaction la plus externe de la requête et y pose le contexte tenant."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path == CHEMIN_SANS_CONTEXTE:
            # Sonde de santé (alpha.core.sante) : aucune donnée lue, aucune transaction ;
            # elle doit répondre 503 (et non 500) quand la base est indisponible.
            return self.get_response(request)
        tenant, scope, utilisateur = lire_contexte_session(request)
        with transaction.atomic(), appliquer_contexte(tenant, scope, utilisateur):
            response = self.get_response(request)
            if getattr(response, "streaming", False):
                raise ImproperlyConfigured("Pas de réponse streaming sous contexte tenant.")
        return response


class StatutEtablissementMiddleware:
    """Applique le statut de l'établissement courant (§ 3.3).

    - ``SUSPENDU`` ou ``ARCHIVE`` (ou établissement invisible) : 403 ``ETABLISSEMENT_SUSPENDU`` ;
    - ``LECTURE_SEULE`` : 423 ``ETABLISSEMENT_LECTURE_SEULE`` sur les méthodes d'écriture.
    Les routes ``/api/v1/auth/`` ne sont pas concernées.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tenant = contexte.tenant_courant()
        if tenant is not None and not request.path.startswith(PREFIXE_AUTH):
            statut = (
                Etablissement.objects.filter(id=tenant).values_list("statut", flat=True).first()
            )
            if statut != StatutEtablissement.ACTIF:
                if statut == StatutEtablissement.LECTURE_SEULE:
                    if request.method not in METHODES_SURES:
                        return self._refus(ETABLISSEMENT_LECTURE_SEULE, 423)
                else:
                    return self._refus(ETABLISSEMENT_SUSPENDU, 403)
        return self.get_response(request)

    @staticmethod
    def _refus(code: str, statut: int) -> JsonResponse:
        return JsonResponse(
            corps_erreur(code, MESSAGES[code]),
            status=statut,
            json_dumps_params={"ensure_ascii": False},
        )
