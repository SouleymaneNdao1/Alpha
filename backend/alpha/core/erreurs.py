"""Format d'erreur unique de l'API (architecture § 5).

Toute erreur renvoyée par l'API a la forme ::

    {"code": "IDENTIFIANTS_INVALIDES", "message": "Adresse e-mail ou mot de passe incorrect.",
     "details": {...}}

- ``code`` : constante stable en MAJUSCULES, exploitée par le frontend ;
- ``message`` : texte en français, affichable tel quel ;
- ``details`` : objet (éventuellement vide). Erreurs de validation : 400
  ``VALIDATION`` avec ``details = {"champ": ["message"]}``.

Ce module fournit :
- ``ErreurApi`` : exception à lever (ou à convertir en réponse avec
  ``reponse_erreur``) pour une erreur métier ;
- ``gestionnaire_exceptions`` : EXCEPTION_HANDLER de DRF ;
- les vues d'erreur Django (404, 400, 403, 500, échec CSRF) au même format,
  pour les URL qui ne passent pas par DRF.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, HttpRequest, JsonResponse
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as gestionnaire_drf

journal = logging.getLogger("alpha.erreurs")

# Codes génériques (les codes métier sont définis par chaque application).
VALIDATION = "VALIDATION"
REQUETE_INVALIDE = "REQUETE_INVALIDE"
NON_AUTHENTIFIE = "NON_AUTHENTIFIE"
PERMISSION_REFUSEE = "PERMISSION_REFUSEE"
CSRF_INVALIDE = "CSRF_INVALIDE"
INTROUVABLE = "INTROUVABLE"
METHODE_NON_AUTORISEE = "METHODE_NON_AUTORISEE"
FORMAT_NON_ACCEPTABLE = "FORMAT_NON_ACCEPTABLE"
TYPE_CONTENU_NON_SUPPORTE = "TYPE_CONTENU_NON_SUPPORTE"
TROP_DE_REQUETES = "TROP_DE_REQUETES"
ERREUR_INTERNE = "ERREUR_INTERNE"

MESSAGES: dict[str, str] = {
    VALIDATION: "Certaines données sont invalides.",
    REQUETE_INVALIDE: "La requête est mal formée.",
    NON_AUTHENTIFIE: "Vous devez être connecté pour effectuer cette action.",
    PERMISSION_REFUSEE: "Vous n'avez pas les droits nécessaires pour effectuer cette action.",
    CSRF_INVALIDE: "La vérification de sécurité a échoué. Rechargez la page puis réessayez.",
    INTROUVABLE: "La ressource demandée est introuvable.",
    METHODE_NON_AUTORISEE: "Cette méthode n'est pas autorisée sur cette ressource.",
    FORMAT_NON_ACCEPTABLE: "Le format de réponse demandé n'est pas disponible.",
    TYPE_CONTENU_NON_SUPPORTE: "Le type de contenu envoyé n'est pas pris en charge.",
    TROP_DE_REQUETES: "Trop de tentatives. Patientez avant de réessayer.",
    ERREUR_INTERNE: "Une erreur inattendue s'est produite. Réessayez plus tard.",
}


class ErreurApi(exceptions.APIException):
    """Erreur métier au format ALPHA.

    Exemple : ``raise ErreurApi("ETAPE_INVALIDE", "Cette étape est déjà franchie.", statut=409)``.

    Rappel (§ 3.3) : une vue qui doit conserver ses écritures (audit d'un échec
    de connexion, par exemple) RENVOIE ``reponse_erreur(...)`` au lieu de lever
    l'exception, sinon le point de sauvegarde de la vue est annulé.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = REQUETE_INVALIDE
    default_detail = MESSAGES[REQUETE_INVALIDE]

    def __init__(
        self,
        code: str,
        message: str,
        *,
        statut: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail=message, code=code)
        self.code = code
        self.message = message
        self.status_code = statut
        self.details = details or {}


def corps_erreur(code: str, message: str | None = None, details: Any = None) -> dict[str, Any]:
    """Corps JSON d'une erreur ; ``message`` par défaut selon le code."""
    return {
        "code": code,
        "message": message or MESSAGES.get(code, MESSAGES[ERREUR_INTERNE]),
        "details": details if details is not None else {},
    }


def reponse_erreur(
    code: str,
    message: str | None = None,
    *,
    statut: int = status.HTTP_400_BAD_REQUEST,
    details: Any = None,
    entetes: dict[str, str] | None = None,
) -> Response:
    """Réponse DRF au format d'erreur ALPHA (à RENVOYER depuis une vue)."""
    return Response(corps_erreur(code, message, details), status=statut, headers=entetes)


