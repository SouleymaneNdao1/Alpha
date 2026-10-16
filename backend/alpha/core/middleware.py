"""Middlewares transverses (architecture § 3.3)."""

from __future__ import annotations

import ipaddress
import re
import uuid
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from alpha.core import contexte

ENTETE_REQUEST_ID = "X-Request-ID"
# Identifiant reçu accepté tel quel s'il est court et sans caractère exotique
# (il finit dans les journaux et dans l'audit : pas d'injection possible).
_REQUEST_ID_VALIDE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def _ip_valide(valeur: str) -> str | None:
    try:
        return str(ipaddress.ip_address(valeur.strip()))
    except ValueError:
        return None


def ip_client(request: HttpRequest, nb_proxies: int) -> str | None:
    """IP réelle du client derrière ``nb_proxies`` proxys de confiance (Caddy = 1).

    Chaque proxy de confiance AJOUTE l'adresse de son pair à droite de
    X-Forwarded-For : on lit donc la n-ième valeur en partant de la droite.
    Les valeurs plus à gauche sont fournies par le client et ignorées.
    """
    distante = request.META.get("REMOTE_ADDR")
    if nb_proxies > 0:
        transmis = request.META.get("HTTP_X_FORWARDED_FOR", "")
        adresses = [a for a in (x.strip() for x in transmis.split(",")) if a]
        if len(adresses) >= nb_proxies:
            candidate = _ip_valide(adresses[-nb_proxies])
            if candidate:
                return candidate
    return _ip_valide(distante) if distante else None


class RequestIdMiddleware:
    """Pose ``request_id`` et ``ip`` dans ``alpha.core.contexte`` pour la durée de la requête.

    - reprend l'en-tête X-Request-ID entrant s'il est valide (posé par Caddy ou
      par le frontend), sinon en génère un ;
    - le renvoie dans la réponse (en-tête X-Request-ID) ;
    - rétablit le contexte à la fin de la requête, même en cas d'exception.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.nb_proxies = int(getattr(settings, "ALPHA_NB_PROXIES_CONFIANCE", 1))

    def __call__(self, request: HttpRequest) -> HttpResponse:
        recu = request.headers.get(ENTETE_REQUEST_ID, "")
        rid = recu if _REQUEST_ID_VALIDE.match(recu) else uuid.uuid4().hex
        adresse = ip_client(request, self.nb_proxies)

        request.request_id = rid  # type: ignore[attr-defined]
        request.ip_client = adresse  # type: ignore[attr-defined]

        jetons = contexte.definir(request_id=rid, ip=adresse)
        try:
            response = self.get_response(request)
        finally:
            contexte.restaurer(jetons)
        response[ENTETE_REQUEST_ID] = rid
        return response
