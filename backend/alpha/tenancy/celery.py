"""Décorateur des tâches Celery liées à un établissement (architecture § 3.7).

    @tache_tenant(queue="defaut")
    def envoyer_email_invitation(etablissement_id, jeton_id): ...

    envoyer_email_invitation.delay(str(etab.id), str(jeton.id))

Règles :
- ``etablissement_id`` est TOUJOURS le premier argument (uuid ou chaîne),
  jamais un objet ORM sérialisé ;
- la tâche s'exécute dans ``transaction.atomic()`` + ``contexte_tenant(etablissement_id)``
  (portée « tenant », aucun utilisateur) : le worker, connecté en alpha_app,
  ne voit que les lignes de cet établissement ;
- planifier l'envoi depuis le code applicatif avec ``transaction.on_commit``.

Les tâches transverses (planifiées) n'utilisent pas ce décorateur : elles
ouvrent ``contexte_tenant(None, scope="worker")`` puis appellent une tâche
``tache_tenant`` par établissement.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from celery import shared_task

from alpha.core import contexte

from .contexte import contexte_tenant
from .exceptions import TenantNonDefini


def tache_tenant(**options: Any) -> Callable[[Callable[..., Any]], Any]:
    """Déclare une tâche Celery exécutée sous le contexte de l'établissement passé en 1er argument.

    ``options`` est transmis à ``shared_task`` (file ``defaut`` par défaut).
    """
    options.setdefault("queue", "defaut")

    def decorateur(fonction: Callable[..., Any]) -> Any:
        @functools.wraps(fonction)
        def enveloppe(etablissement_id: Any, *args: Any, **kwargs: Any) -> Any:
            if etablissement_id is None or etablissement_id == "":
                raise TenantNonDefini(
                    f"Tâche {fonction.__name__} appelée sans identifiant d'établissement."
                )
            with contexte_tenant(
                etablissement_id, scope=contexte.SCOPE_TENANT, utilisateur_id=None
            ):
                return fonction(etablissement_id, *args, **kwargs)

        return shared_task(**options)(enveloppe)

    return decorateur
