"""Pose du contexte tenant dans PostgreSQL et dans l'application (architecture § 3.2, § 3.3).

Deux barrières sont alimentées en même temps :

- les ``contextvars`` d'``alpha.core.contexte`` (lus par ``TenantManager`` et
  ``TenantModel.save``) ;
- les variables de session PostgreSQL ``app.current_tenant``, ``app.scope`` et
  ``app.current_user`` (lues par les fonctions ``app_*()`` et donc par les
  politiques RLS), toujours posées par ``set_config(…, true)`` : elles sont
  LOCALES À LA TRANSACTION et disparaissent au COMMIT/ROLLBACK, ce qui empêche
  toute fuite d'un établissement à l'autre via une connexion persistante.

Points d'entrée :

- ``contexte_tenant(etablissement_id, scope="tenant")`` : gestionnaire de
  contexte qui ouvre un bloc atomique (transaction, ou point de sauvegarde si
  une transaction est déjà ouverte), pose le contexte, puis rétablit la valeur
  précédente à la sortie. Usage : connexion (le tenant n'est connu qu'après
  résolution de l'e-mail), tâches Celery, provisionnement par le super-admin.
- ``appliquer_contexte(...)`` : même pose, SANS ouvrir de bloc atomique ; à
  utiliser à l'intérieur d'une transaction déjà ouverte (``TenantContextMiddleware``).

Rétablissement à la sortie :
- sortie normale : les variables SQL et les contextvars reprennent leurs
  valeurs précédentes (``set_config`` explicite) ;
- sortie sur exception : les contextvars sont rétablies ; côté PostgreSQL,
  l'annulation du point de sauvegarde (ou de la transaction) annule aussi les
  ``set_config`` faits à l'intérieur.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from django.db import DEFAULT_DB_ALIAS, connections, transaction

from alpha.core import contexte

# Valeur sentinelle : « ne pas changer l'utilisateur courant ».
INCHANGE: Any = object()

_SQL_POSER = (
    "SELECT set_config('app.current_tenant', %s, true), "
    "set_config('app.scope', %s, true), "
    "set_config('app.current_user', %s, true)"
)


def _uuid_ou_none(valeur: Any) -> uuid.UUID | None:
    """Convertit en UUID ; ``None`` et ``""`` donnent ``None``. Lève ValueError sinon."""
    if valeur is None or valeur == "":
        return None
    if isinstance(valeur, uuid.UUID):
        return valeur
    if not isinstance(valeur, str):
        # Garde-fou : jamais d'objet ORM (ou autre) à la place d'un identifiant (§ 3.7).
        raise ValueError(f"Identifiant attendu (uuid ou chaîne), reçu : {type(valeur).__name__}.")
    return uuid.UUID(valeur)


def _verifier_coherence(tenant: uuid.UUID | None, scope: str) -> None:
    if scope not in contexte.SCOPES:
        raise ValueError(f"Portée inconnue : {scope!r}.")
    if scope == contexte.SCOPE_TENANT and tenant is None:
        raise ValueError("La portée « tenant » exige un identifiant d'établissement.")
    if scope != contexte.SCOPE_TENANT and tenant is not None:
        raise ValueError(f"La portée « {scope} » ne doit pas désigner d'établissement.")


def poser_variables_sql(
    tenant: uuid.UUID | None,
    scope: str,
    utilisateur: uuid.UUID | None,
    using: str = DEFAULT_DB_ALIAS,
) -> None:
    """Pose les trois variables ``app.*`` (locales à la transaction) sur la connexion ``using``."""
    connexion = connections[using]
    if not connexion.in_atomic_block:
        # Hors transaction, set_config(…, true) serait perdu dès la fin de l'instruction.
        raise RuntimeError("Les variables app.* doivent être posées dans un bloc atomique.")
    with connexion.cursor() as curseur:
        curseur.execute(
            _SQL_POSER,
            [str(tenant) if tenant else "", scope, str(utilisateur) if utilisateur else ""],
        )


@contextmanager
def appliquer_contexte(
    etablissement_id: Any,
    scope: str,
    utilisateur_id: Any = INCHANGE,
    *,
    using: str = DEFAULT_DB_ALIAS,
) -> Iterator[None]:
    """Pose le contexte (SQL + contextvars) dans le bloc atomique déjà ouvert, puis le rétablit."""
    tenant = _uuid_ou_none(etablissement_id)
    _verifier_coherence(tenant, scope)
    utilisateur = (
        contexte.utilisateur_courant()
        if utilisateur_id is INCHANGE
        else _uuid_ou_none(utilisateur_id)
    )
    precedent = (
        contexte.tenant_courant(),
        contexte.scope_courant(),
        contexte.utilisateur_courant(),
    )

    poser_variables_sql(tenant, scope, utilisateur, using)
    jetons = contexte.definir(tenant=tenant, scope=scope, utilisateur=utilisateur)
    try:
        yield
    finally:
        contexte.restaurer(jetons)
    # Sortie normale uniquement (sur exception, le rollback rétablit les variables SQL).
    connexion = connections[using]
    if connexion.in_atomic_block and not connexion.needs_rollback:
        poser_variables_sql(*precedent, using=using)


@contextmanager
def contexte_tenant(
    etablissement_id: Any,
    scope: str = contexte.SCOPE_TENANT,
    *,
    utilisateur_id: Any = INCHANGE,
    using: str = DEFAULT_DB_ALIAS,
) -> Iterator[None]:
    """Exécute le bloc sous le contexte de l'établissement donné (§ 3.3).

    - ``scope="tenant"`` (défaut) : ``etablissement_id`` obligatoire ;
    - ``scope="worker"`` / ``"platform"`` / ``"anonymous"`` : ``etablissement_id``
      doit être ``None`` (ex. ``contexte_tenant(None, scope="worker")`` pour les
      tâches transverses, qui ne voient que la liste des établissements) ;
    - ``utilisateur_id`` : par défaut, l'utilisateur courant est conservé.

    Le bloc est atomique : en cas d'exception, tout ce qu'il a écrit est annulé.
    """
    with (
        transaction.atomic(using=using),
        appliquer_contexte(etablissement_id, scope, utilisateur_id, using=using),
    ):
        yield
