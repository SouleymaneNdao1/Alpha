"""Tâches planifiées des délégations (architecture § 3.7, § 6.5) : toutes les 5 minutes.

- ``delegations.activer_delegations`` : date l'entrée en vigueur des délégations
  ACTIVES dont le début est atteint (``activee_le``, audit ``delegation.active``) ;
- ``delegations.cloturer_delegations`` : passe à TERMINEE les délégations ACTIVES
  dont la fin est passée (audit ``delegation.terminee``).

Les orchestrateurs ouvrent ``contexte_tenant(None, scope="worker")`` (liste des
établissements seulement), puis lancent une sous-tâche ``tache_tenant`` par
établissement. Tout est idempotent : un second passage ne trouve plus rien à faire
(filtre sur le statut et ``activee_le``, verrou ``SKIP LOCKED``).
"""

from __future__ import annotations

from celery import shared_task

from alpha.core import contexte
from alpha.tenancy.celery import tache_tenant
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement

from . import services


def _etablissements() -> list[str]:
    with contexte_tenant(None, scope=contexte.SCOPE_WORKER, utilisateur_id=None):
        return [str(i) for i in Etablissement.objects.order_by("code").values_list("id", flat=True)]


@tache_tenant(name="delegations.activer_delegations_etablissement")
def activer_delegations_etablissement(etablissement_id: str) -> int:
    return services.activer_delegations_echues()


@tache_tenant(name="delegations.cloturer_delegations_etablissement")
def cloturer_delegations_etablissement(etablissement_id: str) -> int:
    return services.cloturer_delegations_echues()


@shared_task(name="delegations.activer_delegations")
def activer_delegations() -> int:
    identifiants = _etablissements()
    for etablissement_id in identifiants:
        activer_delegations_etablissement.delay(etablissement_id)
    return len(identifiants)


@shared_task(name="delegations.cloturer_delegations")
def cloturer_delegations() -> int:
    identifiants = _etablissements()
    for etablissement_id in identifiants:
        cloturer_delegations_etablissement.delay(etablissement_id)
    return len(identifiants)