def _details_validation(detail: Any) -> dict[str, Any]:
    """Normalise les erreurs de validation DRF en ``{"champ": ["message", ...]}``."""
    if isinstance(detail, dict):
        return {cle: _details_validation_valeur(valeur) for cle, valeur in detail.items()}
    # Erreur non rattachée à un champ (liste ou chaîne).
    return {"non_field_errors": _details_validation_valeur(detail)}


def _details_validation_valeur(valeur: Any) -> Any:
    if isinstance(valeur, dict):
        return {cle: _details_validation_valeur(v) for cle, v in valeur.items()}
    if isinstance(valeur, list):
        return [_details_validation_valeur(v) for v in valeur]
    return str(valeur)


def _code_et_message(exc: exceptions.APIException) -> tuple[str, str, Any]:
    """Code, message et détails pour une exception DRF standard."""
    if isinstance(exc, ErreurApi):
        return exc.code, exc.message, exc.details
    if isinstance(exc, exceptions.ValidationError):
        return VALIDATION, MESSAGES[VALIDATION], _details_validation(exc.detail)
    if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
        return NON_AUTHENTIFIE, MESSAGES[NON_AUTHENTIFIE], {}
    if isinstance(exc, exceptions.PermissionDenied):
        # SessionAuthentication de DRF lève PermissionDenied("CSRF Failed: …").
        if str(exc.detail).startswith("CSRF Failed"):
            return CSRF_INVALIDE, MESSAGES[CSRF_INVALIDE], {}
        return PERMISSION_REFUSEE, MESSAGES[PERMISSION_REFUSEE], {}
    if isinstance(exc, exceptions.NotFound):
        return INTROUVABLE, MESSAGES[INTROUVABLE], {}
    if isinstance(exc, exceptions.MethodNotAllowed):
        return METHODE_NON_AUTORISEE, MESSAGES[METHODE_NON_AUTORISEE], {}
    if isinstance(exc, exceptions.NotAcceptable):
        return FORMAT_NON_ACCEPTABLE, MESSAGES[FORMAT_NON_ACCEPTABLE], {}
    if isinstance(exc, exceptions.UnsupportedMediaType):
        return TYPE_CONTENU_NON_SUPPORTE, MESSAGES[TYPE_CONTENU_NON_SUPPORTE], {}
    if isinstance(exc, exceptions.Throttled):
        details = {"reessayer_dans_s": exc.wait} if exc.wait is not None else {}
        return TROP_DE_REQUETES, MESSAGES[TROP_DE_REQUETES], details
    if isinstance(exc, exceptions.ParseError):
        return REQUETE_INVALIDE, MESSAGES[REQUETE_INVALIDE], {}
    # Autre APIException : code DRF en majuscules, message DRF (traduit en français).
    code = exc.get_codes() if isinstance(exc.get_codes(), str) else exc.default_code
    return str(code).upper(), str(exc.detail), {}


def gestionnaire_exceptions(exc: Exception, contexte: dict[str, Any]) -> Response | None:
    """EXCEPTION_HANDLER de DRF : convertit toute erreur au format ALPHA.

    Les exceptions non prévues (erreurs de programmation) ne sont pas
    interceptées : Django les journalise et ``vue_500`` répond.
    """
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    reponse = gestionnaire_drf(exc, contexte)
    if reponse is None or not isinstance(exc, exceptions.APIException):
        return reponse

    code, message, details = _code_et_message(exc)
    reponse.data = corps_erreur(code, message, details)
    if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
        # DRF répond 403 quand l'authentification n'a pas d'en-tête WWW-Authenticate
        # (cas des sessions) ; le contrat d'API impose 401 pour « non authentifié ».
        reponse.status_code = status.HTTP_401_UNAUTHORIZED
    return reponse


# --- Vues d'erreur Django (hors DRF) ----------------------------------------------


def _json_erreur(code: str, statut: int) -> JsonResponse:
    return JsonResponse(
        corps_erreur(code), status=statut, json_dumps_params={"ensure_ascii": False}
    )


def vue_400(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return _json_erreur(REQUETE_INVALIDE, status.HTTP_400_BAD_REQUEST)


def vue_403(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return _json_erreur(PERMISSION_REFUSEE, status.HTTP_403_FORBIDDEN)


def vue_404(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return _json_erreur(INTROUVABLE, status.HTTP_404_NOT_FOUND)


def vue_500(request: HttpRequest) -> JsonResponse:
    return _json_erreur(ERREUR_INTERNE, status.HTTP_500_INTERNAL_SERVER_ERROR)


def vue_echec_csrf(request: HttpRequest, reason: str = "") -> JsonResponse:
    """CSRF_FAILURE_VIEW : refus du CsrfViewMiddleware (vues décorées ``csrf_protect``)."""
    journal.warning("Échec de la vérification CSRF : %s", reason)
    return _json_erreur(CSRF_INVALIDE, status.HTTP_403_FORBIDDEN)
