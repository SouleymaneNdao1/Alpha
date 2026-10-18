"""Connexions de test (tâche T1, § 8) : rôle applicatif par défaut, propriétaire à la demande.

Montage (voir ``config.settings.test`` et ``docs/tests.md``) :

- ``default``      : alpha_app, soumis à la RLS — TOUS les tests s'exécutent sous ce rôle ;
- ``proprietaire`` : alpha_owner (BYPASSRLS, propriétaire des tables), miroir de la même
  base. Réservé aux tests qui contournent volontairement les protections : altération du
  journal d'audit, lecture « hors RLS » pour vérifier ce qui a réellement été écrit ;
- ``audit``        : alpha_app, connexion indépendante du journal d'audit (B4).

Une connexion ne voit que les données VALIDÉES par une autre : un test qui utilise
``proprietaire`` ou ``audit`` en plus de ``default`` est transactionnel :
``pytest.mark.django_db(transaction=True, databases=BASES_PROPRIETAIRE)``.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from django.db import DEFAULT_DB_ALIAS, connections, transaction

ALIAS_APP = DEFAULT_DB_ALIAS
ALIAS_PROPRIETAIRE = "proprietaire"
ALIAS_AUDIT = "audit"
BASES_PROPRIETAIRE = [ALIAS_APP, ALIAS_PROPRIETAIRE]
TOUTES_LES_BASES = [ALIAS_APP, ALIAS_PROPRIETAIRE, ALIAS_AUDIT]

_CLES_IDENTITE = ("USER", "PASSWORD")


@contextmanager
def default_en_proprietaire() -> Iterator[None]:
    """Fait temporairement passer la connexion ``default`` sous alpha_owner.

    Réservé à l'infrastructure : création et migration de la base de test, vidage
    (TRUNCATE) des tests transactionnels. Le dictionnaire de réglages est partagé
    par les connexions de tous les fils : la bascule vaut pour tout le processus.
    Aucune transaction ne doit être ouverte sur ``default``.
    """
    connexion = connections[DEFAULT_DB_ALIAS]
    reglages = connexion.settings_dict
    proprietaire = connections.settings[ALIAS_PROPRIETAIRE]
    sauvegarde = {cle: reglages[cle] for cle in _CLES_IDENTITE}
    connexion.close()
    reglages.update({cle: proprietaire[cle] for cle in _CLES_IDENTITE})
    try:
        yield
    finally:
        connexion.close()
        reglages.update(sauvegarde)


def role_courant(alias: str = DEFAULT_DB_ALIAS) -> str:
    with connections[alias].cursor() as curseur:
        curseur.execute("SELECT current_user")
        return curseur.fetchone()[0]


def sql(alias: str, requete: str, parametres: Sequence[Any] | None = None) -> list[tuple]:
    """Exécute une requête SQL brute et renvoie ses lignes (liste vide sans résultat)."""
    with connections[alias].cursor() as curseur:
        curseur.execute(requete, parametres)
        return curseur.fetchall() if curseur.description else []


def sql_proprietaire(requete: str, parametres: Sequence[Any] | None = None) -> list[tuple]:
    """Lecture/écriture « hors RLS » par alpha_owner (test transactionnel obligatoire)."""
    with transaction.atomic(using=ALIAS_PROPRIETAIRE):
        return sql(ALIAS_PROPRIETAIRE, requete, parametres)
