"""Contexte de la requête ou de la tâche en cours (architecture § 3.3).

Les valeurs sont portées par des ``contextvars`` : chaque thread gunicorn et
chaque tâche Celery a son propre contexte, sans fuite d'une requête à l'autre.

Lecture (partout dans le code) :
    tenant_courant(), scope_courant(), utilisateur_courant(), ip(), request_id(),
    user_agent()

Écriture (réservée aux middlewares, à ``contexte_tenant`` et au décorateur
``tache_tenant``) : ``definir(...)`` renvoie des jetons à rendre à
``restaurer(...)``, ou ``contexte(...)`` comme gestionnaire de contexte.

Ce module ne touche pas à PostgreSQL : la pose des variables de session
``app.*`` (``set_config``) relève de ``alpha.tenancy`` (tâche B2).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

# Portées possibles (miroir de la variable PostgreSQL app.scope, § 3.2).
SCOPE_TENANT = "tenant"
SCOPE_PLATFORM = "platform"
SCOPE_WORKER = "worker"
SCOPE_ANONYMOUS = "anonymous"
SCOPES = (SCOPE_TENANT, SCOPE_PLATFORM, SCOPE_WORKER, SCOPE_ANONYMOUS)

_tenant: ContextVar[uuid.UUID | None] = ContextVar("alpha_tenant", default=None)
_scope: ContextVar[str] = ContextVar("alpha_scope", default=SCOPE_ANONYMOUS)
_utilisateur: ContextVar[uuid.UUID | None] = ContextVar("alpha_utilisateur", default=None)
_ip: ContextVar[str | None] = ContextVar("alpha_ip", default=None)
_request_id: ContextVar[str | None] = ContextVar("alpha_request_id", default=None)
# Ajout B4 : le journal d'audit enregistre le user agent du client (§ 6.1).
_user_agent: ContextVar[str | None] = ContextVar("alpha_user_agent", default=None)

_VARIABLES: dict[str, ContextVar[Any]] = {
    "tenant": _tenant,
    "scope": _scope,
    "utilisateur": _utilisateur,
    "ip": _ip,
    "request_id": _request_id,
    "user_agent": _user_agent,
}


def tenant_courant() -> uuid.UUID | None:
    """Identifiant de l'établissement courant, ou None (aucun accès aux tables tenant)."""
    return _tenant.get()


def scope_courant() -> str:
    """Portée courante : « tenant », « platform », « worker » ou « anonymous »."""
    return _scope.get()


def utilisateur_courant() -> uuid.UUID | None:
    """Identifiant de l'utilisateur authentifié, ou None."""
    return _utilisateur.get()


def ip() -> str | None:
    """Adresse IP réelle du client (après prise en compte du proxy de confiance)."""
    return _ip.get()


def request_id() -> str | None:
    """Identifiant de corrélation de la requête (en-tête X-Request-ID)."""
    return _request_id.get()


def user_agent() -> str | None:
    """En-tête User-Agent du client (tronqué à 300 caractères), ou None hors requête."""
    return _user_agent.get()


def _normaliser_uuid(valeur: Any) -> uuid.UUID | None:
    if valeur is None or valeur == "":
        return None
    if isinstance(valeur, uuid.UUID):
        return valeur
    return uuid.UUID(str(valeur))


def definir(**valeurs: Any) -> dict[str, Token[Any]]:
    """Pose une ou plusieurs valeurs du contexte et renvoie les jetons de restauration.

    Clés acceptées : tenant, scope, utilisateur, ip, request_id, user_agent.
    """
    inconnues = set(valeurs) - set(_VARIABLES)
    if inconnues:
        raise ValueError(f"Clés de contexte inconnues : {', '.join(sorted(inconnues))}.")
    if "tenant" in valeurs:
        valeurs["tenant"] = _normaliser_uuid(valeurs["tenant"])
    if "utilisateur" in valeurs:
        valeurs["utilisateur"] = _normaliser_uuid(valeurs["utilisateur"])
    if "scope" in valeurs and valeurs["scope"] not in SCOPES:
        raise ValueError(f"Portée inconnue : {valeurs['scope']!r}.")
    return {cle: _VARIABLES[cle].set(valeur) for cle, valeur in valeurs.items()}


def restaurer(jetons: dict[str, Token[Any]]) -> None:
    """Rétablit les valeurs antérieures à l'appel de ``definir`` correspondant."""
    for cle, jeton in reversed(list(jetons.items())):
        _VARIABLES[cle].reset(jeton)


@contextmanager
def contexte(**valeurs: Any) -> Iterator[None]:
    """Gestionnaire de contexte : pose les valeurs, puis les rétablit à la sortie."""
    jetons = definir(**valeurs)
    try:
        yield
    finally:
        restaurer(jetons)


def instantane() -> dict[str, Any]:
    """Copie des valeurs courantes (journalisation, diagnostic)."""
    return {cle: variable.get() for cle, variable in _VARIABLES.items()}
