"""Sonde de santé publique ``GET /api/v1/sante/`` (demande DevOps, docs/ops/monitoring.md).

- 200 ``{"statut": "ok"}`` si PostgreSQL et Redis répondent ;
- 503 ``{"statut": "indisponible"}`` sinon.

La réponse ne révèle AUCUN détail interne (ni quel service manque, ni version, ni
message d'erreur) ; la cause est seulement écrite dans les journaux du conteneur.
Rien n'est écrit dans le journal d'audit ni dans la base : la base n'est interrogée
que par ``SELECT 1``, sans contexte tenant (aucune table lue).

La vue est une vue Django simple (hors DRF : pas d'authentification ni de session) ;
``TenantContextMiddleware`` la laisse passer sans ouvrir de transaction (sinon une
base indisponible ferait échouer le middleware en 500 avant la vue) et
``non_atomic_requests`` la soustrait à ``ATOMIC_REQUESTS``.
"""

from __future__ import annotations

import logging

from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

journal = logging.getLogger("alpha.sante")

CHEMIN_SANTE = "/api/v1/sante/"


def base_disponible() -> bool:
    connexion = connections[DEFAULT_DB_ALIAS]
    try:
        with connexion.cursor() as curseur:
            curseur.execute("SELECT 1")
            return curseur.fetchone() == (1,)
    except Exception as exc:
        journal.warning("Sonde de santé : base indisponible (%s).", type(exc).__name__)
        connexion.close_if_unusable_or_obsolete()
        return False


def redis_disponible() -> bool:
    try:
        from django_redis import get_redis_connection

        return bool(get_redis_connection("default").ping())
    except Exception as exc:
        journal.warning("Sonde de santé : Redis indisponible (%s).", type(exc).__name__)
        return False


@never_cache
@require_safe
@transaction.non_atomic_requests
def sante(request: HttpRequest) -> JsonResponse:
    # Les deux contrôles sont toujours exécutés (journaux complets) ; réponse sans détail.
    base, redis = base_disponible(), redis_disponible()
    if base and redis:
        return JsonResponse({"statut": "ok"})
    return JsonResponse({"statut": "indisponible"}, status=503)
